import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import SubcontoType, UserRole
from app.posting.engine import (
    AnalyticsInput,
    DocumentNotFound,
    LineInput,
    PostingError,
    post_document,
    unpost_document,
)
from app.posting.models import AccountingPeriod, EntryLine

router = APIRouter(prefix="/organizations/{organization_id}", tags=["înregistrări"])

PERIOD_CLOSE_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant})


class AnalyticsIn(BaseModel):
    side: str = Field(pattern="^[DK]$")
    subconto_type: SubcontoType
    ref_id: uuid.UUID


class LineIn(BaseModel):
    debit_account_id: uuid.UUID
    credit_account_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    entry_date: date | None = None
    tax_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    currency_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    quantity: Decimal | None = Field(default=None, max_digits=15, decimal_places=3)
    department_id: uuid.UUID | None = None
    grant_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    activity_type: str | None = None
    is_non_statutory: bool = False
    description: str | None = None
    analytics: list[AnalyticsIn] = []


class PostRequest(BaseModel):
    lines: list[LineIn] = Field(min_length=1)


class EntryLineOut(BaseModel):
    id: int
    line_no: int
    entry_date: date
    debit_account_id: uuid.UUID
    credit_account_id: uuid.UUID
    amount: Decimal
    currency: str | None
    currency_amount: Decimal | None
    grant_id: uuid.UUID | None
    budget_line_id: uuid.UUID | None
    description: str | None

    model_config = {"from_attributes": True}


class PeriodOut(BaseModel):
    year: int
    month: int
    is_closed: bool | None

    model_config = {"from_attributes": True}


def _http_error(exc: PostingError) -> HTTPException:
    if isinstance(exc, DocumentNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/documents/{document_id}/post", response_model=list[EntryLineOut])
def post(
    document_id: uuid.UUID,
    body: PostRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[EntryLine]:
    """Înregistrează documentul cu rândurile Dt/Kt date (până la regulile din posting_rules)."""
    ctx.require(POSTING_ROLES)
    lines = [
        LineInput(
            **line.model_dump(exclude={"analytics"}),
            analytics=[AnalyticsInput(**a.model_dump()) for a in line.analytics],
        )
        for line in body.lines
    ]
    try:
        created = post_document(
            db, organization_id=ctx.organization_id, document_id=document_id, lines=lines, user_id=ctx.user.id
        )
    except PostingError as exc:
        db.rollback()
        raise _http_error(exc) from None
    db.commit()
    return created


@router.post("/documents/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    try:
        unpost_document(db, organization_id=ctx.organization_id, document_id=document_id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise _http_error(exc) from None
    db.commit()


@router.get("/documents/{document_id}/entries", response_model=list[EntryLineOut])
def entries(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[EntryLine]:
    """Dt/Kt al documentului."""
    return list(
        db.scalars(
            select(EntryLine)
            .where(EntryLine.organization_id == ctx.organization_id, EntryLine.document_id == document_id)
            .order_by(EntryLine.line_no)
        )
    )


@router.post("/periods/{year}/{month}/close", response_model=PeriodOut)
def close_period(
    year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> AccountingPeriod:
    ctx.require(PERIOD_CLOSE_ROLES)
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Luna trebuie să fie între 1 și 12")
    period = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.organization_id == ctx.organization_id,
            AccountingPeriod.year == year,
            AccountingPeriod.month == month,
        )
    )
    if period is None:
        period = AccountingPeriod(organization_id=ctx.organization_id, year=year, month=month)
        db.add(period)
    period.is_closed = True
    period.closed_by = ctx.user.id
    period.closed_at = datetime.now()
    db.flush()
    write_audit(
        db,
        action="close_period",
        entity="accounting_periods",
        entity_id=period.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"year": year, "month": month},
    )
    db.commit()
    return period
