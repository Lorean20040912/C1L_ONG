"""Vânzările: transformarea facturii emise în rânduri Dt/Kt, totaluri, stingerea cu încasări.

Factura emisă nu conține formule: fiecare rând cere operațiunile `revenue` (Dt 221 — Kt 618 / 617,
după tipul venitului) și `vat_collected` (Dt 221 — Kt 534.4); nota de stornare cere operațiunile
inverse (`revenue_storno`, `vat_storno`). Conturile vin din `posting_rules` (document `sales_invoice`).
Încasarea de la client este documentul de trezorerie existent (operațiunea `customer`).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import SubcontoType
from app.documents.models import Document
from app.documents.posting import _mdl
from app.posting.engine import AnalyticsInput, PostingError, post_document, unpost_document
from app.posting.models import EntryLine
from app.posting.rules import GeneratedLine, OperationInput, build_lines
from app.sales.models import SalesInvoice, SalesInvoiceLine, SalesSettlement
from app.treasury.models import TreasuryDoc
from app.workspaces.models import Organization

CENT = Decimal("0.01")
REVENUE_TYPES = {"economic": "Activitate economică (618)", "organization": "Venituri ale organizației (617)"}
KINDS = {"invoice": "Factură emisă", "credit_note": "Notă de stornare"}
DOC_TYPE = "sales_invoice"


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def vat_of(amount: Decimal, rate: Decimal) -> Decimal:
    return money(Decimal(amount) * Decimal(rate or 0) / 100)


@dataclass
class Totals:
    net: Decimal
    vat: Decimal

    @property
    def gross(self) -> Decimal:
        return self.net + self.vat


def totals(invoice: SalesInvoice) -> Totals:
    return Totals(
        sum((Decimal(ln.amount) for ln in invoice.lines), Decimal(0)),
        sum((Decimal(ln.vat_amount) for ln in invoice.lines), Decimal(0)),
    )


def rate_of(doc: Document, invoice: SalesInvoice) -> Decimal:
    """Cursul de conversie în MDL (1 pentru factura în lei)."""
    if not doc.currency or doc.currency == "MDL":
        return Decimal(1)
    return Decimal(invoice.exchange_rate or 0)


def to_mdl(amount: Decimal, doc: Document, invoice: SalesInvoice) -> Decimal:
    return money(Decimal(amount) * rate_of(doc, invoice))


def vat_payer_on(db: Session, org_id: uuid.UUID, on_date: date) -> bool:
    org = db.get(Organization, org_id)
    return bool(org and org.vat_payer_from and org.vat_payer_from <= on_date)


def check_ready(db: Session, org_id: uuid.UUID, doc: Document, invoice: SalesInvoice) -> None:
    """Verificările de dinaintea înregistrării (aceleași la salvare și la înregistrare)."""
    from app.catalogs.models import Counterparty

    if invoice.status == "cancelled":
        raise PostingError("Factura este anulată")
    if not invoice.lines:
        raise PostingError("Factura nu are rânduri")
    if doc.doc_date is None:
        raise PostingError("Factura nu are dată")
    client = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    if client is None or client.organization_id != org_id:
        raise PostingError("Alegeți clientul")
    if not (client.idno or "").strip():
        raise PostingError(f"Clientul „{client.name}” nu are IDNO; completați-l în Contrapartide")
    if doc.currency and doc.currency != "MDL" and not invoice.exchange_rate:
        raise PostingError(f"Factura în {doc.currency}: indicați cursul BNM")
    if any(Decimal(ln.vat_rate or 0) > 0 for ln in invoice.lines) and not vat_payer_on(db, org_id, doc.doc_date):
        raise PostingError("Organizația nu este plătitoare de TVA la data facturii: cota TVA trebuie să fie 0%")
    if invoice.kind == "credit_note":
        original = db.get(SalesInvoice, invoice.storno_of_id) if invoice.storno_of_id else None
        if original is None or original.organization_id != org_id:
            raise PostingError("Nota de stornare nu are factura de bază")
        original_doc = db.get(Document, original.document_id)
        if not original_doc.is_posted:
            raise PostingError("Factura de bază nu este înregistrată")
        if original_doc.counterparty_id != doc.counterparty_id:
            raise PostingError("Clientul notei diferă de cel al facturii de bază")
        remaining = open_credit(db, original, exclude=invoice.id)
        if totals(invoice).gross > remaining:
            raise PostingError(f"Nota depășește valoarea stornabilă a facturii de bază ({remaining})")


def operations(db: Session, org_id: uuid.UUID, doc: Document, invoice: SalesInvoice) -> list[OperationInput]:
    check_ready(db, org_id, doc, invoice)
    storno = invoice.kind == "credit_note"
    side = "K" if storno else "D"
    rate = rate_of(doc, invoice)
    foreign = doc.currency if doc.currency and doc.currency != "MDL" else None
    client = [AnalyticsInput(side=side, subconto_type=SubcontoType.counterparty, ref_id=doc.counterparty_id)]
    label = f"{invoice.series} {invoice.number}".strip()
    ops: list[OperationInput] = []
    for ln in invoice.lines:
        for operation, amount in (
            ("revenue_storno" if storno else "revenue", Decimal(ln.amount)),
            ("vat_storno" if storno else "vat_collected", Decimal(ln.vat_amount)),
        ):
            if amount <= 0:
                continue
            mdl, cur = _mdl(amount, foreign, rate) if foreign else (amount, None)
            is_revenue = operation.startswith("revenue")
            ops.append(
                OperationInput(
                    operation=operation,
                    amount=mdl,
                    attributes={"revenue_type": ln.revenue_type},
                    grant_id=ln.grant_id,
                    currency=foreign,
                    currency_amount=cur,
                    description=f"{'Stornare ' if storno else ''}factura {label}: {ln.description}"[:300],
                    analytics=list(client),
                    credit_account_id=(ln.account_id if (is_revenue and not storno) else None),
                    debit_account_id=(ln.account_id if (is_revenue and storno) else None),
                )
            )
    return ops


def preview(db: Session, org_id: uuid.UUID, doc: Document, invoice: SalesInvoice) -> list[GeneratedLine]:
    return build_lines(
        db, organization_id=org_id, document_type=DOC_TYPE, doc_date=doc.doc_date,
        operations=operations(db, org_id, doc, invoice),
    )


def post(db: Session, org_id: uuid.UUID, doc: Document, invoice: SalesInvoice, user_id):
    generated = preview(db, org_id, doc, invoice)
    return post_document(
        db, organization_id=org_id, document_id=doc.id, lines=[g.line for g in generated], user_id=user_id,
        rule_refs=[f"{g.rule.id} ({g.rule.source_ref})" for g in generated],
    )


def unpost(db: Session, org_id: uuid.UUID, doc: Document, invoice: SalesInvoice, user_id) -> None:
    if posted_settled(db, invoice.id) > 0:
        raise PostingError("Factura are încasări înregistrate; anulați întâi încasările")
    if invoice.kind == "invoice":
        credited = db.scalar(
            select(func.count()).select_from(SalesInvoice).join(Document, Document.id == SalesInvoice.document_id)
            .where(SalesInvoice.storno_of_id == invoice.id, SalesInvoice.status == "active", Document.is_posted.is_(True))
        )
        if credited:
            raise PostingError("Factura are note de stornare înregistrate; anulați-le întâi")
    unpost_document(db, organization_id=org_id, document_id=doc.id, user_id=user_id)


# ───────────────────────── solduri și stingere ─────────────────────────


def posted_settled(db: Session, invoice_id: uuid.UUID) -> Decimal:
    """Cât s-a încasat pe factură (încasări înregistrate), în valuta facturii."""
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(SalesSettlement.amount), 0))
            .join(Document, Document.id == SalesSettlement.receipt_document_id)
            .where(SalesSettlement.sales_invoice_id == invoice_id, Document.is_posted.is_(True),
                   Document.deletion_mark.is_not(True))
        )
    )


def credited_total(db: Session, invoice: SalesInvoice, exclude: uuid.UUID | None = None, posted_only: bool = False) -> Decimal:
    """Valoarea notelor de stornare (active) ale facturii."""
    q = (
        select(SalesInvoice)
        .join(Document, Document.id == SalesInvoice.document_id)
        .where(SalesInvoice.storno_of_id == invoice.id, SalesInvoice.status == "active")
    )
    if exclude:
        q = q.where(SalesInvoice.id != exclude)
    if posted_only:
        q = q.where(Document.is_posted.is_(True))
    return sum((totals(n).gross for n in db.scalars(q)), Decimal(0))


def open_credit(db: Session, original: SalesInvoice, exclude: uuid.UUID | None = None) -> Decimal:
    return totals(original).gross - credited_total(db, original, exclude=exclude)


def receipt_doc(db: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> tuple[Document, TreasuryDoc]:
    row = db.execute(
        select(Document, TreasuryDoc)
        .join(TreasuryDoc, TreasuryDoc.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == org_id)
    ).first()
    if row is None:
        raise PostingError("Încasarea nu a fost găsită")
    doc, td = row
    if td.kind not in ("bank_receipt", "cash_receipt") or td.operation != "customer":
        raise PostingError("Documentul nu este o încasare de la client")
    return doc, td


def balance_of(db: Session, invoice: SalesInvoice) -> Decimal:
    """Restul de încasat al facturii (valuta facturii), după note de stornare și încasări legate."""
    return totals(invoice).gross - credited_total(db, invoice, posted_only=True) - posted_settled(db, invoice.id)


def entry_count(db: Session, org_id: uuid.UUID, document_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(EntryLine).where(
            EntryLine.organization_id == org_id, EntryLine.document_id == document_id
        )
    ) or 0
