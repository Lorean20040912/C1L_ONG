"""Factura primită: listă, creare, modificare, Dt/Kt (previzualizare), înregistrare, anulare."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import DocumentType, LineKind
from app.documents.duplicates import duplicate_invoice, duplicate_message
from app.documents.models import Document, Invoice, InvoiceLine
from app.documents.posting import post_invoice, preview_invoice, unpost_invoice
from app.grants.budget import check_amounts, check_document
from app.grants.models import BudgetLine, CostItem, Grant
from app.grants.router import BudgetWarningOut, warnings_out
from app.posting.engine import PostingError
from app.posting.router import EntryLineOut, PreviewLine, http_error, preview_out

router = APIRouter(prefix="/organizations/{organization_id}/invoices", tags=["facturi primite"])


class InvoiceLineIn(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal | None = Field(default=None, max_digits=12, decimal_places=3)
    unit: str | None = None
    unit_price: Decimal | None = Field(default=None, max_digits=15, decimal_places=4)
    vat_rate: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    line_kind: LineKind = LineKind.service
    account_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    put_into_use: bool = True


class InvoiceLineOut(InvoiceLineIn):
    id: uuid.UUID
    fixed_asset_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class InvoiceIn(BaseModel):
    doc_number: str = Field(min_length=1)
    series: str | None = None
    doc_date: date
    counterparty_id: uuid.UUID
    lines: list[InvoiceLineIn] = Field(min_length=1)
    version: int | None = Field(default=None, description="la modificare: versiunea citită (blocare optimistă)")


class InvoiceListItem(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    series: str | None
    doc_date: date | None
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None
    total_amount: Decimal | None
    is_posted: bool | None
    deletion_mark: bool | None


class InvoiceOut(InvoiceListItem):
    version: int | None
    lines: list[InvoiceLineOut]


def _out(db: Session, doc: Document, invoice: Invoice) -> InvoiceOut:
    name = (
        db.scalar(select(Counterparty.name).where(Counterparty.id == doc.counterparty_id))
        if doc.counterparty_id
        else None
    )
    return InvoiceOut(
        document_id=doc.id,
        doc_number=doc.doc_number,
        series=invoice.series,
        doc_date=doc.doc_date,
        counterparty_id=doc.counterparty_id,
        counterparty_name=name,
        total_amount=doc.total_amount,
        is_posted=doc.is_posted,
        deletion_mark=doc.deletion_mark,
        version=doc.version,
        lines=[InvoiceLineOut.model_validate(line) for line in invoice.lines],
    )


def _get(db: Session, ctx: OrgContext, document_id: uuid.UUID, lock: bool = False) -> tuple[Document, Invoice]:
    query = (
        select(Document, Invoice)
        .join(Invoice, Invoice.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == ctx.organization_id)
    )
    row = db.execute(query.with_for_update(of=Document) if lock else query).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura nu a fost găsită")
    return row[0], row[1]


def _owned(db: Session, model, org_id: uuid.UUID, ids: set, label: str) -> None:
    ids = {i for i in ids if i}
    if not ids:
        return
    if model is BudgetLine:
        query = (
            select(BudgetLine.id).join(Grant, Grant.id == BudgetLine.grant_id).where(Grant.organization_id == org_id)
        )
    else:
        query = select(model.id).where(model.organization_id == org_id)
    found = set(db.scalars(query.where(model.id.in_(ids))))
    if found != ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{label} nu aparține organizației")


def _validate(db: Session, ctx: OrgContext, body: InvoiceIn, exclude_id: uuid.UUID | None = None) -> None:
    _owned(db, Counterparty, ctx.organization_id, {body.counterparty_id}, "Furnizorul")
    _owned(db, Account, ctx.organization_id, {ln.account_id for ln in body.lines}, "Contul")
    _owned(db, BudgetLine, ctx.organization_id, {ln.budget_line_id for ln in body.lines}, "Linia de buget")
    _owned(db, CostItem, ctx.organization_id, {ln.cost_item_id for ln in body.lines}, "Articolul de cheltuieli")
    dup = duplicate_invoice(db, organization_id=ctx.organization_id, counterparty_id=body.counterparty_id,
                            doc_number=body.doc_number, doc_date=body.doc_date, series=body.series, exclude_id=exclude_id)  # fmt: skip
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, duplicate_message(db, dup, body.doc_number, body.doc_date))


def _set_lines(invoice: Invoice, body: InvoiceIn) -> None:
    invoice.lines = [InvoiceLine(position=i, **line.model_dump()) for i, line in enumerate(body.lines)]


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[InvoiceListItem]:
    query = (
        select(Document, Invoice.series, Counterparty.name)
        .join(Invoice, Invoice.document_id == Document.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == ctx.organization_id)
    )
    if date_from:
        query = query.where(Document.doc_date >= date_from)
    if date_to:
        query = query.where(Document.doc_date <= date_to)
    rows = db.execute(query.order_by(Document.doc_date.desc(), Document.doc_number.desc()).limit(500)).all()
    return [
        InvoiceListItem(
            document_id=doc.id,
            doc_number=doc.doc_number,
            series=series,
            doc_date=doc.doc_date,
            counterparty_id=doc.counterparty_id,
            counterparty_name=name,
            total_amount=doc.total_amount,
            is_posted=doc.is_posted,
            deletion_mark=doc.deletion_mark,
        )
        for doc, series, name in rows
    ]


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> InvoiceOut:
    ctx.require(POSTING_ROLES)
    _validate(db, ctx, body)
    doc = Document(
        organization_id=ctx.organization_id,
        type=DocumentType.invoice,
        doc_number=body.doc_number,
        doc_date=body.doc_date,
        counterparty_id=body.counterparty_id,
        total_amount=sum(ln.amount for ln in body.lines),
        uploaded_by=ctx.user.id,
    )
    db.add(doc)
    db.flush()
    invoice = Invoice(document_id=doc.id, series=body.series)
    _set_lines(invoice, body)
    db.add(invoice)
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
    return _out(db, doc, invoice)


@router.get("/{document_id}", response_model=InvoiceOut)
def get_invoice(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> InvoiceOut:
    doc, invoice = _get(db, ctx, document_id)
    return _out(db, doc, invoice)


@router.put("/{document_id}", response_model=InvoiceOut)
def update_invoice(
    document_id: uuid.UUID, body: InvoiceIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> InvoiceOut:
    """Modificarea e permisă doar documentului neînregistrat (în 1C: întâi „Anulare înregistrare”)."""
    ctx.require(POSTING_ROLES)
    doc, invoice = _get(db, ctx, document_id, lock=True)
    if body.version is not None and body.version != doc.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Factura a fost modificată între timp de alt utilizator; redeschideți-o"
        )
    if doc.is_posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Factura este înregistrată; anulați înregistrarea ca să o modificați"
        )
    _validate(db, ctx, body, exclude_id=doc.id)
    doc.doc_number = body.doc_number
    doc.doc_date = body.doc_date
    doc.counterparty_id = body.counterparty_id
    doc.total_amount = sum(ln.amount for ln in body.lines)
    doc.version = (doc.version or 1) + 1
    invoice.series = body.series
    _set_lines(invoice, body)
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
    db.refresh(invoice)
    return _out(db, doc, invoice)


@router.post("/{document_id}/preview", response_model=list[PreviewLine])
def preview(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[PreviewLine]:
    _get(db, ctx, document_id)
    try:
        return preview_out(db, preview_invoice(db, ctx.organization_id, document_id))
    except PostingError as exc:
        raise http_error(exc) from None


class PostResult(BaseModel):
    entries: list[EntryLineOut]
    warnings: list[BudgetWarningOut]


@router.get("/{document_id}/budget-check", response_model=list[BudgetWarningOut])
def budget_check(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[BudgetWarningOut]:
    """Depășirile de buget pe care le produce (sau le-a produs) factura."""
    doc, _ = _get(db, ctx, document_id)
    if doc.is_posted:
        return warnings_out(check_document(db, ctx.organization_id, document_id))
    try:
        generated = preview_invoice(db, ctx.organization_id, document_id)
    except PostingError as exc:
        raise http_error(exc) from None
    amounts: dict = defaultdict(Decimal)
    for g in generated:
        if g.line.budget_line_id:
            amounts[g.line.budget_line_id] += g.line.amount
    return warnings_out(check_amounts(db, ctx.organization_id, dict(amounts), exclude_document=document_id))


@router.post("/{document_id}/post", response_model=PostResult)
def post(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PostResult:
    """Înregistrează factura; depășirea bugetului nu blochează, dar se întoarce ca avertisment."""
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        created = post_invoice(db, ctx.organization_id, document_id, ctx.user.id)
        warnings = check_document(db, ctx.organization_id, document_id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return PostResult(entries=[EntryLineOut.model_validate(e) for e in created], warnings=warnings_out(warnings))


@router.post("/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        unpost_invoice(db, ctx.organization_id, document_id, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
