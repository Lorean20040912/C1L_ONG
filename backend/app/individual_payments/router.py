"""„Plată către persoană fizică”: listă, creare, modificare, Dt/Kt, înregistrare, anulare (docs/05 §2)."""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants.models import BudgetLine, CostItem, Grant
from app.individual_payments.posting import PAYMENT_KINDS, compute, post, preview
from app.payroll.models import IndividualPayment, Person
from app.posting.engine import PostingError, unpost_document
from app.posting.router import EntryLineOut, PreviewLine, http_error, preview_out

router = APIRouter(prefix="/organizations/{organization_id}/individual-payments", tags=["plăți către persoane fizice"])


class IndividualPaymentIn(BaseModel):
    doc_number: str = Field(min_length=1)
    person_id: uuid.UUID
    payment_kind: str
    accrual_date: date
    payment_date: date | None = None
    gross: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    budget_line_id: uuid.UUID
    cost_item_id: uuid.UUID | None = None
    version: int | None = None


class IndividualPaymentOut(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    person_id: uuid.UUID
    person_name: str
    payment_kind: str
    income_code: str
    accrual_date: date
    payment_date: date | None
    gross: Decimal
    income_tax: Decimal | None
    net: Decimal | None
    tax_rate_id: uuid.UUID | None
    grant_id: uuid.UUID | None
    budget_line_id: uuid.UUID | None
    cost_item_id: uuid.UUID | None
    is_posted: bool | None
    version: int | None


class PaymentKindOut(BaseModel):
    kind: str
    income_code: str
    rate_code: str
    title: str


def _out(doc: Document, p: IndividualPayment, person: Person) -> IndividualPaymentOut:
    return IndividualPaymentOut(
        document_id=doc.id,
        doc_number=doc.doc_number,
        person_name=person.full_name,
        is_posted=doc.is_posted,
        version=doc.version,
        **{
            k: getattr(p, k)
            for k in (
                "person_id", "payment_kind", "income_code", "accrual_date", "payment_date", "gross", "income_tax",
                "net", "tax_rate_id", "grant_id", "budget_line_id", "cost_item_id",
            )
        },
    )  # fmt: skip


def _get(db: Session, ctx: OrgContext, document_id: uuid.UUID, lock: bool = False):
    query = (
        select(Document, IndividualPayment, Person)
        .join(IndividualPayment, IndividualPayment.document_id == Document.id)
        .join(Person, Person.id == IndividualPayment.person_id)
        .where(Document.id == document_id, Document.organization_id == ctx.organization_id)
    )
    row = db.execute(query.with_for_update(of=Document) if lock else query).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plata nu a fost găsită")
    return row


def _apply(db: Session, ctx: OrgContext, doc: Document, p: IndividualPayment, body: IndividualPaymentIn) -> Person:
    org = ctx.organization_id
    person = db.scalar(select(Person).where(Person.id == body.person_id, Person.organization_id == org))
    if person is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Persoana nu aparține organizației")
    if body.payment_kind not in PAYMENT_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tip de plată necunoscut")
    grant_id = db.scalar(
        select(Grant.id)
        .join(BudgetLine, BudgetLine.grant_id == Grant.id)
        .where(BudgetLine.id == body.budget_line_id, Grant.organization_id == org)
    )
    if grant_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linia de buget nu aparține organizației")
    if body.cost_item_id and db.scalar(
        select(CostItem.id).where(CostItem.id == body.cost_item_id, CostItem.organization_id == org)
    ) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Articolul de cheltuieli nu aparține organizației")
    doc.doc_number = body.doc_number
    doc.doc_date = body.accrual_date
    doc.total_amount = body.gross
    doc.currency = "MDL"
    p.person_id = person.id
    p.payment_kind = body.payment_kind
    p.accrual_date = body.accrual_date
    p.payment_date = body.payment_date
    p.gross = body.gross
    p.budget_line_id = body.budget_line_id
    p.grant_id = grant_id
    p.cost_item_id = body.cost_item_id
    try:
        compute(db, p)
    except PostingError as exc:
        raise http_error(exc) from None
    return person


@router.get("/kinds", response_model=list[PaymentKindOut])
def kinds(ctx: OrgContext = Depends(get_org_context)) -> list[PaymentKindOut]:
    return [
        PaymentKindOut(kind=k, income_code=code, rate_code=rate, title=title)
        for k, (code, rate, title) in PAYMENT_KINDS.items()
    ]


@router.get("", response_model=list[IndividualPaymentOut])
def list_payments(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Document, IndividualPayment, Person)
        .join(IndividualPayment, IndividualPayment.document_id == Document.id)
        .join(Person, Person.id == IndividualPayment.person_id)
        .where(Document.organization_id == ctx.organization_id)
        .order_by(Document.doc_date.desc(), Document.doc_number.desc())
        .limit(500)
    ).all()
    return [_out(*r) for r in rows]


@router.post("", response_model=IndividualPaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(body: IndividualPaymentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = Document(organization_id=ctx.organization_id, type=DocumentType.individual_payment, uploaded_by=ctx.user.id)
    p = IndividualPayment()
    person = _apply(db, ctx, doc, p, body)
    db.add(doc)
    db.flush()
    p.document_id = doc.id
    db.add(p)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="documents",
        entity_id=doc.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"kind": p.payment_kind, "gross": str(p.gross), "income_tax": str(p.income_tax)},
    )
    db.commit()
    return _out(doc, p, person)


@router.get("/{document_id}", response_model=IndividualPaymentOut)
def get_payment(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return _out(*_get(db, ctx, document_id))


@router.put("/{document_id}", response_model=IndividualPaymentOut)
def update_payment(
    document_id: uuid.UUID,
    body: IndividualPaymentIn,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    ctx.require(POSTING_ROLES)
    doc, p, _ = _get(db, ctx, document_id, lock=True)
    if body.version is not None and body.version != doc.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Plata a fost modificată între timp; redeschideți-o")
    if doc.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Plata este înregistrată; anulați înregistrarea ca s-o modificați")
    person = _apply(db, ctx, doc, p, body)
    doc.version = (doc.version or 1) + 1
    db.flush()
    write_audit(
        db,
        action="update",
        entity="documents",
        entity_id=doc.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"kind": p.payment_kind, "gross": str(p.gross)},
    )
    db.commit()
    return _out(doc, p, person)


@router.post("/{document_id}/preview", response_model=list[PreviewLine])
def preview_route(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    _get(db, ctx, document_id)
    try:
        result = preview_out(db, preview(db, ctx.organization_id, document_id))
    except PostingError as exc:
        raise http_error(exc) from None
    finally:
        db.rollback()  # previzualizarea nu salvează cota recalculată
    return result


@router.post("/{document_id}/post", response_model=list[EntryLineOut])
def post_route(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        created = post(db, ctx.organization_id, document_id, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return created


@router.post("/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost_route(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        unpost_document(db, organization_id=ctx.organization_id, document_id=document_id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
