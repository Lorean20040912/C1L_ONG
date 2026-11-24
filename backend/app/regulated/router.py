"""API-ul rapoartelor reglementate (ONG17, 5-CON) și al calendarului raportărilor."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.regulated import export, rsf2
from app.regulated.errors import ReportError, ReportFrozen
from app.regulated.models import ReportForm, ReportingCalendar, ReportStatus, TaxReport
from app.regulated.service import (
    STATUS_LABELS,
    calculate_sources,
    calendar_status,
    cell_sources,
    compute,
    generate,
    set_overrides,
    set_status,
    source_value,
    sync_calendar,
)
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["rapoarte reglementate"])


def _http(exc: ReportError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, ReportFrozen) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(code, str(exc))


class FormOut(BaseModel):
    id: uuid.UUID
    code: str
    authority: str
    periodicity: str
    version: str
    valid_from: date
    valid_to: date | None
    title: str | None
    supported: bool


class ReportRow(BaseModel):
    code: str
    label: str
    indent: int
    informative: bool
    unit: str | None
    has_formula: bool
    calculated: Decimal
    value: Decimal
    overridden: bool


class ReportOut(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    form_version: str
    unit: str
    period_from: date
    period_to: date
    status: ReportStatus
    submitted_at: datetime | None
    generated_at: str | None
    header: dict
    rows: list[ReportRow]
    checks: list[dict]
    annex_1d: list[dict]
    xml_export: bool


class ReportListItem(BaseModel):
    id: uuid.UUID
    code: str
    period_from: date
    period_to: date
    status: ReportStatus
    submitted_at: datetime | None


class GenerateIn(BaseModel):
    code: str
    period_from: date


class OverridesIn(BaseModel):
    cells: dict[str, str | None]


class StatusIn(BaseModel):
    status: ReportStatus


class CellDrilldown(BaseModel):
    code: str
    label: str
    value: Decimal
    overridden: bool
    sources: list[dict]
    items: list[dict]
    changed_since_report: bool


class CalendarItem(BaseModel):
    id: uuid.UUID
    code: str
    title: str | None
    period_from: date
    period_to: date
    due_date: date
    status: str
    status_label: str
    days_left: int
    tax_report_id: uuid.UUID | None
    supported: bool


def _report(db: Session, ctx: OrgContext, report_id: uuid.UUID, lock: bool = False) -> TaxReport:
    query = select(TaxReport).where(TaxReport.id == report_id, TaxReport.organization_id == ctx.organization_id)
    report = db.scalar(query.with_for_update() if lock else query)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Raportul nu a fost găsit")
    return report


def report_out(db: Session, report: TaxReport) -> ReportOut:
    try:
        return _report_out(db, report)
    except ReportError as exc:  # formulă greșită într-o versiune a formularului
        raise _http(exc) from None


def _report_out(db: Session, report: TaxReport) -> ReportOut:
    form = db.get(ReportForm, report.form_id)
    data = report.data or {}
    values = {k: Decimal(v) for k, v in data.get("values", {}).items()}
    sources = {k: Decimal(v) for k, v in data.get("sources", {}).items()}
    calculated = compute(form.structure, sources, {}, has_activity=data.get("has_activity", True)).values
    overrides = report.manual_overrides or {}
    rows = [
        ReportRow(
            code=r["code"], label=r["label"], indent=r.get("indent", 0), informative=bool(r.get("informative")),
            unit=r.get("unit"), has_formula=bool(r.get("formula")), calculated=calculated.get(r["code"], Decimal(0)),
            value=values.get(r["code"], Decimal(0)), overridden=r["code"] in overrides,
        )  # fmt: skip
        for r in form.structure.get("rows", [])
    ]
    return ReportOut(
        id=report.id, code=form.code, title=form.structure.get("title", form.code), form_version=form.version,
        unit=form.structure.get("unit", "lei"), period_from=report.period_from, period_to=report.period_to,
        status=report.status or ReportStatus.draft, submitted_at=report.submitted_at,
        generated_at=data.get("generated_at"), header=data.get("header", {}), rows=rows,
        checks=data.get("checks", []), annex_1d=data.get("annex_1d", []), xml_export=export.has_xml(form.code),
    )  # fmt: skip


@router.get("/forms", response_model=list[FormOut])
def list_forms(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[FormOut]:
    return [
        FormOut(
            id=f.id, code=f.code, authority=f.authority, periodicity=f.periodicity, version=f.version,
            valid_from=f.valid_from, valid_to=f.valid_to, title=f.structure.get("title"),
            supported=bool(f.structure.get("rows")),
        )  # fmt: skip
        for f in db.scalars(select(ReportForm).order_by(ReportForm.code, ReportForm.valid_from))
    ]


@router.get("/tax-reports", response_model=list[ReportListItem])
def list_reports(
    code: str | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[ReportListItem]:
    query = (
        select(TaxReport, ReportForm.code)
        .join(ReportForm, ReportForm.id == TaxReport.form_id)
        .where(TaxReport.organization_id == ctx.organization_id)
        .order_by(TaxReport.period_from.desc(), ReportForm.code)
    )
    if code:
        query = query.where(ReportForm.code == code)
    return [
        ReportListItem(id=r.id, code=c, period_from=r.period_from, period_to=r.period_to,
                       status=r.status or ReportStatus.draft, submitted_at=r.submitted_at)  # fmt: skip
        for r, c in db.execute(query).all()
    ]


@router.post("/tax-reports", response_model=ReportOut)
def generate_report(body: GenerateIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> ReportOut:
    """Completează automat raportul pe perioadă (ciorna existentă se recalculează, corecțiile rămân)."""
    ctx.require(POSTING_ROLES)
    org = db.get(Organization, ctx.organization_id)
    try:
        report = generate(db, org, ctx.user, body.code, body.period_from)
    except ReportError as exc:
        db.rollback()
        raise _http(exc) from None
    write_audit(
        db, action="generate", entity="tax_reports", entity_id=report.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, new_values={"code": body.code, "period_from": body.period_from.isoformat()},
    )  # fmt: skip
    db.commit()
    return report_out(db, report)


@router.get("/tax-reports/{report_id}", response_model=ReportOut)
def get_report(report_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> ReportOut:
    return report_out(db, _report(db, ctx, report_id))


@router.put("/tax-reports/{report_id}/overrides", response_model=ReportOut)
def update_overrides(
    report_id: uuid.UUID, body: OverridesIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> ReportOut:
    """Corecția manuală a celulelor (valoare goală = revine la valoarea calculată)."""
    ctx.require(POSTING_ROLES)
    report = _report(db, ctx, report_id, lock=True)
    old = dict(report.manual_overrides or {})
    try:
        set_overrides(db, report, body.cells)
    except ReportError as exc:
        db.rollback()
        raise _http(exc) from None
    write_audit(
        db, action="update", entity="tax_reports", entity_id=report.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, old_values={"manual_overrides": old}, new_values={"manual_overrides": report.manual_overrides},
    )  # fmt: skip
    db.commit()
    return report_out(db, report)


@router.post("/tax-reports/{report_id}/status", response_model=ReportOut)
def change_status(
    report_id: uuid.UUID, body: StatusIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> ReportOut:
    """Verificat / depus. Depunerea (contabilul-șef) îngheață raportul și îl leagă de calendar."""
    ctx.require(ADMIN_ROLES if body.status == ReportStatus.submitted else POSTING_ROLES)
    report = _report(db, ctx, report_id, lock=True)
    old = report.status.value if report.status else None
    try:
        set_status(db, report, body.status)
    except ReportError as exc:
        db.rollback()
        raise _http(exc) from None
    write_audit(
        db, action="validate" if body.status == ReportStatus.submitted else "update", entity="tax_reports",
        entity_id=report.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"status": old}, new_values={"status": body.status.value},
    )  # fmt: skip
    db.commit()
    return report_out(db, report)


@router.delete("/tax-reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    report = _report(db, ctx, report_id, lock=True)
    if report.status == ReportStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Raportul depus nu se șterge")
    write_audit(
        db, action="delete", entity="tax_reports", entity_id=report.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, old_values={"period_from": report.period_from.isoformat(), "status": report.status.value},
    )  # fmt: skip
    db.delete(report)
    db.commit()


@router.get("/tax-reports/{report_id}/cells/{code}", response_model=CellDrilldown)
def drilldown(
    report_id: uuid.UUID, code: str, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> CellDrilldown:
    """Descifrarea celulei: înregistrările (și depășirile de buget) din care provine (ToR F6a.6).

    Lista vine din contabilitatea de acum; `changed_since_report` arată dacă sursele
    s-au schimbat de la completarea raportului (ex. raport depus, documente modificate după)."""
    report = _report(db, ctx, report_id)
    form = db.get(ReportForm, report.form_id)
    row = next((r for r in form.structure.get("rows", []) if r["code"] == code), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rândul {code} nu există în formular")
    try:
        names = cell_sources(form.structure, code)
        current = calculate_sources(db, ctx.organization_id, form, report.period_from, report.period_to)
    except ReportError as exc:
        raise _http(exc) from None
    stored = (report.data or {}).get("sources", {})
    sources, items, changed = [], [], False
    for name in names:
        now = current.value(name)
        then = Decimal(stored.get(name, 0))
        changed |= now != then
        sources.append({"source": name, "value": str(source_value(form.structure, {name: now}, name)), "lei": str(now),
                        "reported_lei": str(then)})  # fmt: skip
        items += [{"source": name, **c.as_json()} for c in current.details.get(name, [])]
    value = Decimal((report.data or {}).get("values", {}).get(code, 0))
    return CellDrilldown(
        code=code, label=row["label"], value=value, overridden=code in (report.manual_overrides or {}),
        sources=sources, items=items, changed_since_report=changed,
    )  # fmt: skip


@router.get("/tax-reports/{report_id}/export.xlsx")
def export_xlsx(report_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Response:
    out = report_out(db, _report(db, ctx, report_id))
    org = db.get(Organization, ctx.organization_id)
    content = export.report_xlsx(out, org.name)
    _audit_export(db, ctx, out, "xlsx")
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{export.file_name(out)}.xlsx"'},
    )


@router.get("/tax-reports/{report_id}/export.xml")
def export_xml(report_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Response:
    report = _report(db, ctx, report_id)
    form = db.get(ReportForm, report.form_id)
    if not export.has_xml(form.code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Formularul {form.code} nu are format XML")
    out = report_out(db, report)
    content = export.report_xml(out)
    _audit_export(db, ctx, out, "xml")
    return Response(
        content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{export.file_name(out)}.xml"'},
    )


@router.get("/rsf2/preview")
def preview_rsf2(year: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> dict:
    """Previzualizarea RSF2: rândurile cu valori și sumele de control, înainte de descărcarea XML."""
    if not 2000 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Anul nu este valid")
    org = db.get(Organization, ctx.organization_id)
    return rsf2.preview(rsf2.compute(db, org, year))


@router.get("/rsf2.xml")
def export_rsf2(year: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Response:
    """Situațiile financiare anuale (RSF2), XML în formatul exportului oficial; valorile vin din contabilitate."""
    if not 2000 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Anul nu este valid")
    org = db.get(Organization, ctx.organization_id)
    content = rsf2.build_xml(org, year, rsf2.compute(db, org, year))
    write_audit(
        db, action="export", entity="tax_reports", entity_id=ctx.organization_id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, new_values={"format": "xml", "form": "RSF2", "year": year},
    )  # fmt: skip
    db.commit()
    return Response(
        content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{rsf2.file_name(year)}.xml"'},
    )


def _audit_export(db: Session, ctx: OrgContext, out: ReportOut, fmt: str) -> None:
    write_audit(
        db, action="export", entity="tax_reports", entity_id=out.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, new_values={"format": fmt},
    )  # fmt: skip
    db.commit()


@router.get("/calendar", response_model=list[CalendarItem])
def reporting_calendar(
    on: date | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[CalendarItem]:
    """Calendarul obligațiilor de raportare (ToR F0.1a): termen, statut, raportul depus."""
    today = on or date.today()
    org = db.get(Organization, ctx.organization_id)
    sync_calendar(db, org, today)
    db.commit()
    rows = db.execute(
        select(ReportingCalendar, ReportForm, TaxReport.status)
        .join(ReportForm, ReportForm.id == ReportingCalendar.form_id)
        .outerjoin(TaxReport, TaxReport.id == ReportingCalendar.tax_report_id)
        .where(
            ReportingCalendar.organization_id == ctx.organization_id,
            # termenele vechi rămân vizibile doar cât timp sunt restante
            (ReportingCalendar.due_date >= today - timedelta(days=60)) | ReportingCalendar.tax_report_id.is_(None),
        )
        .order_by(ReportingCalendar.due_date, ReportForm.code)
    ).all()
    items = []
    for row, form, report_status in rows:
        state = calendar_status(row, report_status, today)
        items.append(
            CalendarItem(
                id=row.id, code=form.code, title=form.structure.get("title"), period_from=row.period_from,
                period_to=row.period_to, due_date=row.due_date, status=state, status_label=STATUS_LABELS[state],
                days_left=(row.due_date - today).days,
                tax_report_id=row.tax_report_id if state == "submitted" else None,
                supported=bool(form.structure.get("rows")),
            )  # fmt: skip
        )
    return items
