"""Stingerea facturilor primite: legarea plăților către furnizori de facturi, suma achitată și soldul rămas pe factură."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Counterparty
from app.core.db import get_db
from app.core.enums import DocumentStatus, DocumentType, PaymentDirection
from app.documents.duplicates import PURCHASE_TYPES
from app.documents.models import Document, Invoice, PaymentOrder
from app.treasury.models import InvoiceSettlement, TreasuryDoc

router = APIRouter(prefix="/organizations/{organization_id}/treasury", tags=["stingerea facturilor primite"])
ZERO = Decimal(0)
SUPPLIER_KINDS = ("bank_payment", "cash_payment")


def payment_status(total: Decimal, paid: Decimal) -> str:
    """„unpaid” / „partial” / „paid”."""
    if paid <= 0:
        return "unpaid"
    return "paid" if paid >= total else "partial"


def paid_by_invoice(db: Session, org: uuid.UUID, invoice_ids) -> dict[uuid.UUID, Decimal]:
    """Suma achitată pe factură: doar stingerile cu plata înregistrată contabil (și nesters)."""
    ids = list(invoice_ids)
    if not ids:
        return {}
    pay = Document
    rows = db.execute(
        select(InvoiceSettlement.invoice_document_id, func.sum(InvoiceSettlement.amount))
        .join(pay, pay.id == InvoiceSettlement.payment_document_id)
        .where(InvoiceSettlement.organization_id == org, InvoiceSettlement.invoice_document_id.in_(ids),
               pay.is_posted.is_(True), pay.deletion_mark.is_not(True))
        .group_by(InvoiceSettlement.invoice_document_id)
    ).all()
    return {i: s for i, s in rows}


def _allocated(db: Session, org: uuid.UUID, *, invoice_id: uuid.UUID | None = None, payment_id: uuid.UUID | None = None,
               exclude_payment: uuid.UUID | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(InvoiceSettlement.amount), 0)).where(InvoiceSettlement.organization_id == org)
    if invoice_id:
        q = q.where(InvoiceSettlement.invoice_document_id == invoice_id)
    if payment_id:
        q = q.where(InvoiceSettlement.payment_document_id == payment_id)
    if exclude_payment:
        q = q.where(InvoiceSettlement.payment_document_id != exclude_payment)
    return db.scalar(q) or ZERO


def _is_supplier_payment(db: Session, doc: Document) -> bool:
    if doc.counterparty_id is None:
        return False
    if doc.type == DocumentType.payment_order:
        direction = db.scalar(select(PaymentOrder.direction).where(PaymentOrder.document_id == doc.id))
        return direction == PaymentDirection.outgoing
    td = db.scalar(select(TreasuryDoc).where(TreasuryDoc.document_id == doc.id))
    return td is not None and td.kind in SUPPLIER_KINDS and td.operation == "supplier"


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


class SettleItem(BaseModel):
    invoice_document_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class SettleIn(BaseModel):
    items: list[SettleItem] = []


class InvoiceOpen(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    series: str | None
    doc_date: date | None
    total: Decimal
    paid: Decimal
    remaining: Decimal
    payment_status: str
    is_posted: bool


class PaymentLink(BaseModel):
    payment_document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    is_posted: bool
    amount: Decimal  # cât din plată stinge factura


class PaymentOut(BaseModel):
    payment_document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None
    amount: Decimal
    allocated: Decimal
    free: Decimal
    is_posted: bool
    items: list[SettleItem]
    open_invoices: list[InvoiceOpen]


class InvoiceSettlementsOut(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    total: Decimal
    paid: Decimal
    remaining: Decimal
    payment_status: str
    payments: list[PaymentLink]


def _invoice_doc(db: Session, org: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.organization_id == org,
                                           Document.type.in_(PURCHASE_TYPES), Document.deletion_mark.is_not(True)))
    if doc is None:
        raise _bad("Factura nu a fost găsită", status.HTTP_404_NOT_FOUND)
    return doc


def _payment_doc(db: Session, org: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.organization_id == org,
                                           Document.deletion_mark.is_not(True)))
    if doc is None:
        raise _bad("Plata nu a fost găsită", status.HTTP_404_NOT_FOUND)
    return doc


def open_invoices(db: Session, org: uuid.UUID, counterparty_id: uuid.UUID, include_paid: bool = False) -> list[InvoiceOpen]:
    rows = db.execute(
        select(Document, Invoice.series).join(Invoice, Invoice.document_id == Document.id)
        .where(Document.organization_id == org, Document.counterparty_id == counterparty_id,
               Document.deletion_mark.is_not(True), Document.status != DocumentStatus.rejected)
        .order_by(Document.doc_date, Document.doc_number)
    ).all()
    paid = paid_by_invoice(db, org, [d.id for d, _ in rows])
    reserved = {d.id: _allocated(db, org, invoice_id=d.id) for d, _ in rows}
    out = []
    for d, series in rows:
        total = d.total_amount or ZERO
        p = paid.get(d.id, ZERO)
        item = InvoiceOpen(document_id=d.id, doc_number=d.doc_number, series=series, doc_date=d.doc_date, total=total, paid=p,
                           remaining=max(total - p, ZERO), payment_status=payment_status(total, p), is_posted=bool(d.is_posted))
        # „rămas de legat” ia în calcul și stingerile plăților încă neînregistrate (rezervate)
        if include_paid or total - reserved[d.id] > 0:
            out.append(item)
    return out


def _payment_out(db: Session, org: uuid.UUID, doc: Document) -> PaymentOut:
    rows = db.scalars(select(InvoiceSettlement).where(InvoiceSettlement.payment_document_id == doc.id)).all()
    cp = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    amount = doc.total_amount or ZERO
    allocated = sum((r.amount for r in rows), ZERO)
    opens = open_invoices(db, org, doc.counterparty_id, include_paid=True) if doc.counterparty_id else []
    linked = {r.invoice_document_id for r in rows}
    return PaymentOut(
        payment_document_id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date, counterparty_id=doc.counterparty_id,
        counterparty_name=cp.name if cp else None, amount=amount, allocated=allocated, free=max(amount - allocated, ZERO),
        is_posted=bool(doc.is_posted), items=[SettleItem(invoice_document_id=r.invoice_document_id, amount=r.amount) for r in rows],
        open_invoices=[o for o in opens if o.remaining > 0 or o.document_id in linked])  # fmt: skip


def replace_settlements(db: Session, org: uuid.UUID, user_id: uuid.UUID | None, pay: Document, items: list[SettleItem]) -> None:
    """Înlocuiește stingerile unei plăți; verifică furnizorul, suma plății și suma fiecărei facturi."""
    if not _is_supplier_payment(db, pay):
        raise _bad("Doar plățile către furnizori (cu contrapartida indicată) pot stinge facturi primite")
    seen: set[uuid.UUID] = set()
    total = ZERO
    for it in items:
        if it.invoice_document_id in seen:
            raise _bad("Aceeași factură apare de două ori")
        seen.add(it.invoice_document_id)
        inv = _invoice_doc(db, org, it.invoice_document_id)
        if inv.counterparty_id != pay.counterparty_id:
            raise _bad(f"Factura {inv.doc_number} este a altui furnizor decât cel al plății")
        room = (inv.total_amount or ZERO) - _allocated(db, org, invoice_id=inv.id, exclude_payment=pay.id)
        if it.amount > room:
            raise _bad(f"Suma depășește restul de achitat al facturii {inv.doc_number} ({_money(max(room, ZERO))})")
        total += it.amount
    if total > (pay.total_amount or ZERO):
        raise _bad(f"Suma stingerilor ({_money(total)}) depășește suma plății ({_money(pay.total_amount or ZERO)})")
    for old in db.scalars(select(InvoiceSettlement).where(InvoiceSettlement.payment_document_id == pay.id)):
        db.delete(old)
    db.flush()
    for it in items:
        db.add(InvoiceSettlement(organization_id=org, invoice_document_id=it.invoice_document_id,
                                 payment_document_id=pay.id, amount=it.amount, created_by=user_id))
    db.flush()


@router.get("/settlements/open-invoices", response_model=list[InvoiceOpen])
def list_open_invoices(counterparty_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Facturile primite de la un furnizor care mai pot fi stinse (cu suma achitată și restul)."""
    cp = db.get(Counterparty, counterparty_id)
    if cp is None or cp.organization_id != ctx.organization_id:
        raise _bad("Contrapartida nu aparține organizației")
    return open_invoices(db, ctx.organization_id, counterparty_id)


@router.get("/payments/{payment_document_id}/settlements", response_model=PaymentOut)
def get_payment_settlements(payment_document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    doc = _payment_doc(db, ctx.organization_id, payment_document_id)
    if not _is_supplier_payment(db, doc):
        raise _bad("Doar plățile către furnizori pot stinge facturi primite")
    return _payment_out(db, ctx.organization_id, doc)


@router.put("/payments/{payment_document_id}/settlements", response_model=PaymentOut)
def put_payment_settlements(payment_document_id: uuid.UUID, body: SettleIn, ctx: OrgContext = Depends(get_org_context),
                            db: Session = Depends(get_db)):
    """Leagă plata de facturi (lista înlocuiește stingerile anterioare; listă goală = dezleagă)."""
    ctx.require(POSTING_ROLES)
    doc = _payment_doc(db, ctx.organization_id, payment_document_id)
    replace_settlements(db, ctx.organization_id, ctx.user.id, doc, body.items)
    write_audit(db, action="settle", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"invoices": [str(i.invoice_document_id) for i in body.items]})  # fmt: skip
    db.commit()
    return _payment_out(db, ctx.organization_id, doc)


@router.get("/invoices/{invoice_document_id}/settlements", response_model=InvoiceSettlementsOut)
def get_invoice_settlements(invoice_document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    inv = _invoice_doc(db, ctx.organization_id, invoice_document_id)
    rows = db.execute(
        select(InvoiceSettlement.amount, Document).join(Document, Document.id == InvoiceSettlement.payment_document_id)
        .where(InvoiceSettlement.invoice_document_id == inv.id, Document.deletion_mark.is_not(True))
        .order_by(Document.doc_date, Document.doc_number)
    ).all()
    total = inv.total_amount or ZERO
    paid = paid_by_invoice(db, ctx.organization_id, [inv.id]).get(inv.id, ZERO)
    return InvoiceSettlementsOut(
        document_id=inv.id, doc_number=inv.doc_number, total=total, paid=paid, remaining=max(total - paid, ZERO),
        payment_status=payment_status(total, paid),
        payments=[PaymentLink(payment_document_id=d.id, doc_number=d.doc_number, doc_date=d.doc_date, is_posted=bool(d.is_posted), amount=a)
                  for a, d in rows])  # fmt: skip


class PaymentRow(BaseModel):
    payment_document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    amount: Decimal
    allocated: Decimal
    free: Decimal
    is_posted: bool


@router.get("/settlements/payments", response_model=list[PaymentRow])
def list_supplier_payments(counterparty_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Plățile către un furnizor, cu cât din ele e deja legat de facturi (și cât a rămas liber)."""
    cp = db.get(Counterparty, counterparty_id)
    if cp is None or cp.organization_id != ctx.organization_id:
        raise _bad("Contrapartida nu aparține organizației")
    docs = db.scalars(select(Document).where(Document.organization_id == ctx.organization_id, Document.counterparty_id == counterparty_id,
                                             Document.deletion_mark.is_not(True),
                                             Document.type.in_((DocumentType.payment_order, DocumentType.other)))
                      .order_by(Document.doc_date, Document.doc_number)).all()  # fmt: skip
    out = []
    for d in docs:
        if not _is_supplier_payment(db, d):
            continue
        allocated = _allocated(db, ctx.organization_id, payment_id=d.id)
        amount = d.total_amount or ZERO
        out.append(PaymentRow(payment_document_id=d.id, doc_number=d.doc_number, doc_date=d.doc_date, amount=amount,
                              allocated=allocated, free=max(amount - allocated, ZERO), is_posted=bool(d.is_posted)))
    return out


class AutoIn(BaseModel):
    counterparty_id: uuid.UUID | None = None


class AutoOut(BaseModel):
    payments: int
    invoices: int
    amount: Decimal


@router.post("/settlements/auto", response_model=AutoOut)
def auto_settle(body: AutoIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> AutoOut:
    """Stinge automat (cele mai vechi facturi întâi) plățile înregistrate către furnizori care nu sunt încă legate."""
    ctx.require(POSTING_ROLES)
    org = ctx.organization_id
    pays_q = (select(Document).where(Document.organization_id == org, Document.is_posted.is_(True), Document.deletion_mark.is_not(True),
                                     Document.counterparty_id.is_not(None))
              .order_by(Document.doc_date, Document.doc_number))  # fmt: skip
    if body.counterparty_id:
        pays_q = pays_q.where(Document.counterparty_id == body.counterparty_id)
    by_cp: dict[uuid.UUID, list[Document]] = defaultdict(list)
    for d in db.scalars(pays_q):
        if _is_supplier_payment(db, d):
            by_cp[d.counterparty_id].append(d)
    n_pay = n_inv = 0
    total = ZERO
    touched: set[uuid.UUID] = set()
    for cp_id, pays in by_cp.items():
        invoices = [i for i in open_invoices(db, org, cp_id) if i.is_posted]
        room = {i.document_id: i.total - _allocated(db, org, invoice_id=i.document_id) for i in invoices}
        for pay in pays:
            free = (pay.total_amount or ZERO) - _allocated(db, org, payment_id=pay.id)
            used = False
            for inv in invoices:
                if free <= 0:
                    break
                take = min(free, room[inv.document_id])
                if take <= 0:
                    continue
                existing = db.scalar(select(InvoiceSettlement).where(InvoiceSettlement.invoice_document_id == inv.document_id,
                                                                     InvoiceSettlement.payment_document_id == pay.id))
                if existing:
                    existing.amount += take
                else:
                    db.add(InvoiceSettlement(organization_id=org, invoice_document_id=inv.document_id,
                                             payment_document_id=pay.id, amount=take, created_by=ctx.user.id))
                db.flush()
                free -= take
                room[inv.document_id] -= take
                total += take
                touched.add(inv.document_id)
                used = True
            n_pay += used
    n_inv = len(touched)
    write_audit(db, action="settle_auto", entity="documents", organization_id=org, user_id=ctx.user.id,
                new_values={"payments": n_pay, "invoices": n_inv, "amount": str(total)})  # fmt: skip
    db.commit()
    return AutoOut(payments=n_pay, invoices=n_inv, amount=total)


def sync_order_settlement(db: Session, org: uuid.UUID, doc: Document, order: PaymentOrder, user_id: uuid.UUID | None) -> None:
    """Ordinul de plată cu factura indicată (câmpul „factura achitată”) stinge factura cu suma ordinului (plafonată la rest)."""
    for old in db.scalars(select(InvoiceSettlement).where(InvoiceSettlement.payment_document_id == doc.id)):
        db.delete(old)
    db.flush()
    if order.invoice_id is None or order.direction != PaymentDirection.outgoing:
        return
    inv_doc_id = db.scalar(select(Invoice.document_id).where(Invoice.id == order.invoice_id))
    inv = db.get(Document, inv_doc_id) if inv_doc_id else None
    if inv is None or inv.organization_id != org:
        return
    room = (inv.total_amount or ZERO) - _allocated(db, org, invoice_id=inv.id, exclude_payment=doc.id)
    amount = min(doc.total_amount or ZERO, room)
    if amount > 0:
        db.add(InvoiceSettlement(organization_id=org, invoice_document_id=inv.id, payment_document_id=doc.id,
                                 amount=amount, created_by=user_id))
        db.flush()


