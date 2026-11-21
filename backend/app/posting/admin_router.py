"""Setările contabile: politica contabilă pe versiuni, perioadele, conturile noi în plan.

- Politica contabilă nu se rescrie: o schimbare = o versiune nouă cu data de la
  care se aplică (docs/11 §6 p.2; ToR F00.4), aprobată de contabilul-șef.
- Perioada închisă protejează înregistrările; redeschiderea o face doar
  administratorul sau contabilul-șef, cu motiv, și rămâne în audit.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, OrgContext, get_org_context
from app.auth.models import User
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import AccountKind
from app.posting.models import AccountingPeriod, AccountingPolicy

router = APIRouter(prefix="/organizations/{organization_id}", tags=["setări contabile"])

# ───────────── politica contabilă ─────────────


class PolicyIn(BaseModel):
    valid_from: date
    grant_receivable_account_id: uuid.UUID | None = None
    grant_recognition: str = Field(default="on_signing", pattern="^(on_signing|on_receipt)$")
    stock_to_deferred_income: str = Field(default="unused_only", pattern="^(unused_only|all)$")
    fa_valuation_method: str | None = None
    settings: dict = {}

    @field_validator("settings")
    @classmethod
    def _check_settings(cls, value: dict) -> dict:
        age = value.get("max_rate_age_days")
        if age is not None and (isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 60):
            raise ValueError("max_rate_age_days: număr întreg de zile între 0 și 60")
        return value


class PolicyOut(BaseModel):
    id: uuid.UUID
    valid_from: date
    grant_receivable_account_id: uuid.UUID | None
    grant_recognition: str | None
    stock_to_deferred_income: str | None
    fa_valuation_method: str | None
    settings: dict | None
    approved_by: uuid.UUID | None
    approved_by_name: str | None = None


@router.get("/accounting-policies", response_model=list[PolicyOut])
def list_policies(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[PolicyOut]:
    """Versiunile politicii contabile, cea mai nouă prima."""
    rows = db.execute(
        select(AccountingPolicy, User.full_name)
        .outerjoin(User, User.id == AccountingPolicy.approved_by)
        .where(AccountingPolicy.organization_id == ctx.organization_id)
        .order_by(AccountingPolicy.valid_from.desc())
    ).all()
    return [
        PolicyOut(
            id=p.id,
            valid_from=p.valid_from,
            grant_receivable_account_id=p.grant_receivable_account_id,
            grant_recognition=p.grant_recognition,
            stock_to_deferred_income=p.stock_to_deferred_income,
            fa_valuation_method=p.fa_valuation_method,
            settings=p.settings,
            approved_by=p.approved_by,
            approved_by_name=name,
        )
        for p, name in rows
    ]


@router.post("/accounting-policies", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def create_policy(
    body: PolicyIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PolicyOut:
    ctx.require(ADMIN_ROLES)
    if (
        body.grant_receivable_account_id
        and db.scalar(
            select(Account.id).where(
                Account.id == body.grant_receivable_account_id, Account.organization_id == ctx.organization_id
            )
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul nu aparține organizației")
    if db.scalar(
        select(AccountingPolicy.id).where(
            AccountingPolicy.organization_id == ctx.organization_id, AccountingPolicy.valid_from == body.valid_from
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Există deja o versiune a politicii de la această dată")
    policy = AccountingPolicy(organization_id=ctx.organization_id, approved_by=ctx.user.id, **body.model_dump())
    db.add(policy)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="accounting_policies",
        entity_id=policy.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )
    db.commit()
    return PolicyOut(
        **{k: getattr(policy, k) for k in PolicyOut.model_fields if k != "approved_by_name"},
        approved_by_name=ctx.user.full_name,
    )


# ───────────── perioadele ─────────────


class PeriodOut(BaseModel):
    year: int
    month: int
    is_closed: bool
    closed_at: datetime | None
    closed_by_name: str | None


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3)


@router.get("/periods", response_model=list[PeriodOut])
def list_periods(
    year: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[PeriodOut]:
    """Cele 12 luni ale anului; lipsa rândului = lună deschisă."""
    rows = {
        p.month: (p, name)
        for p, name in db.execute(
            select(AccountingPeriod, User.full_name)
            .outerjoin(User, User.id == AccountingPeriod.closed_by)
            .where(AccountingPeriod.organization_id == ctx.organization_id, AccountingPeriod.year == year)
        )
    }
    result = []
    for month in range(1, 13):
        period, name = rows.get(month, (None, None))
        closed = bool(period and period.is_closed)
        result.append(
            PeriodOut(
                year=year,
                month=month,
                is_closed=closed,
                closed_at=period.closed_at if closed else None,
                closed_by_name=name if closed else None,
            )
        )
    return result


@router.post("/periods/{year}/{month}/reopen", response_model=PeriodOut)
def reopen_period(
    year: int, month: int, body: ReopenIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PeriodOut:
    ctx.require(ADMIN_ROLES)
    period = db.scalar(
        select(AccountingPeriod)
        .where(
            AccountingPeriod.organization_id == ctx.organization_id,
            AccountingPeriod.year == year,
            AccountingPeriod.month == month,
        )
        .with_for_update()
    )
    if period is None or not period.is_closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Perioada nu este închisă")
    old = {"closed_by": str(period.closed_by), "closed_at": str(period.closed_at)}
    period.is_closed = False
    period.closed_by = None
    period.closed_at = None
    db.flush()
    write_audit(
        db,
        action="reopen_period",
        entity="accounting_periods",
        entity_id=period.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values=old,
        new_values={"year": year, "month": month, "reason": body.reason},
    )
    db.commit()
    return PeriodOut(year=year, month=month, is_closed=False, closed_at=None, closed_by_name=None)


# ───────────── conturi noi în planul de conturi ─────────────


class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=10, pattern=r"^[0-9][0-9.]*$")
    name: str = Field(min_length=1)
    account_kind: AccountKind
    parent_id: uuid.UUID | None = None
    is_group: bool = False
    is_currency: bool = False


class AccountCreated(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    account_kind: AccountKind
    is_group: bool | None

    model_config = {"from_attributes": True}


@router.post("/accounts", response_model=AccountCreated, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> Account:
    """Un cont sau subcont nou (ex. 213, 217, 234.4) în planul organizației."""
    ctx.require(ADMIN_ROLES)
    if db.scalar(select(Account.id).where(Account.organization_id == ctx.organization_id, Account.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Contul {body.code} există deja")
    if (
        body.parent_id
        and db.scalar(
            select(Account.id).where(Account.id == body.parent_id, Account.organization_id == ctx.organization_id)
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul-părinte nu aparține organizației")
    account = Account(organization_id=ctx.organization_id, **body.model_dump())
    db.add(account)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="accounts",
        entity_id=account.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )
    db.commit()
    return account
