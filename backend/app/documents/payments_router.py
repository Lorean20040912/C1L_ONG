"""Ordinul de plată: listă, creare, modificare, Dt/Kt (previzualizare), înregistrare, anulare."""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.bank.models import BankAccount
from app.catalogs.models import Counterparty
from app.core.db import get_db
from app.core.enums import DocumentType, PaymentDirection
from app.documents.models import Document, Invoice, PaymentOrder, PaymentOrderLine
from app.documents.posting import post_payment, preview_payment
from app.grants.models import Grant
from app.posting.engine import PostingError, unpost_document
from app.posting.router import EntryLineOut, PreviewLine, http_error, preview_out

router = APIRouter(prefix="/organizations/{organization_id}/payment-orders", tags=["ordine de plată"])


class PaymentLineIn(BaseModel):
    grant_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class PaymentIn(BaseModel):
    direction: PaymentDirection = PaymentDirection.outgoing
    doc_number: str = Field(min_length=1)
    doc_date: date
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    purpose: str | None = Field(default=None, max_length=210)
    bank_account_id: uuid.UUID
    counterparty_id: uuid.UUID | None = None
    invoice_document_id: uuid.UUID | None = Field(default=None, description="factura achitată (id-ul documentului)")
    is_urgent: bool = False
    lines: list[PaymentLineIn] = []
    version: int | None = None


class PaymentOut(BaseModel):
    document_id: uuid.UUID
    direction: PaymentDirection
    doc_number: str | None
    doc_date: date | None
    amount: Decimal | None
    currency: str | None
    exchange_rate: Decimal | None
    purpose: str | None
    bank_account_id: uuid.UUID | None
    counterparty_id: uuid.UUID | None
    beneficiary_name: str | None
    beneficiary_idno: str | None
    invoice_document_id: uuid.UUID | None
    bank_status: str | None
    is_posted: bool | None
    version: int | None
    lines: list[PaymentLineIn]


def _out(db: Session, doc: Document, order: PaymentOrder) -> PaymentOut:
    invoice_doc = (
        db.scalar(select(Invoice.document_id).where(Invoice.id == order.invoice_id)) if order.invoice_id else None
    )
    return PaymentOut(
        document_id=doc.id,
        direction=order.direction,
        doc_number=doc.doc_number,
        doc_date=doc.doc_date,
        amount=doc.total_amount,
        currency=doc.currency,
        exchange_rate=order.exchange_rate,
        purpose=order.purpose,
        bank_account_id=order.bank_account_id,
        counterparty_id=doc.counterparty_id,
        beneficiary_name=order.beneficiary_name,
        beneficiary_idno=order.beneficiary_idno,
        invoice_document_id=invoice_doc,
        bank_status=order.bank_status,
        is_posted=doc.is_posted,
        version=doc.version,
        lines=[PaymentLineIn(grant_id=ln.grant_id, amount=ln.amount) for ln in order.lines],
    )


def _get(db: Session, ctx: OrgContext, document_id: uuid.UUID, lock: bool = False) -> tuple[Document, PaymentOrder]:
    query = (
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == ctx.organization_id)
    )
    row = db.execute(query.with_for_update(of=Document) if lock else query).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ordinul de plată nu a fost găsit")
    return row[0], row[1]


def _apply(db: Session, ctx: OrgContext, doc: Document, order: PaymentOrder, body: PaymentIn) -> None:
    org = ctx.organization_id
    bank = db.get(BankAccount, body.bank_account_id)
    if bank is None or bank.organization_id != org:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul bancar nu aparține organizației")
    currency = (body.currency or bank.currency).upper()
    if currency != bank.currency:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Contul bancar este în {bank.currency}")
    counterparty = None
    if body.counterparty_id:
        counterparty = db.get(Counterparty, body.counterparty_id)
        if counterparty is None or counterparty.organization_id != org:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contrapartida nu aparține organizației")
    invoice = None
    if body.invoice_document_id:
        invoice = db.scalar(
            select(Invoice)
            .join(Document, Document.id == Invoice.document_id)
            .where(Invoice.document_id == body.invoice_document_id, Document.organization_id == org)
        )
        if invoice is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Factura nu aparține organizației")
    grant_ids = {ln.grant_id for ln in body.lines if ln.grant_id}
    if (
        grant_ids
        and set(db.scalars(select(Grant.id).where(Grant.id.in_(grant_ids), Grant.organization_id == org))) != grant_ids
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Grantul nu aparține organizației")

    doc.doc_number = body.doc_number
    doc.doc_date = body.doc_date
    doc.total_amount = body.amount
    doc.currency = currency
    doc.counterparty_id = body.counterparty_id
    order.direction = body.direction
    order.exchange_rate = body.exchange_rate
    order.purpose = body.purpose
    order.bank_account_id = bank.id
    order.invoice_id = invoice.id if invoice else None
    order.is_urgent = body.is_urgent
    # instantaneu: ce s-a trimis la bancă rămâne așa chiar dacă se schimbă contrapartida
    order.beneficiary_name = counterparty.name if counterparty else None
    order.beneficiary_idno = counterparty.idno if counterparty else None
    order.beneficiary_iban = counterparty.iban_enc if counterparty else None
    order.lines = [PaymentOrderLine(grant_id=ln.grant_id, amount=ln.amount) for ln in body.lines]


@router.get("", response_model=list[PaymentOut])
def list_payments(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[PaymentOut]:
    rows = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(Document.organization_id == ctx.organization_id)
        .order_by(Document.doc_date.desc(), Document.doc_number.desc())
        .limit(500)
    ).all()
    return [_out(db, doc, order) for doc, order in rows]


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PaymentOut:
    ctx.require(POSTING_ROLES)
    doc = Document(organization_id=ctx.organization_id, type=DocumentType.payment_order, uploaded_by=ctx.user.id)
    order = PaymentOrder(direction=body.direction)
    _apply(db, ctx, doc, order, body)
    db.add(doc)
    db.flush()
    order.document_id = doc.id
    db.add(order)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="documents",
        entity_id=doc.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()
    return _out(db, doc, order)


@router.get("/{document_id}", response_model=PaymentOut)
def get_payment(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PaymentOut:
    doc, order = _get(db, ctx, document_id)
    return _out(db, doc, order)


@router.put("/{document_id}", response_model=PaymentOut)
def update_payment(
    document_id: uuid.UUID, body: PaymentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PaymentOut:
    ctx.require(POSTING_ROLES)
    doc, order = _get(db, ctx, document_id, lock=True)
    if body.version is not None and body.version != doc.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ordinul a fost modificat între timp de alt utilizator; redeschideți-l"
        )
    if doc.is_posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ordinul este înregistrat; anulați înregistrarea ca să-l modificați"
        )
    _apply(db, ctx, doc, order, body)
    doc.version = (doc.version or 1) + 1
    db.flush()
    write_audit(
        db,
        action="update",
        entity="documents",
        entity_id=doc.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()
    return _out(db, doc, order)


@router.post("/{document_id}/preview", response_model=list[PreviewLine])
def preview(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[PreviewLine]:
    _get(db, ctx, document_id)
    try:
        return preview_out(db, preview_payment(db, ctx.organization_id, document_id))
    except PostingError as exc:
        raise http_error(exc) from None


@router.post("/{document_id}/post", response_model=list[EntryLineOut])
def post(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        created = post_payment(db, ctx.organization_id, document_id, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return created


@router.post("/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        unpost_document(db, organization_id=ctx.organization_id, document_id=document_id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
