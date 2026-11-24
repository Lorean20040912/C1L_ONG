"""Facturi emise: listă, creare, modificare, Dt/Kt, înregistrare, anulare, stornare, încasări legate."""

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.bank.models import BankAccount
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants.models import Grant
from app.posting.engine import PostingError
from app.posting.models import EntryLine
from app.posting.router import EntryLineOut, PreviewLine, http_error, preview_out
from app.sales import service
from app.sales.models import SalesInvoice, SalesInvoiceLine, SalesSettlement
from app.taxes.models import TaxRate
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}/sales", tags=["vânzări"])


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


# ───────────────────────── scheme ─────────────────────────


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=4)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2, description="fără TVA")
    vat_rate: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    revenue_type: str = "economic"
    account_id: uuid.UUID | None = None
    grant_id: uuid.UUID | None = None


class LineOut(LineIn):
    amount: Decimal
    vat_amount: Decimal
    total: Decimal


class InvoiceIn(BaseModel):
    series: str = Field(default="", max_length=10)
    number: str | None = Field(default=None, max_length=30)
    doc_date: date
    due_date: date | None = None
    counterparty_id: uuid.UUID
    currency: str = Field(default="MDL", min_length=3, max_length=3)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[LineIn] = Field(min_length=1)
    version: int | None = Field(default=None, description="la modificare: versiunea citită (blocare optimistă)")


class CreditNoteIn(BaseModel):
    doc_date: date
    number: str | None = Field(default=None, max_length=30)
    series: str | None = Field(default=None, max_length=10)
    reason: str | None = Field(default=None, max_length=300)
    lines: list[LineIn] | None = Field(default=None, description="implicit: toate rândurile facturii de bază")


class Party(BaseModel):
    name: str | None
    idno: str | None
    vat_code: str | None = None
    address: str | None = None
    director: str | None = None
    accountant: str | None = None
    banks: list[str] = []


class InvoiceListItem(BaseModel):
    document_id: uuid.UUID
    id: uuid.UUID
    kind: str
    kind_label: str
    series: str
    number: str
    doc_date: date | None
    due_date: date | None
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None
    currency: str | None
    net: Decimal
    vat: Decimal
    gross: Decimal
    paid: Decimal
    balance: Decimal
    status: str
    is_posted: bool | None
    storno_of_id: uuid.UUID | None


class InvoiceOut(InvoiceListItem):
    exchange_rate: Decimal | None
    notes: str | None
    cancel_reason: str | None
    version: int | None
    lines: list[LineOut]
    seller: Party
    client: Party
    credited: Decimal
    storno_number: str | None = None


class PostResult(BaseModel):
    entries: list[EntryLineOut]


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class EntryOut(BaseModel):
    entry_date: date
    debit_account: str
    credit_account: str
    amount: Decimal
    description: str | None


class SettlementItem(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)


class SettlementsIn(BaseModel):
    items: list[SettlementItem] = []


class SettlementOut(SettlementItem):
    number: str
    series: str
    doc_date: date | None
    open_balance: Decimal


class SettlementsOut(BaseModel):
    receipt_document_id: uuid.UUID
    receipt_amount: Decimal
    receipt_posted: bool
    counterparty_id: uuid.UUID | None
    allocated: Decimal
    unallocated: Decimal
    items: list[SettlementOut]


# ───────────────────────── funcții comune ─────────────────────────


def _get(db: Session, ctx: OrgContext, document_id: uuid.UUID, lock: bool = False) -> tuple[Document, SalesInvoice]:
    q = (
        select(Document, SalesInvoice)
        .join(SalesInvoice, SalesInvoice.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == ctx.organization_id)
    )
    row = db.execute(q.with_for_update(of=Document) if lock else q).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura nu a fost găsită")
    return row[0], row[1]


def _party_org(db: Session, org_id: uuid.UUID) -> Party:
    org = db.get(Organization, org_id)
    banks = []
    for b in db.scalars(select(BankAccount).where(BankAccount.organization_id == org_id).order_by(BankAccount.currency)):
        banks.append(f"{b.iban} ({b.currency}){', ' + b.bank_name if b.bank_name else ''}")
    return Party(name=org.name, idno=org.idno, vat_code=org.vat_code, director=org.director_name,
                 accountant=org.chief_accountant_name, banks=banks)


def _out_item(db: Session, doc: Document, inv: SalesInvoice, client: Counterparty | None) -> dict:
    t = service.totals(inv)
    paid = service.posted_settled(db, inv.id)
    sign = -1 if inv.kind == "credit_note" else 1
    balance = service.balance_of(db, inv) if inv.kind == "invoice" else Decimal(0)
    return dict(
        document_id=doc.id, id=inv.id, kind=inv.kind, kind_label=service.KINDS[inv.kind], series=inv.series,
        number=inv.number, doc_date=doc.doc_date, due_date=inv.due_date, counterparty_id=doc.counterparty_id,
        counterparty_name=client.name if client else None, currency=doc.currency, net=sign * t.net,
        vat=sign * t.vat, gross=sign * t.gross, paid=paid, balance=balance, status=inv.status,
        is_posted=doc.is_posted, storno_of_id=inv.storno_of_id,
    )  # fmt: skip


def _out(db: Session, doc: Document, inv: SalesInvoice) -> InvoiceOut:
    client = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    lines = [
        LineOut(**{k: getattr(ln, k) for k in ("description", "unit", "quantity", "unit_price", "amount", "vat_rate",
                                                 "revenue_type", "account_id", "grant_id", "vat_amount")},
                total=Decimal(ln.amount) + Decimal(ln.vat_amount))
        for ln in inv.lines
    ]  # fmt: skip
    storno_number = None
    if inv.storno_of_id:
        o = db.get(SalesInvoice, inv.storno_of_id)
        storno_number = f"{o.series} {o.number}".strip() if o else None
    seller = _party_org(db, doc.organization_id)
    return InvoiceOut(
        **_out_item(db, doc, inv, client), exchange_rate=inv.exchange_rate, notes=inv.notes,
        cancel_reason=inv.cancel_reason, version=doc.version, lines=lines, seller=seller,
        client=Party(name=client.name if client else None, idno=client.idno if client else None,
                     vat_code=client.vat_code if client else None, address=client.address if client else None),
        credited=service.credited_total(db, inv, posted_only=True) if inv.kind == "invoice" else Decimal(0),
        storno_number=storno_number,
    )  # fmt: skip


def _next_number(db: Session, org_id: uuid.UUID, series: str) -> str:
    numbers = db.scalars(select(SalesInvoice.number).where(SalesInvoice.organization_id == org_id,
                                                           SalesInvoice.series == series))
    top = max((int(n) for n in numbers if re.fullmatch(r"\d{1,9}", n or "")), default=0)
    return f"{top + 1:06d}"


def _allowed_rates(db: Session, on_date: date) -> set[Decimal]:
    rates = db.scalars(
        select(TaxRate.value).where(TaxRate.code.like("VAT_%"), TaxRate.valid_from <= on_date,
                                    or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= on_date))
    )
    return {Decimal(r).quantize(Decimal("0.01")) for r in rates} | {Decimal("0.00")}


def _owned(db: Session, model, org_id: uuid.UUID, ids: set, label: str) -> None:
    ids = {i for i in ids if i}
    if ids and set(db.scalars(select(model.id).where(model.organization_id == org_id, model.id.in_(ids)))) != ids:
        raise _bad(f"{label} nu aparține organizației")


def _prepare_lines(db: Session, ctx: OrgContext, body_lines: list[LineIn], doc_date: date) -> list[SalesInvoiceLine]:
    _owned(db, Account, ctx.organization_id, {ln.account_id for ln in body_lines}, "Contul")
    _owned(db, Grant, ctx.organization_id, {ln.grant_id for ln in body_lines}, "Grantul")
    allowed = _allowed_rates(db, doc_date)
    revenue_codes = dict(db.execute(select(Account.id, Account.code).where(
        Account.id.in_({ln.account_id for ln in body_lines if ln.account_id}))).all()) if any(
        ln.account_id for ln in body_lines) else {}
    out = []
    for i, ln in enumerate(body_lines, start=1):
        if ln.revenue_type not in service.REVENUE_TYPES:
            raise _bad(f"Rândul {i}: tipul venitului „{ln.revenue_type}” nu există")
        amount = ln.amount
        if amount is None:
            if ln.quantity is None or ln.unit_price is None:
                raise _bad(f"Rândul {i}: indicați suma sau cantitatea și prețul")
            amount = service.money(ln.quantity * ln.unit_price)
        if amount <= 0:
            raise _bad(f"Rândul {i}: suma trebuie să fie pozitivă")
        rate = ln.vat_rate.quantize(Decimal("0.01"))
        if rate not in allowed:
            raise _bad(f"Rândul {i}: cota TVA {rate}% nu există în cotele în vigoare "
                       f"({', '.join(str(r) for r in sorted(allowed))})")
        if ln.account_id and not revenue_codes.get(ln.account_id, "").startswith("6"):
            raise _bad(f"Rândul {i}: contul de venit trebuie să fie din clasa 6")
        out.append(SalesInvoiceLine(
            organization_id=ctx.organization_id, position=i - 1, description=ln.description, unit=ln.unit,
            quantity=ln.quantity, unit_price=ln.unit_price, amount=amount, vat_rate=rate,
            vat_amount=service.vat_of(amount, rate), revenue_type=ln.revenue_type, account_id=ln.account_id,
            grant_id=ln.grant_id,
        ))  # fmt: skip
    return out


def _client(db: Session, ctx: OrgContext, counterparty_id: uuid.UUID) -> Counterparty:
    client = db.scalar(select(Counterparty).where(Counterparty.id == counterparty_id,
                                                  Counterparty.organization_id == ctx.organization_id))
    if client is None:
        raise _bad("Clientul nu aparține organizației")
    if not (client.idno or "").strip():
        raise _bad(f"Clientul „{client.name}” nu are IDNO; completați-l în Contrapartide")
    return client


def _apply(db: Session, ctx: OrgContext, doc: Document, inv: SalesInvoice, body: InvoiceIn) -> None:
    org = ctx.organization_id
    _client(db, ctx, body.counterparty_id)
    currency = body.currency.upper()
    if currency != "MDL" and not body.exchange_rate:
        raise _bad(f"Factura în {currency}: indicați cursul BNM")
    if body.due_date and body.due_date < body.doc_date:
        raise _bad("Scadența este înaintea datei facturii")
    lines = _prepare_lines(db, ctx, body.lines, body.doc_date)
    if any(ln.vat_rate > 0 for ln in lines) and not service.vat_payer_on(db, org, body.doc_date):
        raise _bad("Organizația nu este plătitoare de TVA la data facturii: cota TVA trebuie să fie 0%")
    series = body.series.strip()
    number = (body.number or "").strip() or _next_number(db, org, series)
    clash = db.scalar(select(SalesInvoice.id).where(
        SalesInvoice.organization_id == org, SalesInvoice.series == series, SalesInvoice.number == number,
        SalesInvoice.id != (inv.id or uuid.uuid4())))
    if clash:
        raise _bad(f"Există deja factura {series} {number}".replace("  ", " "), status.HTTP_409_CONFLICT)
    inv.series, inv.number = series, number
    inv.due_date, inv.notes = body.due_date, body.notes
    inv.exchange_rate = body.exchange_rate if currency != "MDL" else None
    inv.organization_id = org
    inv.lines = lines
    doc.doc_number = f"{series} {number}".strip()
    doc.doc_date = body.doc_date
    doc.counterparty_id = body.counterparty_id
    doc.currency = currency
    doc.total_amount = sum((ln.amount + ln.vat_amount for ln in lines), Decimal(0))


def _save_new(db: Session, ctx: OrgContext, doc: Document, inv: SalesInvoice, body: InvoiceIn) -> None:
    _apply(db, ctx, doc, inv, body)
    db.add(doc)
    db.flush()
    inv.document_id = doc.id
    db.add(inv)
    try:
        db.flush()
    except Exception as exc:  # cursă pe numărul facturii
        db.rollback()
        if "uq_sales_invoices_number" in str(exc):
            raise _bad("Numărul facturii este deja folosit", status.HTTP_409_CONFLICT) from None
        raise
    write_audit(db, action="create", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)


# ───────────────────────── meta și listă ─────────────────────────


class MetaOut(BaseModel):
    revenue_types: dict[str, str]
    vat_rates: list[Decimal]
    vat_payer: bool
    next_number: str
    base_currency: str


@router.get("/meta", response_model=MetaOut)
def meta(series: str = "", on_date: date | None = None, ctx: OrgContext = Depends(get_org_context),
         db: Session = Depends(get_db)) -> MetaOut:
    on = on_date or date.today()
    payer = service.vat_payer_on(db, ctx.organization_id, on)
    rates = sorted(_allowed_rates(db, on)) if payer else [Decimal("0.00")]
    return MetaOut(revenue_types=service.REVENUE_TYPES, vat_rates=rates, vat_payer=payer,
                   next_number=_next_number(db, ctx.organization_id, series.strip()), base_currency="MDL")


@router.get("/invoices", response_model=list[InvoiceListItem])
def list_invoices(
    date_from: date | None = None,
    date_to: date | None = None,
    counterparty_id: uuid.UUID | None = None,
    kind: str | None = None,
    posted: bool | None = None,
    unpaid: bool | None = None,
    q: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[InvoiceListItem]:
    query = (
        select(Document, SalesInvoice, Counterparty)
        .join(SalesInvoice, SalesInvoice.document_id == Document.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == ctx.organization_id)
    )
    if date_from:
        query = query.where(Document.doc_date >= date_from)
    if date_to:
        query = query.where(Document.doc_date <= date_to)
    if counterparty_id:
        query = query.where(Document.counterparty_id == counterparty_id)
    if kind:
        query = query.where(SalesInvoice.kind == kind)
    if posted is not None:
        query = query.where(Document.is_posted.is_(True) if posted else Document.is_posted.is_not(True))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(SalesInvoice.number.ilike(like), Counterparty.name.ilike(like),
                                Counterparty.idno.ilike(like)))
    rows = db.execute(query.order_by(Document.doc_date.desc(), SalesInvoice.number.desc()).limit(500)).all()
    items = [InvoiceListItem(**_out_item(db, d, i, c)) for d, i, c in rows]
    if unpaid:
        items = [i for i in items if i.kind == "invoice" and i.status == "active" and i.is_posted and i.balance > 0]
    return items


@router.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(body: InvoiceIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> InvoiceOut:
    ctx.require(POSTING_ROLES)
    doc = Document(organization_id=ctx.organization_id, type=DocumentType.other, uploaded_by=ctx.user.id)
    inv = SalesInvoice(kind="invoice", organization_id=ctx.organization_id)
    _save_new(db, ctx, doc, inv, body)
    db.commit()
    db.refresh(inv)
    return _out(db, doc, inv)


@router.get("/invoices/{document_id}", response_model=InvoiceOut)
def get_invoice(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> InvoiceOut:
    doc, inv = _get(db, ctx, document_id)
    return _out(db, doc, inv)


@router.put("/invoices/{document_id}", response_model=InvoiceOut)
def update_invoice(document_id: uuid.UUID, body: InvoiceIn, ctx: OrgContext = Depends(get_org_context),
                   db: Session = Depends(get_db)) -> InvoiceOut:
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id, lock=True)
    if body.version is not None and body.version != doc.version:
        raise _bad("Factura a fost modificată între timp de alt utilizator; redeschideți-o", status.HTTP_409_CONFLICT)
    if doc.is_posted:
        raise _bad("Factura este înregistrată; anulați înregistrarea ca să o modificați", status.HTTP_409_CONFLICT)
    if inv.status == "cancelled":
        raise _bad("Factura este anulată", status.HTTP_409_CONFLICT)
    if inv.kind == "credit_note" and body.counterparty_id != doc.counterparty_id:
        raise _bad("Clientul notei de stornare nu se schimbă")
    _apply(db, ctx, doc, inv, body)
    doc.version = (doc.version or 1) + 1
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        if "uq_sales_invoices_number" in str(exc):
            raise _bad("Numărul facturii este deja folosit", status.HTTP_409_CONFLICT) from None
        raise
    write_audit(db, action="update", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)
    db.commit()
    db.refresh(inv)
    return _out(db, doc, inv)


@router.delete("/invoices/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    """Șterge doar un document neînregistrat și nefolosit; altfel se folosește anularea (numărul rămâne în registru)."""
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id, lock=True)
    if doc.is_posted:
        raise _bad("Factura este înregistrată; anulați-o", status.HTTP_409_CONFLICT)
    if service.entry_count(db, ctx.organization_id, doc.id) or db.scalar(
        select(func.count()).select_from(SalesInvoice).where(SalesInvoice.storno_of_id == inv.id)
    ) or db.scalar(select(func.count()).select_from(SalesSettlement).where(SalesSettlement.sales_invoice_id == inv.id)):
        raise _bad("Factura are documente legate; folosiți anularea", status.HTTP_409_CONFLICT)
    write_audit(db, action="delete", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)
    db.delete(inv)
    db.flush()
    db.delete(doc)
    db.commit()


# ───────────────────────── înregistrare, anulare, stornare ─────────────────────────


@router.post("/invoices/{document_id}/preview", response_model=list[PreviewLine])
def preview(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[PreviewLine]:
    doc, inv = _get(db, ctx, document_id)
    try:
        return preview_out(db, service.preview(db, ctx.organization_id, doc, inv))
    except PostingError as exc:
        raise http_error(exc) from None


@router.post("/invoices/{document_id}/post", response_model=PostResult)
def post(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> PostResult:
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id)
    try:
        created = service.post(db, ctx.organization_id, doc, inv, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return PostResult(entries=[EntryLineOut.model_validate(e) for e in created])


@router.post("/invoices/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id)
    try:
        service.unpost(db, ctx.organization_id, doc, inv, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()


@router.post("/invoices/{document_id}/cancel", response_model=InvoiceOut)
def cancel(document_id: uuid.UUID, body: CancelIn, ctx: OrgContext = Depends(get_org_context),
           db: Session = Depends(get_db)) -> InvoiceOut:
    """Anulează factura: se scot înregistrările, numărul rămâne în registru cu mențiunea „anulată”."""
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id, lock=True)
    if inv.status == "cancelled":
        raise _bad("Factura este deja anulată", status.HTTP_409_CONFLICT)
    try:
        if doc.is_posted:
            service.unpost(db, ctx.organization_id, doc, inv, ctx.user.id)
        elif service.posted_settled(db, inv.id):
            raise PostingError("Factura are încasări înregistrate; anulați întâi încasările")
        if db.scalar(select(func.count()).select_from(SalesSettlement).where(SalesSettlement.sales_invoice_id == inv.id)):
            db.query(SalesSettlement).filter(SalesSettlement.sales_invoice_id == inv.id).delete(synchronize_session=False)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    inv.status = "cancelled"
    inv.cancel_reason = body.reason
    inv.cancelled_at = datetime.now(timezone.utc)
    doc.deletion_mark = True
    doc.version = (doc.version or 1) + 1
    write_audit(db, action="cancel", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"reason": body.reason})
    db.commit()
    db.refresh(inv)
    return _out(db, doc, inv)


@router.post("/invoices/{document_id}/credit-note", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def credit_note(document_id: uuid.UUID, body: CreditNoteIn, ctx: OrgContext = Depends(get_org_context),
                db: Session = Depends(get_db)) -> InvoiceOut:
    """Nota de stornare (factură de corecție) a unei facturi înregistrate; se înregistrează separat."""
    ctx.require(POSTING_ROLES)
    doc, inv = _get(db, ctx, document_id, lock=True)
    if inv.kind != "invoice":
        raise _bad("Se stornează doar facturile, nu și notele de stornare")
    if inv.status == "cancelled" or not doc.is_posted:
        raise _bad("Se stornează doar o factură înregistrată și neanulată", status.HTTP_409_CONFLICT)
    lines = body.lines or [
        LineIn(description=ln.description, unit=ln.unit, quantity=ln.quantity, unit_price=ln.unit_price,
               amount=ln.amount, vat_rate=ln.vat_rate, revenue_type=ln.revenue_type, account_id=ln.account_id,
               grant_id=ln.grant_id)
        for ln in inv.lines
    ]
    payload = InvoiceIn(
        series=body.series if body.series is not None else inv.series, number=body.number, doc_date=body.doc_date,
        counterparty_id=doc.counterparty_id, currency=doc.currency or "MDL", exchange_rate=inv.exchange_rate,
        notes=body.reason or f"Stornare factura {inv.series} {inv.number}".replace("  ", " "), lines=lines)
    ndoc = Document(organization_id=ctx.organization_id, type=DocumentType.other, uploaded_by=ctx.user.id)
    note = SalesInvoice(kind="credit_note", organization_id=ctx.organization_id, storno_of_id=inv.id)
    _save_new(db, ctx, ndoc, note, payload)
    if service.totals(note).gross > service.open_credit(db, inv, exclude=note.id):
        db.rollback()
        raise _bad("Nota depășește valoarea stornabilă a facturii de bază")
    db.commit()
    db.refresh(note)
    return _out(db, ndoc, note)


@router.get("/invoices/{document_id}/entries", response_model=list[EntryOut])
def entries(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[EntryOut]:
    _get(db, ctx, document_id)
    rows = db.scalars(select(EntryLine).where(EntryLine.organization_id == ctx.organization_id,
                                              EntryLine.document_id == document_id).order_by(EntryLine.line_no)).all()
    ids = {r.debit_account_id for r in rows} | {r.credit_account_id for r in rows}
    code = dict(db.execute(select(Account.id, Account.code).where(Account.id.in_(ids))).all())
    return [EntryOut(entry_date=r.entry_date, debit_account=code[r.debit_account_id],
                     credit_account=code[r.credit_account_id], amount=r.amount, description=r.description) for r in rows]


# ───────────────────────── încasări legate de factură ─────────────────────────


def _settlements_out(db: Session, ctx: OrgContext, doc: Document, td) -> SettlementsOut:
    rows = db.execute(
        select(SalesSettlement, SalesInvoice, Document)
        .join(SalesInvoice, SalesInvoice.id == SalesSettlement.sales_invoice_id)
        .join(Document, Document.id == SalesInvoice.document_id)
        .where(SalesSettlement.receipt_document_id == doc.id, SalesSettlement.organization_id == ctx.organization_id)
    ).all()
    items = []
    for s, i, d in rows:
        other = service.posted_settled(db, i.id) - (s.amount if doc.is_posted else Decimal(0))
        open_balance = (service.totals(i).gross - service.credited_total(db, i, posted_only=True) - other)
        items.append(SettlementOut(invoice_id=i.id, amount=s.amount, number=i.number, series=i.series,
                                   doc_date=d.doc_date, open_balance=open_balance))
    allocated = sum((i.amount for i in items), Decimal(0))
    return SettlementsOut(receipt_document_id=doc.id, receipt_amount=doc.total_amount or Decimal(0),
                          receipt_posted=bool(doc.is_posted), counterparty_id=doc.counterparty_id, allocated=allocated,
                          unallocated=(doc.total_amount or Decimal(0)) - allocated, items=items)


@router.get("/receipts/{document_id}/settlements", response_model=SettlementsOut)
def get_settlements(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context),
                    db: Session = Depends(get_db)) -> SettlementsOut:
    try:
        doc, td = service.receipt_doc(db, ctx.organization_id, document_id)
    except PostingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _settlements_out(db, ctx, doc, td)


@router.put("/receipts/{document_id}/settlements", response_model=SettlementsOut)
def set_settlements(document_id: uuid.UUID, body: SettlementsIn, ctx: OrgContext = Depends(get_org_context),
                    db: Session = Depends(get_db)) -> SettlementsOut:
    """Leagă încasarea de la client (document de trezorerie, operațiunea „Încasare de la client”) de facturi."""
    ctx.require(POSTING_ROLES)
    try:
        doc, td = service.receipt_doc(db, ctx.organization_id, document_id)
    except PostingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    doc = db.scalar(select(Document).where(Document.id == doc.id).with_for_update())
    if doc.is_posted:
        raise _bad("Încasarea este înregistrată; anulați înregistrarea ca să schimbați legările", status.HTTP_409_CONFLICT)
    ids = [i.invoice_id for i in body.items]
    if len(set(ids)) != len(ids):
        raise _bad("O factură apare de două ori")
    total = sum((i.amount for i in body.items), Decimal(0))
    if total > (doc.total_amount or Decimal(0)):
        raise _bad(f"Suma legată ({total}) depășește suma încasării ({doc.total_amount})")
    for item in body.items:
        row = db.execute(
            select(SalesInvoice, Document).join(Document, Document.id == SalesInvoice.document_id)
            .where(SalesInvoice.id == item.invoice_id, SalesInvoice.organization_id == ctx.organization_id)
        ).first()
        if row is None:
            raise _bad("Factura nu aparține organizației")
        inv, idoc = row
        if inv.kind != "invoice" or inv.status != "active" or not idoc.is_posted:
            raise _bad(f"Factura {inv.series} {inv.number} trebuie să fie înregistrată și neanulată".replace("  ", " "))
        if idoc.counterparty_id != doc.counterparty_id:
            raise _bad(f"Factura {inv.series} {inv.number} este a altui client".replace("  ", " "))
        if (idoc.currency or "MDL") != (doc.currency or "MDL"):
            raise _bad(f"Factura {inv.series} {inv.number} e în {idoc.currency}, încasarea în {doc.currency}".replace("  ", " "))
        open_balance = service.balance_of(db, inv)
        if item.amount > open_balance:
            raise _bad(f"Factura {inv.series} {inv.number}: de încasat doar {open_balance}".replace("  ", " "))
    db.query(SalesSettlement).filter(SalesSettlement.receipt_document_id == doc.id).delete(synchronize_session=False)
    for item in body.items:
        db.add(SalesSettlement(organization_id=ctx.organization_id, receipt_document_id=doc.id,
                               sales_invoice_id=item.invoice_id, amount=item.amount))
    db.flush()
    write_audit(db, action="update", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"settlements": [str(i.invoice_id) for i in body.items]})
    db.commit()
    return _settlements_out(db, ctx, doc, td)


@router.get("/invoices/{document_id}/receipts", response_model=list[dict])
def invoice_receipts(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context),
                     db: Session = Depends(get_db)) -> list[dict]:
    """Încasările legate de factură (cu data, suma și starea)."""
    _, inv = _get(db, ctx, document_id)
    rows = db.execute(
        select(SalesSettlement, Document)
        .join(Document, Document.id == SalesSettlement.receipt_document_id)
        .where(SalesSettlement.sales_invoice_id == inv.id)
        .order_by(Document.doc_date, Document.doc_number)
    ).all()
    return [{"receipt_document_id": str(d.id), "doc_number": d.doc_number, "doc_date": d.doc_date.isoformat() if d.doc_date else None,
             "amount": str(s.amount), "is_posted": bool(d.is_posted)} for s, d in rows]
