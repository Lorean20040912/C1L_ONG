"""Asistentul „Închiderea lunii”: pași cu previzualizare → executare → anulare (docs/02 §4).

Fiecare lună are un rând `month_close_runs` și un document-registrator; pasul
executat înregistrează pe acest document, deci Dt/Kt arată exact ce a făcut
închiderea. Implementate: amortizarea, calculul salariului (app/payroll/calc.py,
cu rezultatele înghețate în payroll_entries), veniturile, verificările; ceilalți
pași din ToR (repartizare pe granturi, diferențe de curs...) apar ca „în lucru”.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants import allocation as grant_allocation
from app.month_close.depreciation import DepreciationPlan, month_bounds, plan
from app.month_close.models import MonthCloseRun
from app.month_close.steps import StepResult, StepRow, checks, income_plan
from app.payroll import calc as payroll_calc
from app.payroll.service import clear_entries, store_entries
from app.posting.engine import PostingError, post_document, unpost_document

# pașii din ToR F2b.4, în ordine; `implemented` = are deja calcul
STEPS = [
    ("depreciation", "Calculul amortizării", True),
    ("payroll", "Calculul salariului", True),
    ("grant_allocation", "Repartizarea cheltuielilor pe granturi", True),
    ("fx_difference", "Diferențe de curs valutar", False),
    ("special_purpose_income", "Recunoașterea veniturilor din mijloace cu destinație specială", True),
    ("account_closing", "Închiderea conturilor", False),
    ("checks", "Verificări (Dt = Kt, solduri negative, documente neînregistrate)", True),
]


OPTIONAL_STEPS = {"grant_allocation"}


def get_run(db: Session, organization_id: uuid.UUID, year: int, month: int, lock: bool = False) -> MonthCloseRun | None:
    query = select(MonthCloseRun).where(
        MonthCloseRun.organization_id == organization_id, MonthCloseRun.year == year, MonthCloseRun.month == month
    )
    return db.scalar(query.with_for_update() if lock else query)


def steps_view(run: MonthCloseRun | None) -> list[dict]:
    saved = {s["step"]: s for s in (run.steps or [])} if run else {}
    return [
        {"step": code, "title": title, "implemented": implemented, "status": "pending", **saved.get(code, {})}
        for code, title, implemented in STEPS
    ]


def _ensure_run(
    db: Session, organization_id: uuid.UUID, year: int, month: int, user_id: uuid.UUID | None
) -> MonthCloseRun:
    run = get_run(db, organization_id, year, month, lock=True)
    if run is None:
        run = MonthCloseRun(organization_id=organization_id, year=year, month=month, steps=[], status="draft")
        db.add(run)
        db.flush()
    if run.document_id is None:
        _, end = month_bounds(year, month)
        doc = Document(
            organization_id=organization_id,
            type=DocumentType.other,
            doc_number=f"ÎL-{year}-{month:02d}",
            doc_date=end,
            uploaded_by=user_id,
        )
        db.add(doc)
        db.flush()
        run.document_id = doc.id
    return run


def _set_step(run: MonthCloseRun, step: str, **values) -> None:
    steps = [s for s in (run.steps or []) if s["step"] != step]
    steps.append({"step": step, **values})
    order = [code for code, _, _ in STEPS]
    run.steps = sorted(steps, key=lambda s: order.index(s["step"]))  # listă nouă → SQLAlchemy vede schimbarea
    # repartizarea pe granturi e opțională: nu toate organizațiile au cheltuieli comune
    implemented = [code for code, _, ok in STEPS if ok and code not in OPTIONAL_STEPS]
    statuses = {s["step"]: s.get("status") for s in run.steps}
    run.status = "done" if all(statuses.get(code) == "done" for code in implemented) else "draft"


def preview_depreciation(db: Session, organization_id: uuid.UUID, year: int, month: int) -> DepreciationPlan:
    run = get_run(db, organization_id, year, month)
    return plan(db, organization_id, year, month, exclude_document=run.document_id if run else None)


def run_depreciation(
    db: Session, organization_id: uuid.UUID, year: int, month: int, user_id: uuid.UUID | None
) -> DepreciationPlan:
    """Execută pasul: înregistrează amortizarea pe documentul închiderii (repetarea înlocuiește calculul)."""
    run = _ensure_run(db, organization_id, year, month, user_id)
    result = plan(db, organization_id, year, month, exclude_document=run.document_id)
    if result.errors:
        raise PostingError("Amortizarea nu se poate calcula: " + "; ".join(result.errors))
    doc = db.get(Document, run.document_id)
    if result.lines:
        post_document(
            db,
            organization_id=organization_id,
            document_id=doc.id,
            lines=[g.line for g in result.lines],
            user_id=user_id,
            rule_refs=sorted({f"{g.rule.id} ({g.rule.source_ref})" for g in result.lines}),
        )
    elif doc.is_posted:
        unpost_document(db, organization_id=organization_id, document_id=doc.id, user_id=user_id)
    run.run_by = user_id
    run.run_at = datetime.now()
    _set_step(run, "depreciation", status="done", entries=len(result.lines), total=str(result.total))
    db.flush()
    return result


def revert_depreciation(
    db: Session, organization_id: uuid.UUID, year: int, month: int, user_id: uuid.UUID | None
) -> None:
    run = get_run(db, organization_id, year, month, lock=True)
    if run is None or not any(s["step"] == "depreciation" and s.get("status") == "done" for s in run.steps or []):
        raise PostingError("Amortizarea lunii nu a fost executată")
    doc = db.get(Document, run.document_id) if run.document_id else None
    if doc is not None and doc.is_posted:
        unpost_document(db, organization_id=organization_id, document_id=doc.id, user_id=user_id)
    _set_step(run, "depreciation", status="reverted", entries=0, total="0")
    db.flush()


# ───────────── ceilalți pași: fiecare pas care înregistrează are documentul lui ─────────────

STEP_DOCUMENT_SUFFIX = {"special_purpose_income": "VEN", "payroll": "SAL", "grant_allocation": "REP"}


def _step(run: MonthCloseRun | None, step: str) -> dict:
    return next((s for s in (run.steps or []) if s["step"] == step), {}) if run else {}


def _step_document(db: Session, run: MonthCloseRun, step: str, user_id: uuid.UUID | None) -> Document:
    saved = _step(run, step).get("document_id")
    if saved:
        return db.get(Document, uuid.UUID(saved))
    _, end = month_bounds(run.year, run.month)
    doc = Document(
        organization_id=run.organization_id,
        type=DocumentType.other,
        doc_number=f"ÎL-{run.year}-{run.month:02d}-{STEP_DOCUMENT_SUFFIX[step]}",
        doc_date=end,
        uploaded_by=user_id,
    )
    db.add(doc)
    db.flush()
    return doc


def _payroll(db: Session, organization_id: uuid.UUID, year: int, month: int) -> tuple[StepResult, object]:
    """Calculul salariului ca rezultat de pas: un rând pe contract, cu brutul și reținerile."""
    plan = payroll_calc.plan(db, organization_id, year, month)
    result = StepResult(errors=list(plan.errors), lines=list(plan.lines))
    for c in plan.calcs:
        grants = ", ".join(f"{p.grant.code} {p.share}%" for p in c.parts) or "fără finanțare"
        result.rows.append(
            StepRow(
                label=f"{c.person.full_name} — {c.income_code} ({c.contract.number or c.contract.type.value})",
                amount=c.gross,
                debit_account=None,
                credit_account="531",
                note=f"CNAS {c.cnas}, CNAM {c.cnam}, impozit {c.income_tax}, net {c.net}; {grants}",
            )
        )
    return result, plan


def preview_step(
    db: Session, organization_id: uuid.UUID, year: int, month: int, step: str, params: dict | None = None
) -> StepResult:
    if step == "grant_allocation":
        run = get_run(db, organization_id, year, month)
        saved = _step(run, step)
        doc_id = uuid.UUID(saved["document_id"]) if saved.get("document_id") else None
        return grant_allocation.plan(db, organization_id, year, month, params or saved.get("params"), doc_id)[0]
    if step == "payroll":
        return _payroll(db, organization_id, year, month)[0]
    if step == "checks":
        run = get_run(db, organization_id, year, month)
        own = {run.document_id} if run and run.document_id else set()
        own |= {uuid.UUID(s["document_id"]) for s in (run.steps or []) if s.get("document_id")} if run else set()
        return checks(db, organization_id, year, month, own)
    if step == "special_purpose_income":
        saved = _step(get_run(db, organization_id, year, month), step).get("document_id")
        return income_plan(db, organization_id, year, month, uuid.UUID(saved) if saved else None)
    raise PostingError("Pasul nu este încă implementat")


def run_step(
    db: Session,
    organization_id: uuid.UUID,
    year: int,
    month: int,
    step: str,
    user_id: uuid.UUID | None,
    params: dict | None = None,
) -> StepResult:
    run = _ensure_run(db, organization_id, year, month, user_id)
    payroll_plan = allocations = None
    if step == "grant_allocation":
        saved = _step(run, step)
        params = params or saved.get("params")
        doc_id = uuid.UUID(saved["document_id"]) if saved.get("document_id") else None
        result, allocations = grant_allocation.plan(db, organization_id, year, month, params, doc_id)
    elif step == "payroll":
        result, payroll_plan = _payroll(db, organization_id, year, month)
    else:
        result = preview_step(db, organization_id, year, month, step)
    values: dict = {"status": "done", "entries": len(result.lines), "total": str(result.total)}
    if step == "grant_allocation":
        values["params"] = params
    if step == "checks":
        # verificările nu înregistrează; cu probleme pasul rămâne „de corectat”
        values = {"status": "error" if result.errors else "done", "entries": 0, "total": "0", "issues": result.errors}
    else:
        if result.errors:
            raise PostingError("Pasul nu se poate executa: " + "; ".join(result.errors))
        doc = _step_document(db, run, step, user_id)
        values["document_id"] = str(doc.id)
        if result.lines:
            post_document(
                db, organization_id=organization_id, document_id=doc.id, lines=[g.line for g in result.lines], user_id=user_id,
                rule_refs=sorted({f"{g.rule.id} ({g.rule.source_ref})" for g in result.lines}),
            )  # fmt: skip
        elif doc.is_posted:
            unpost_document(db, organization_id=organization_id, document_id=doc.id, user_id=user_id)
        if payroll_plan is not None:
            store_entries(db, organization_id, payroll_plan, user_id)
        if allocations is not None:
            grant_allocation.store(db, doc.id, allocations)
    run.run_by = user_id
    run.run_at = datetime.now()
    _set_step(run, step, **values)
    db.flush()
    return result


def revert_step(
    db: Session, organization_id: uuid.UUID, year: int, month: int, step: str, user_id: uuid.UUID | None
) -> None:
    run = get_run(db, organization_id, year, month, lock=True)
    saved = _step(run, step)
    if saved.get("status") not in ("done", "error"):
        raise PostingError("Pasul nu a fost executat")
    if step == "payroll":
        clear_entries(db, organization_id, year, month)
    if step == "grant_allocation" and saved.get("document_id"):
        grant_allocation.clear(db, uuid.UUID(saved["document_id"]))
    if saved.get("document_id"):
        doc = db.get(Document, uuid.UUID(saved["document_id"]))
        if doc.is_posted:
            unpost_document(db, organization_id=organization_id, document_id=doc.id, user_id=user_id)
    _set_step(
        run,
        step,
        **{
            **{k: v for k, v in saved.items() if k != "step"},
            "status": "reverted",
            "entries": 0,
            "total": "0",
            "issues": [],
        },
    )
    db.flush()
