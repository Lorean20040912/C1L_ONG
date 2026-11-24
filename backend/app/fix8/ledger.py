"""Cartea mare: pe fiecare cont — sold inițial, rulajele lunare, sold final (din `account_turnovers`)."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.posting.models import AccountTurnover
from app.regulated.export import table_xlsx

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["rapoarte"])


class LedgerMonth(BaseModel):
    month: date
    debit: Decimal
    credit: Decimal
    balance: Decimal  # cu semn: pozitiv = debitor


class LedgerAccount(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    opening: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing: Decimal
    months: list[LedgerMonth]


class GeneralLedger(BaseModel):
    date_from: date
    date_to: date
    accounts: list[LedgerAccount]
    total_debit: Decimal
    total_credit: Decimal


def build_ledger(db: Session, ctx: OrgContext, date_from: date, date_to: date, account_id, grant_id) -> GeneralLedger:
    start, end = date_from.replace(day=1), date_to.replace(day=1)
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")
    q = (
        select(Account, AccountTurnover.period, AccountTurnover.debit, AccountTurnover.credit)
        .join(AccountTurnover, AccountTurnover.account_id == Account.id)
        .where(Account.organization_id == ctx.organization_id, AccountTurnover.period <= end)
        .order_by(Account.code, AccountTurnover.period)
    )
    if account_id is not None:
        acc = db.scalar(select(Account).where(Account.id == account_id, Account.organization_id == ctx.organization_id))
        if acc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contul nu a fost găsit")
        q = q.where(or_(Account.code == acc.code, Account.code.startswith(acc.code + ".")))
    if grant_id is not None:
        q = q.where(AccountTurnover.grant_id == grant_id)
    opening: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    months: dict[uuid.UUID, dict[date, list[Decimal]]] = defaultdict(dict)
    accounts: dict[uuid.UUID, Account] = {}
    for acc, period, dt, kt in db.execute(q).all():
        accounts[acc.id] = acc
        if period < start:
            opening[acc.id] += dt - kt
        else:
            m = months[acc.id].setdefault(period, [Decimal(0), Decimal(0)])
            m[0] += dt
            m[1] += kt
    out: list[LedgerAccount] = []
    for acc in sorted(accounts.values(), key=lambda a: a.code):
        balance = opening[acc.id]
        rows = []
        for period in sorted(months[acc.id]):
            dt, kt = months[acc.id][period]
            balance += dt - kt
            rows.append(LedgerMonth(month=period, debit=dt, credit=kt, balance=balance))
        dt_total = sum((r.debit for r in rows), Decimal(0))
        kt_total = sum((r.credit for r in rows), Decimal(0))
        if not (opening[acc.id] or dt_total or kt_total):
            continue
        out.append(
            LedgerAccount(
                account_id=acc.id, code=acc.code, name=acc.name, opening=opening[acc.id], turnover_debit=dt_total,
                turnover_credit=kt_total, closing=balance, months=rows,
            )  # fmt: skip
        )
    return GeneralLedger(
        date_from=start, date_to=end, accounts=out,
        total_debit=sum((a.turnover_debit for a in out), Decimal(0)),
        total_credit=sum((a.turnover_credit for a in out), Decimal(0)),
    )  # fmt: skip


@router.get("/general-ledger", response_model=GeneralLedger)
def general_ledger(
    date_from: date,
    date_to: date,
    account_id: uuid.UUID | None = None,
    grant_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> GeneralLedger:
    """Cartea mare pe luni: un cont (cu subconturile) sau toate conturile cu mișcări."""
    return build_ledger(db, ctx, date_from, date_to, account_id, grant_id)


@router.get("/general-ledger.xlsx")
def general_ledger_xlsx(
    date_from: date,
    date_to: date,
    account_id: uuid.UUID | None = None,
    grant_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Response:
    led = build_ledger(db, ctx, date_from, date_to, account_id, grant_id)
    rows: list[list] = []
    for a in led.accounts:
        rows.append([a.code, a.name, "Sold inițial", None, None, float(a.opening)])
        rows += [["", "", f"{m.month:%m.%Y}", float(m.debit), float(m.credit), float(m.balance)] for m in a.months]
        rows.append(["", "", "Total / sold final", float(a.turnover_debit), float(a.turnover_credit), float(a.closing)])
    rows.append(["", "TOTAL", "", float(led.total_debit), float(led.total_credit), None])
    content = table_xlsx(
        "Cartea mare", f"{led.date_from:%m.%Y} – {led.date_to:%m.%Y} (sold + = debitor, − = creditor)",
        ["Cont", "Denumire", "Perioada", "Rulaj Dt", "Rulaj Kt", "Sold"], rows, [10, 40, 20, 16, 16, 16],
    )  # fmt: skip
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cartea-mare.xlsx"'},
    )
