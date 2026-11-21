"""Datele de care au nevoie rapoartele: articolele de cheltuieli (rândul 5-CON și
categoria desemnării procentuale), statistica ONG (membri, voluntari) și
antetul organizației (categoria ONG17, CUIIO, CFOJ...)."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.documents.models import InvoiceLine
from app.grants.models import BudgetLine, CostItem
from app.posting.models import EntryLine
from app.regulated.models import OrganizationStats
from app.regulated.service import articles_of, form_for
from app.regulated.sources import DESIGNATION_CATEGORIES
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}", tags=["rapoarte: setări"])

NGO_CATEGORIES = tuple("ABCDEFG")


# ───────────────────────────── articole de cheltuieli ─────────────────────────────


class CostItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    con5_article: str | None = Field(default=None, max_length=3)
    designation_category: str | None = None

    @field_validator("con5_article", "designation_category", mode="before")
    @classmethod
    def blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else (v.strip() if isinstance(v, str) else v)


class CostItemOut(BaseModel):
    id: uuid.UUID
    name: str
    con5_article: str | None
    designation_category: str | None

    model_config = {"from_attributes": True}


class Con5Article(BaseModel):
    code: str
    label: str


def _con5_articles(db: Session) -> dict[str, str]:
    form = form_for(db, "5-CON", date.today())
    allowed = articles_of(form.structure)
    return {r["code"]: r["label"] for r in form.structure["rows"] if r["code"] in allowed}


def _validate(db: Session, body: CostItemIn) -> None:
    if body.con5_article is not None:
        body.con5_article = body.con5_article.zfill(3)
        if body.con5_article not in _con5_articles(db):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Rândul {body.con5_article} nu e un articol din 5-CON")
    if body.designation_category is not None and body.designation_category not in DESIGNATION_CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Categoria desemnării: {', '.join(DESIGNATION_CATEGORIES)}"
        )


def _item(db: Session, ctx: OrgContext, item_id: uuid.UUID) -> CostItem:
    item = db.scalar(select(CostItem).where(CostItem.id == item_id, CostItem.organization_id == ctx.organization_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolul de cheltuieli nu a fost găsit")
    return item


@router.get("/con5-articles", response_model=list[Con5Article])
def con5_articles(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[Con5Article]:
    """Rândurile 5-CON la care se poate lega un articol de cheltuieli."""
    return [Con5Article(code=c, label=label) for c, label in _con5_articles(db).items()]


@router.get("/cost-items", response_model=list[CostItemOut])
def list_cost_items(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[CostItem]:
    return list(db.scalars(select(CostItem).where(CostItem.organization_id == ctx.organization_id).order_by(CostItem.name)))


@router.post("/cost-items", response_model=CostItemOut, status_code=status.HTTP_201_CREATED)
def create_cost_item(body: CostItemIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> CostItem:
    ctx.require(POSTING_ROLES)
    _validate(db, body)
    item = CostItem(organization_id=ctx.organization_id, **body.model_dump())
    db.add(item)
    db.flush()
    write_audit(
        db, action="create", entity="cost_items", entity_id=item.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, new_values=body.model_dump(),
    )  # fmt: skip
    db.commit()
    return item


@router.put("/cost-items/{item_id}", response_model=CostItemOut)
def update_cost_item(
    item_id: uuid.UUID, body: CostItemIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> CostItem:
    ctx.require(POSTING_ROLES)
    item = _item(db, ctx, item_id)
    _validate(db, body)
    old = CostItemOut.model_validate(item).model_dump(mode="json", exclude={"id"})
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    write_audit(
        db, action="update", entity="cost_items", entity_id=item.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, old_values=old, new_values=body.model_dump(),
    )  # fmt: skip
    db.commit()
    return item


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_item(item_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    """Articolul folosit (înregistrări, rânduri de facturi, linii de buget) nu se șterge."""
    ctx.require(POSTING_ROLES)
    item = _item(db, ctx, item_id)
    used = db.scalar(
        select(
            exists().where(EntryLine.cost_item_id == item.id, EntryLine.organization_id == ctx.organization_id)
            | exists().where(InvoiceLine.cost_item_id == item.id)
            | exists().where(BudgetLine.cost_item_id == item.id)
        )
    )
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Articolul este folosit în documente sau linii de buget")
    write_audit(
        db, action="delete", entity="cost_items", entity_id=item.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, old_values=CostItemOut.model_validate(item).model_dump(mode="json", exclude={"id"}),
    )  # fmt: skip
    db.delete(item)
    db.commit()


# ───────────────────────────── statistica ONG ─────────────────────────────


class StatsIn(BaseModel):
    period_end: date
    members_count: int | None = Field(default=None, ge=0)
    volunteers_count: int | None = Field(default=None, ge=0)


class StatsOut(StatsIn):
    id: uuid.UUID
    model_config = {"from_attributes": True}


@router.get("/organization-stats", response_model=list[StatsOut])
def list_stats(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[OrganizationStats]:
    return list(
        db.scalars(
            select(OrganizationStats)
            .where(OrganizationStats.organization_id == ctx.organization_id)
            .order_by(OrganizationStats.period_end.desc())
        )
    )


@router.put("/organization-stats", response_model=StatsOut)
def save_stats(body: StatsIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> OrganizationStats:
    """Membri și voluntari la data dată (5-CON rândurile 300, 320); aceeași dată = actualizare."""
    ctx.require(POSTING_ROLES)
    row = db.scalar(
        select(OrganizationStats).where(
            OrganizationStats.organization_id == ctx.organization_id, OrganizationStats.period_end == body.period_end
        )
    )
    action = "update" if row else "create"
    if row is None:
        row = OrganizationStats(organization_id=ctx.organization_id, period_end=body.period_end)
        db.add(row)
    row.members_count, row.volunteers_count = body.members_count, body.volunteers_count
    db.flush()
    write_audit(
        db, action=action, entity="organization_stats", entity_id=row.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return row


@router.delete("/organization-stats/{stats_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stats(stats_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    row = db.scalar(
        select(OrganizationStats).where(
            OrganizationStats.id == stats_id, OrganizationStats.organization_id == ctx.organization_id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Înregistrarea nu a fost găsită")
    write_audit(
        db, action="delete", entity="organization_stats", entity_id=row.id, organization_id=ctx.organization_id,
        user_id=ctx.user.id, old_values={"period_end": row.period_end.isoformat()},
    )  # fmt: skip
    db.delete(row)
    db.commit()


# ───────────────────────────── antetul rapoartelor ─────────────────────────────

PROFILE_FIELDS = ("ngo_category", "cuiio", "cfoj", "cfp", "cuatm", "caem", "sfs_office", "director_name",
                  "chief_accountant_name")  # fmt: skip


class ReportingProfile(BaseModel):
    ngo_category: str | None = None
    cuiio: str | None = Field(default=None, max_length=20)
    cfoj: str | None = Field(default=None, max_length=10)
    cfp: str | None = Field(default=None, max_length=10)
    cuatm: str | None = Field(default=None, max_length=10)
    caem: str | None = Field(default=None, max_length=10)
    sfs_office: str | None = Field(default=None, max_length=200)
    director_name: str | None = Field(default=None, max_length=200)
    chief_accountant_name: str | None = Field(default=None, max_length=200)

    @field_validator("*", mode="before")
    @classmethod
    def blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else (v.strip() if isinstance(v, str) else v)

    @field_validator("ngo_category")
    @classmethod
    def category(cls, v):
        if v is not None and v.upper() not in NGO_CATEGORIES:
            raise ValueError("Categoria ONG17: A–G")
        return v.upper() if v else v


@router.get("/reporting-profile", response_model=ReportingProfile)
def get_profile(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> ReportingProfile:
    org = db.get(Organization, ctx.organization_id)
    return ReportingProfile(**{f: getattr(org, f) for f in PROFILE_FIELDS})


@router.put("/reporting-profile", response_model=ReportingProfile)
def save_profile(body: ReportingProfile, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> ReportingProfile:
    ctx.require(ADMIN_ROLES)
    org = db.get(Organization, ctx.organization_id)
    old = {f: getattr(org, f) for f in PROFILE_FIELDS}
    for f in PROFILE_FIELDS:
        setattr(org, f, getattr(body, f))
    write_audit(
        db, action="update", entity="organizations", entity_id=org.id, organization_id=org.id, user_id=ctx.user.id,
        old_values=old, new_values=body.model_dump(),
    )  # fmt: skip
    db.commit()
    return body
