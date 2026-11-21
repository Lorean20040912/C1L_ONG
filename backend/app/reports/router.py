"""Balanța de verificare (OSV): sold inițial, rulaje, sold final pe conturi.

Se calculează din `account_turnovers` (rulajele lunare), nu din sute de mii de
înregistrări (docs/12 §3.1); perioada se dă în luni.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.posting.models import AccountTurnover

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["rapoarte"])


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    opening_debit: Decimal
    opening_credit: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class TrialBalance(BaseModel):
    date_from: date
    date_to: date
    rows: list[TrialBalanceRow]
    totals: dict[str, Decimal]


def _split(balance: Decimal) -> tuple[Decimal, Decimal]:
    return (balance, Decimal(0)) if balance >= 0 else (Decimal(0), -balance)


@router.get("/trial-balance", response_model=TrialBalance)
def trial_balance(
    date_from: date,
    date_to: date,
    grant_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> TrialBalance:
    start, end = date_from.replace(day=1), date_to.replace(day=1)
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")
    before = AccountTurnover.period < start
    inside = AccountTurnover.period.between(start, end)
    query = (
        select(
            Account.id,
            Account.code,
            Account.name,
            func.sum(case((before, AccountTurnover.debit - AccountTurnover.credit), else_=0)),
            func.sum(case((inside, AccountTurnover.debit), else_=0)),
            func.sum(case((inside, AccountTurnover.credit), else_=0)),
        )
        .join(AccountTurnover, AccountTurnover.account_id == Account.id)
        .where(Account.organization_id == ctx.organization_id, AccountTurnover.period <= end)
        .group_by(Account.id)
        .order_by(Account.code)
    )
    if grant_id is not None:
        query = query.where(AccountTurnover.grant_id == grant_id)
    rows, totals = (
        [],
        dict.fromkeys(
            ["opening_debit", "opening_credit", "turnover_debit", "turnover_credit", "closing_debit", "closing_credit"],
            Decimal(0),
        ),
    )
    for account_id, code, name, opening, dt, kt in db.execute(query).all():
        od, oc = _split(opening)
        cd, cc = _split(opening + dt - kt)
        if not any((od, oc, dt, kt, cd, cc)):
            continue
        row = TrialBalanceRow(
            account_id=account_id, code=code, name=name, opening_debit=od, opening_credit=oc,
            turnover_debit=dt, turnover_credit=kt, closing_debit=cd, closing_credit=cc,
        )  # fmt: skip
        rows.append(row)
        for key in totals:
            totals[key] += getattr(row, key)
    return TrialBalance(date_from=start, date_to=end, rows=rows, totals=totals)
