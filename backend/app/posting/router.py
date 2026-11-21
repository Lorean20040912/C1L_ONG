import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import DocumentType, SubcontoType, UserRole
from app.posting.engine import (
    AnalyticsInput,
    DocumentNotFound,
    LineInput,
    PostingError,
    post_document,
    unpost_document,
)
from app.catalogs.models import Account
from app.documents.models import Document
from app.posting.models import AccountingPeriod, EntryLine
from app.posting.rules import GeneratedLine, OperationInput, build_lines

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


class OperationIn(BaseModel):
    operation: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    attributes: dict[str, str | int | bool] = {}
    entry_date: date | None = None
    grant_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    currency_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    quantity: Decimal | None = Field(default=None, max_digits=15, decimal_places=3)
    activity_type: str | None = None
    description: str | None = None
    analytics: list[AnalyticsIn] = []


class PostRequest(BaseModel):
    """Fie operațiunile documentului (formulele vin din posting_rules), fie rândurile
    Dt/Kt scrise direct (operațiune contabilă manuală)."""

    document_type: str | None = Field(default=None, description="implicit: tipul documentului")
    operations: list[OperationIn] | None = Field(default=None, min_length=1)
    lines: list[LineIn] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_source(self) -> "PostRequest":
        if (self.operations is None) == (self.lines is None):
            raise ValueError("Se trimit fie operations, fie lines")
        return self


class PreviewRequest(BaseModel):
    document_type: str | None = None
    operations: list[OperationIn] = Field(min_length=1)


class PreviewLine(BaseModel):
    entry_date: date
    debit_account: str
    credit_account: str
    amount: Decimal
    grant_id: uuid.UUID | None
    budget_line_id: uuid.UUID | None
    activity_type: str | None
    rule_id: uuid.UUID
    source_ref: str


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


def http_error(exc: PostingError) -> HTTPException:
    if isinstance(exc, DocumentNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def preview_out(db: Session, generated: list[GeneratedLine]) -> list[PreviewLine]:
    """Rândurile generate, cu codurile conturilor și sursa regulii (pentru ecranul Dt/Kt)."""
    ids = {g.line.debit_account_id for g in generated} | {g.line.credit_account_id for g in generated}
    code = dict(db.execute(select(Account.id, Account.code).where(Account.id.in_(ids))).all())
    return [
        PreviewLine(
            entry_date=g.line.entry_date,
            debit_account=code[g.line.debit_account_id],
            credit_account=code[g.line.credit_account_id],
            amount=g.line.amount,
            grant_id=g.line.grant_id,
            budget_line_id=g.line.budget_line_id,
            activity_type=g.line.activity_type,
            rule_id=g.rule.id,
            source_ref=g.rule.source_ref,
        )
        for g in generated
    ]


# documentele care își generează singure operațiunile au rutele lor (/invoices, /payment-orders)
DEDICATED_ROUTES = {DocumentType.invoice: "invoices", DocumentType.payment_order: "payment-orders"}


def _document(db: Session, ctx: OrgContext, document_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.organization_id == ctx.organization_id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul nu a fost găsit")
    return doc


def _refuse_dedicated(doc: Document, action: str) -> None:
    route = DEDICATED_ROUTES.get(doc.type)
    if route:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Documentul se înregistrează prin /{route}/{doc.id}/{action}")


def _generate(
    db: Session, ctx: OrgContext, doc: Document, document_type: str | None, operations: list[OperationIn]
) -> list[GeneratedLine]:
    doc_type = document_type or (doc.type.value if doc.type else None)
    if doc_type is None:
        raise PostingError("Documentul nu are tip; indicați document_type")
    return build_lines(
        db,
        organization_id=ctx.organization_id,
        document_type=doc_type,
        doc_date=doc.doc_date,
        operations=[
            OperationInput(
                **o.model_dump(exclude={"analytics"}),
                analytics=[AnalyticsInput(**a.model_dump()) for a in o.analytics],
            )
            for o in operations
        ],
    )


@router.post("/documents/{document_id}/preview", response_model=list[PreviewLine])
def preview(
    document_id: uuid.UUID,
    body: PreviewRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[PreviewLine]:
    """Rândurile Dt/Kt pe care le-ar genera regulile, fără a înregistra nimic."""
    doc = _document(db, ctx, document_id)
    try:
        generated = _generate(db, ctx, doc, body.document_type, body.operations)
    except PostingError as exc:
        raise http_error(exc) from None
    return preview_out(db, generated)


@router.post("/documents/{document_id}/post", response_model=list[EntryLineOut])
def post(
    document_id: uuid.UUID,
    body: PostRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[EntryLine]:
    """Înregistrează documentul: după regulile din posting_rules (operations) sau manual (lines)."""
    ctx.require(POSTING_ROLES)
    _refuse_dedicated(_document(db, ctx, document_id), "post")
    try:
        rule_refs = None
        if body.operations is not None:
            generated = _generate(db, ctx, _document(db, ctx, document_id), body.document_type, body.operations)
            lines = [g.line for g in generated]
            rule_refs = [f"{g.rule.id} ({g.rule.source_ref})" for g in generated]
        else:
            lines = [
                LineInput(
                    **line.model_dump(exclude={"analytics"}),
                    analytics=[AnalyticsInput(**a.model_dump()) for a in line.analytics],
                )
                for line in body.lines or []
            ]
        created = post_document(
            db,
            organization_id=ctx.organization_id,
            document_id=document_id,
            lines=lines,
            user_id=ctx.user.id,
            rule_refs=rule_refs,
        )
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return created


@router.post("/documents/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    _refuse_dedicated(_document(db, ctx, document_id), "unpost")
    try:
        unpost_document(db, organization_id=ctx.organization_id, document_id=document_id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
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
