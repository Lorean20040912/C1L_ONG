"""Verificarea contabilității: controale de coerență pe perioadă, cu trimitere la documente și conturi."""

import calendar
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import AccountKind, DocumentStatus, DocumentType
from app.documents.models import Document
from app.posting.models import AccountTurnover, EntryLine

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["rapoarte"])
MAX_ITEMS = 100
# documente care prin natura lor nu se înregistrează singure
NOT_POSTED_BY_DESIGN = (DocumentType.bank_statement, DocumentType.contract, DocumentType.other)


class CheckItem(BaseModel):
    message: str
    document_id: uuid.UUID | None = None
    doc_type: str | None = None
    doc_number: str | None = None
    account_id: uuid.UUID | None = None
    amount: Decimal | None = None


class Check(BaseModel):
    code: str
    title: str
    severity: str  # ok | warning | error
    count: int
    items: list[CheckItem]


class AccountingCheck(BaseModel):
    date_from: date
    date_to: date
    ok: bool
    checks: list[Check]


def _check(code: str, title: str, severity: str, items: list[CheckItem]) -> Check:
    return Check(code=code, title=title, severity=severity if items else "ok", count=len(items), items=items[:MAX_ITEMS])


def _doc_item(message: str, doc: Document, amount: Decimal | None = None) -> CheckItem:
    return CheckItem(
        message=message, document_id=doc.id, doc_type=doc.type.value if doc.type else None,
        doc_number=doc.doc_number, amount=amount,
    )  # fmt: skip


def run_checks(db: Session, ctx: OrgContext, date_from: date, date_to: date) -> AccountingCheck:
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")
    org_id = ctx.organization_id
    end = date_to.replace(day=calendar.monthrange(date_to.year, date_to.month)[1])
    end_month = date_to.replace(day=1)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.organization_id == org_id))}
    label = lambda i: f"{accounts[i].code} {accounts[i].name}" if i in accounts else str(i)  # noqa: E731

    # 1. balanța: Dt = Kt pe totaluri și totalurile = înregistrările
    items: list[CheckItem] = []
    turnovers = db.execute(
        select(AccountTurnover.account_id, func.sum(AccountTurnover.debit), func.sum(AccountTurnover.credit))
        .where(AccountTurnover.organization_id == org_id, AccountTurnover.period <= end_month)
        .group_by(AccountTurnover.account_id)
    ).all()
    dt_all = sum((t[1] for t in turnovers), Decimal(0))
    kt_all = sum((t[2] for t in turnovers), Decimal(0))
    if dt_all != kt_all:
        items.append(CheckItem(message=f"Rulajele totale nu se echilibrează: Dt {dt_all} ≠ Kt {kt_all}", amount=dt_all - kt_all))
    real: dict[uuid.UUID, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for col, idx in ((EntryLine.debit_account_id, 0), (EntryLine.credit_account_id, 1)):
        for acc_id, total in db.execute(
            select(col, func.sum(EntryLine.amount))
            .where(EntryLine.organization_id == org_id, EntryLine.entry_date <= end)
            .group_by(col)
        ):
            real[acc_id][idx] = total
    kept = {t[0]: [t[1], t[2]] for t in turnovers}
    for acc_id in sorted(set(real) | set(kept), key=lambda i: label(i)):
        have, want = kept.get(acc_id, [Decimal(0), Decimal(0)]), real.get(acc_id, [Decimal(0), Decimal(0)])
        if have != want:
            items.append(
                CheckItem(
                    message=f"Contul {label(acc_id)}: totalurile (Dt {have[0]}, Kt {have[1]}) diferă de înregistrări (Dt {want[0]}, Kt {want[1]})",
                    account_id=acc_id, amount=(have[0] - have[1]) - (want[0] - want[1]),
                )  # fmt: skip
            )
    balance = _check("balance", "Balanța echilibrată și totaluri = înregistrări", "error", items)

    # 2. înregistrări fără corespondență validă
    items = []
    q = (
        select(EntryLine, Document)
        .join(Document, Document.id == EntryLine.document_id)
        .where(EntryLine.organization_id == org_id, EntryLine.entry_date.between(date_from, date_to))
        .order_by(EntryLine.entry_date, EntryLine.id)
    )
    for e, doc in db.execute(q).all():
        if e.debit_account_id == e.credit_account_id:
            items.append(_doc_item(f"{e.entry_date:%d.%m.%Y}: același cont în Dt și Kt ({label(e.debit_account_id)})", doc, e.amount))
        else:
            for side, acc_id in (("Dt", e.debit_account_id), ("Kt", e.credit_account_id)):
                if accounts.get(acc_id) and accounts[acc_id].is_group:
                    items.append(_doc_item(f"{e.entry_date:%d.%m.%Y}: contul grup {label(acc_id)} folosit în {side}", doc, e.amount))
    corr = _check("correspondence", "Înregistrări fără corespondență validă (același cont, cont grup)", "error", items)

    # 3. documente nepostate / incoerente
    items = []
    in_period = Document.doc_date.between(date_from, date_to)
    base = [Document.organization_id == org_id, Document.deletion_mark.is_not(True)]
    for doc in db.scalars(
        select(Document)
        .where(*base, in_period, Document.status == DocumentStatus.validated, Document.is_posted.is_not(True))
        .where(Document.type.not_in(NOT_POSTED_BY_DESIGN))
        .order_by(Document.doc_date, Document.doc_number)
    ):
        items.append(_doc_item(f"Document validat, neînregistrat: {doc.doc_date:%d.%m.%Y}", doc, doc.total_amount))
    has_entries = select(EntryLine.document_id).where(EntryLine.organization_id == org_id)
    for doc in db.scalars(
        select(Document).where(*base, in_period, Document.is_posted.is_(True), Document.id.not_in(has_entries)).order_by(Document.doc_date)
    ):
        items.append(_doc_item("Marcat înregistrat, dar fără înregistrări Dt/Kt", doc, doc.total_amount))
    for doc in db.scalars(
        select(Document).where(
            Document.organization_id == org_id, Document.deletion_mark.is_(True), Document.id.in_(has_entries)
        )
    ):
        items.append(_doc_item("Marcat pentru ștergere, dar are încă înregistrări Dt/Kt", doc, doc.total_amount))
    unposted = _check("unposted", "Documente nepostate sau incoerente", "warning", items)

    # 4. solduri anormale la sfârșitul perioadei
    items = []
    for acc_id, dt, kt in turnovers:
        acc = accounts.get(acc_id)
        if acc is None or acc.is_group:
            continue
        bal = dt - kt
        if acc.account_kind == AccountKind.active and bal < 0:
            items.append(CheckItem(message=f"Cont activ cu sold creditor: {label(acc_id)} ({-bal})", account_id=acc_id, amount=bal))
        elif acc.account_kind == AccountKind.passive and bal > 0:
            items.append(CheckItem(message=f"Cont pasiv cu sold debitor: {label(acc_id)} ({bal})", account_id=acc_id, amount=bal))
    items.sort(key=lambda i: i.message)
    abnormal = _check("abnormal", "Solduri anormale (contul activ în credit / pasiv în debit)", "warning", items)

    checks = [balance, corr, unposted, abnormal]
    return AccountingCheck(date_from=date_from, date_to=date_to, ok=all(c.severity == "ok" for c in checks), checks=checks)


@router.get("/accounting-check", response_model=AccountingCheck)
def accounting_check(
    date_from: date,
    date_to: date,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AccountingCheck:
    """Controale de coerență: balanța, corespondențele, documentele nepostate, soldurile anormale."""
    return run_checks(db, ctx, date_from, date_to)
