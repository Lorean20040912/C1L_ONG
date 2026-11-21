import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.bank.models import BankAccount
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import AccountKind
from app.grants.models import BudgetLine, Grant

router = APIRouter(prefix="/organizations/{organization_id}", tags=["cataloage"])


class AccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    account_kind: AccountKind
    is_group: bool | None

    model_config = {"from_attributes": True}


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[Account]:
    """Planul de conturi al organizației curente."""
    return list(
        db.scalars(select(Account).where(Account.organization_id == ctx.organization_id).order_by(Account.code))
    )


# ───────────── contrapartide ─────────────


class CounterpartyIn(BaseModel):
    name: str = Field(min_length=1)
    idno: str | None = Field(default=None, pattern=r"^\d{13}$")
    vat_code: str | None = None
    bank_code: str | None = None
    address: str | None = None


class CounterpartyOut(CounterpartyIn):
    id: uuid.UUID

    model_config = {"from_attributes": True}


@router.get("/counterparties", response_model=list[CounterpartyOut])
def list_counterparties(
    q: str | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[Counterparty]:
    query = select(Counterparty).where(Counterparty.organization_id == ctx.organization_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Counterparty.name.ilike(like), Counterparty.idno.like(like)))
    return list(db.scalars(query.order_by(Counterparty.name).limit(200)))


@router.post("/counterparties", response_model=CounterpartyOut, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    body: CounterpartyIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> Counterparty:
    ctx.require(POSTING_ROLES)
    if body.idno and db.scalar(
        select(Counterparty.id).where(
            Counterparty.organization_id == ctx.organization_id, Counterparty.idno == body.idno
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Contrapartida cu acest IDNO există deja")
    cp = Counterparty(organization_id=ctx.organization_id, **body.model_dump())
    db.add(cp)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="counterparties",
        entity_id=cp.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()
    return cp


# ───────────── granturi și linii de buget (pentru selecție în documente) ─────────────


class BudgetLineOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    planned_amount: Decimal

    model_config = {"from_attributes": True}


class GrantOut(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    funding_type: str | None
    currency: str
    is_closed: bool | None
    budget_lines: list[BudgetLineOut]


@router.get("/grants", response_model=list[GrantOut])
def list_grants(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[GrantOut]:
    grants = db.scalars(select(Grant).where(Grant.organization_id == ctx.organization_id).order_by(Grant.code)).all()
    lines = db.scalars(
        select(BudgetLine).where(BudgetLine.grant_id.in_([g.id for g in grants])).order_by(BudgetLine.code)
    ).all()
    by_grant: dict = {}
    for line in lines:
        by_grant.setdefault(line.grant_id, []).append(BudgetLineOut.model_validate(line))
    return [
        GrantOut(
            id=g.id,
            code=g.code,
            title=g.title,
            funding_type=g.funding_type,
            currency=g.currency,
            is_closed=g.is_closed,
            budget_lines=by_grant.get(g.id, []),
        )
        for g in grants
    ]


# ───────────── conturi bancare ─────────────


class BankAccountIn(BaseModel):
    iban: str = Field(min_length=10, max_length=34)
    bank_name: str | None = None
    bank_code: str | None = None
    currency: str = Field(default="MDL", min_length=3, max_length=3)
    account_id: uuid.UUID
    grant_id: uuid.UUID | None = None


class BankAccountOut(BaseModel):
    id: uuid.UUID
    iban: str
    bank_name: str | None
    currency: str
    account_id: uuid.UUID | None
    grant_id: uuid.UUID | None


def _bank_out(b: BankAccount) -> BankAccountOut:
    return BankAccountOut(
        id=b.id,
        iban=b.iban_enc,
        bank_name=b.bank_name,
        currency=b.currency,
        account_id=b.account_id,
        grant_id=b.grant_id,
    )


@router.get("/bank-accounts", response_model=list[BankAccountOut])
def list_bank_accounts(
    ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[BankAccountOut]:
    rows = db.scalars(
        select(BankAccount).where(BankAccount.organization_id == ctx.organization_id).order_by(BankAccount.currency)
    )
    return [_bank_out(b) for b in rows]


@router.post("/bank-accounts", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    body: BankAccountIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> BankAccountOut:
    ctx.require(ADMIN_ROLES)
    if (
        db.scalar(
            select(Account.id).where(Account.id == body.account_id, Account.organization_id == ctx.organization_id)
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul contabil nu aparține organizației")
    if (
        body.grant_id
        and db.scalar(select(Grant.id).where(Grant.id == body.grant_id, Grant.organization_id == ctx.organization_id))
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Grantul nu aparține organizației")
    bank = BankAccount(
        organization_id=ctx.organization_id,
        iban_enc=body.iban.replace(" ", "").upper(),
        bank_name=body.bank_name,
        bank_code=body.bank_code,
        currency=body.currency.upper(),
        account_id=body.account_id,
        grant_id=body.grant_id,
    )
    db.add(bank)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="bank_accounts",
        entity_id=bank.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()
    return _bank_out(bank)
