"""Granturile și liniile de buget: creare și modificare (ToR F6.1).

O linie de buget folosită deja în înregistrări sau în rânduri de facturi nu se
șterge (istoricul rămâne legat de ea); i se poate schimba denumirea sau suma.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.documents.models import InvoiceLine
from app.grants.models import BudgetLine, BudgetVersion, CostItem, Grant
from app.posting.models import EntryLine

router = APIRouter(prefix="/organizations/{organization_id}", tags=["granturi"])

FUNDING_TYPES = ("grant", "donație", "cotizații", "economic", "percentage_designation", "unrestricted")


class GrantIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1)
    funding_type: str = Field(default="grant", description="sursa de finanțare: " + " / ".join(FUNDING_TYPES))
    designation_year: int | None = None
    currency: str = Field(default="MDL", min_length=3, max_length=3)
    total_amount: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    account_id: uuid.UUID | None = None
    start_date: date
    end_date: date
    is_closed: bool = False

    @model_validator(mode="after")
    def dates(self) -> "GrantIn":
        # funding_type decide formulele (716 / 717 / 718), deci se acceptă doar valorile cunoscute
        if self.funding_type not in FUNDING_TYPES:
            raise ValueError(f"Sursa de finanțare trebuie să fie una din: {', '.join(FUNDING_TYPES)}")
        if self.end_date < self.start_date:
            raise ValueError("Data de sfârșit este înaintea celei de început")
        return self


class GrantDetail(BaseModel):
    """Grantul așa cum e în bază (poate veni și din import, cu alte surse de finanțare)."""

    id: uuid.UUID
    code: str
    title: str
    funding_type: str | None
    designation_year: int | None
    currency: str
    total_amount: Decimal
    account_id: uuid.UUID | None
    start_date: date
    end_date: date
    is_closed: bool | None

    model_config = {"from_attributes": True}


class BudgetLineIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1)
    planned_amount: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    unit: str | None = None
    quantity: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    unit_cost: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    donor_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    cofinancing_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    cost_item_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def cofinancing(self) -> "BudgetLineIn":
        # verificarea din docs/02 §9a: cofinanțarea pe linie ≤ totalul liniei
        if self.cofinancing_amount is not None and self.cofinancing_amount > self.planned_amount:
            raise ValueError("Cofinanțarea depășește totalul liniei")
        return self


class BudgetLineDetail(BaseModel):
    id: uuid.UUID
    grant_id: uuid.UUID
    code: str
    name: str
    planned_amount: Decimal
    unit: str | None
    quantity: Decimal | None
    unit_cost: Decimal | None
    donor_amount: Decimal | None
    cofinancing_amount: Decimal | None
    cost_item_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    budget_version_id: uuid.UUID | None = None
    in_use: bool = False

    model_config = {"from_attributes": True}


def _grant(db: Session, ctx: OrgContext, grant_id: uuid.UUID, lock: bool = False) -> Grant:
    query = select(Grant).where(Grant.id == grant_id, Grant.organization_id == ctx.organization_id)
    grant = db.scalar(query.with_for_update() if lock else query)
    if grant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grantul nu a fost găsit")
    return grant


def _line(db: Session, ctx: OrgContext, line_id: uuid.UUID) -> BudgetLine:
    line = db.scalar(
        select(BudgetLine)
        .join(Grant, Grant.id == BudgetLine.grant_id)
        .where(BudgetLine.id == line_id, Grant.organization_id == ctx.organization_id)
        .with_for_update(of=BudgetLine)
    )
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linia de buget nu a fost găsită")
    return line


def _check_refs(db: Session, ctx: OrgContext, *, account_id=None, cost_item_id=None) -> None:
    if (
        account_id
        and db.scalar(
            select(Account.id).where(Account.id == account_id, Account.organization_id == ctx.organization_id)
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul nu aparține organizației")
    if (
        cost_item_id
        and db.scalar(
            select(CostItem.id).where(CostItem.id == cost_item_id, CostItem.organization_id == ctx.organization_id)
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Articolul de cheltuieli nu aparține organizației")


def current_version_id(db: Session, grant_id: uuid.UUID) -> uuid.UUID | None:
    """Versiunea în vigoare a bugetului (None = grantul nu are încă versiuni, liniile sunt „libere”)."""
    return db.scalar(
        select(BudgetVersion.id).where(BudgetVersion.grant_id == grant_id, BudgetVersion.is_current.is_(True))
    )


def _only_current(line: BudgetLine, db: Session) -> None:
    if line.budget_version_id != current_version_id(db, line.grant_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Linia aparține unei versiuni vechi a bugetului; creați o versiune nouă"
        )


def _in_use(db: Session, line_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(select(exists().where(EntryLine.budget_line_id == line_id)))
        or db.scalar(select(exists().where(InvoiceLine.budget_line_id == line_id)))
    )


def _unique_code(db: Session, ctx: OrgContext, code: str, except_id: uuid.UUID | None = None) -> None:
    query = select(Grant.id).where(Grant.organization_id == ctx.organization_id, Grant.code == code)
    if except_id:
        query = query.where(Grant.id != except_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Există deja un grant cu codul {code}")


@router.get("/grants/{grant_id}", response_model=GrantDetail)
def get_grant(grant_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Grant:
    return _grant(db, ctx, grant_id)


@router.post("/grants", response_model=GrantDetail, status_code=status.HTTP_201_CREATED)
def create_grant(body: GrantIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Grant:
    ctx.require(POSTING_ROLES)
    _unique_code(db, ctx, body.code)
    _check_refs(db, ctx, account_id=body.account_id)
    grant = Grant(
        organization_id=ctx.organization_id, **body.model_dump(exclude={"currency"}), currency=body.currency.upper()
    )
    db.add(grant)
    db.flush()
    write_audit(
        db, action="create", entity="grants", entity_id=grant.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return grant


@router.put("/grants/{grant_id}", response_model=GrantDetail)
def update_grant(
    grant_id: uuid.UUID, body: GrantIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> Grant:
    ctx.require(POSTING_ROLES)
    grant = _grant(db, ctx, grant_id, lock=True)
    _unique_code(db, ctx, body.code, except_id=grant.id)
    _check_refs(db, ctx, account_id=body.account_id)
    old = GrantDetail.model_validate(grant).model_dump(mode="json", exclude={"id"})
    for key, value in body.model_dump().items():
        setattr(grant, key, value.upper() if key == "currency" else value)
    db.flush()
    write_audit(
        db, action="update", entity="grants", entity_id=grant.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values=old, new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return grant


@router.get("/grants/{grant_id}/budget-lines", response_model=list[BudgetLineDetail])
def list_budget_lines(
    grant_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[BudgetLineDetail]:
    """Liniile versiunii cerute; fără `version_id` — cele ale versiunii în vigoare."""
    _grant(db, ctx, grant_id)
    version = version_id or current_version_id(db, grant_id)
    lines = db.scalars(
        select(BudgetLine)
        .where(BudgetLine.grant_id == grant_id, BudgetLine.budget_version_id.is_not_distinct_from(version))
        .order_by(BudgetLine.code)
    ).all()
    used = set(
        db.scalars(select(EntryLine.budget_line_id).where(EntryLine.budget_line_id.in_([ln.id for ln in lines])))
    )
    used |= set(
        db.scalars(select(InvoiceLine.budget_line_id).where(InvoiceLine.budget_line_id.in_([ln.id for ln in lines])))
    )
    return [BudgetLineDetail.model_validate(ln).model_copy(update={"in_use": ln.id in used}) for ln in lines]


@router.post("/grants/{grant_id}/budget-lines", response_model=BudgetLineDetail, status_code=status.HTTP_201_CREATED)
def create_budget_line(
    grant_id: uuid.UUID, body: BudgetLineIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> BudgetLine:
    ctx.require(POSTING_ROLES)
    _grant(db, ctx, grant_id, lock=True)
    _check_refs(db, ctx, cost_item_id=body.cost_item_id)
    if (
        body.parent_id
        and db.scalar(select(BudgetLine.id).where(BudgetLine.id == body.parent_id, BudgetLine.grant_id == grant_id))
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia-părinte nu aparține grantului")
    version = current_version_id(db, grant_id)
    if db.scalar(
        select(BudgetLine.id).where(
            BudgetLine.grant_id == grant_id,
            BudgetLine.code == body.code,
            BudgetLine.budget_version_id.is_not_distinct_from(version),
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Linia {body.code} există deja în acest grant")
    line = BudgetLine(grant_id=grant_id, budget_version_id=version, **body.model_dump())
    db.add(line)
    db.flush()
    write_audit(
        db, action="create", entity="budget_lines", entity_id=line.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return line


@router.put("/budget-lines/{line_id}", response_model=BudgetLineDetail)
def update_budget_line(
    line_id: uuid.UUID, body: BudgetLineIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> BudgetLineDetail:
    ctx.require(POSTING_ROLES)
    line = _line(db, ctx, line_id)
    _only_current(line, db)
    _check_refs(db, ctx, cost_item_id=body.cost_item_id)
    if body.parent_id == line.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia nu poate fi propriul părinte")
    if db.scalar(
        select(BudgetLine.id).where(
            BudgetLine.grant_id == line.grant_id,
            BudgetLine.code == body.code,
            BudgetLine.id != line.id,
            BudgetLine.budget_version_id.is_not_distinct_from(line.budget_version_id),
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Linia {body.code} există deja în acest grant")
    old = BudgetLineDetail.model_validate(line).model_dump(mode="json", exclude={"id", "grant_id", "in_use"})
    for key, value in body.model_dump().items():
        setattr(line, key, value)
    db.flush()
    write_audit(
        db, action="update", entity="budget_lines", entity_id=line.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values=old, new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return BudgetLineDetail.model_validate(line).model_copy(update={"in_use": _in_use(db, line.id)})


@router.delete("/budget-lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget_line(
    line_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> None:
    ctx.require(POSTING_ROLES)
    line = _line(db, ctx, line_id)
    _only_current(line, db)
    if _in_use(db, line.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Linia e folosită în documente sau înregistrări și nu se poate șterge"
        )
    if db.scalar(select(exists().where(BudgetLine.parent_id == line.id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Linia are sub-linii; ștergeți-le întâi")
    write_audit(
        db, action="delete", entity="budget_lines", entity_id=line.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"code": line.code, "name": line.name, "planned_amount": str(line.planned_amount)},
    )  # fmt: skip
    db.delete(line)
    db.commit()
