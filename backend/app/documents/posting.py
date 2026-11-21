"""Înregistrarea documentelor concrete: factura primită și ordinul de plată.

Documentul nu conține formule: își transformă rândurile în operațiuni
(`OperationInput`), regulile din `posting_rules` dau conturile, iar motorul
(`post_document`) scrie înregistrările și rulajele în aceeași tranzacție.

Sursa de finanțare a rândului vine din linia de buget → grant → funding_type:
- „unrestricted” / „cotizații” → mijloace nepredestinate (717);
- „economic” → activitatea economică (718);
- orice alt tip de grant → mijloace cu destinație specială (716 + 537/616).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.bank.models import BankAccount
from app.catalogs.models import Account
from app.core.enums import LineKind, PaymentDirection, SubcontoType
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, Grant
from app.posting.engine import AnalyticsInput, PostingError, post_document, unpost_document
from app.posting.models import EntryLine
from app.posting.rules import GeneratedLine, OperationInput, build_lines, policy_in_force

BASE_CURRENCY = "MDL"
CENT = Decimal("0.01")

UNRESTRICTED_FUNDING = {"unrestricted", "cotizatii", "cotizații", "membership_fees", "own_funds"}
ECONOMIC_FUNDING = {"economic"}

# rândurile care se consumă imediat (cheltuială), nu intră în stoc / mijloace fixe
EXPENSE_KINDS = {LineKind.service}


def funding_of(grant: Grant) -> str:
    kind = (grant.funding_type or "").strip().lower()
    if kind in UNRESTRICTED_FUNDING:
        return "unrestricted"
    if kind in ECONOMIC_FUNDING:
        return "economic"
    return "special_purpose"


def _term(grant: Grant, on_date: date) -> str:
    """Finanțarea pe termen lung (425) dacă proiectul mai durează peste un an, altfel curentă (537)."""
    return "long" if grant.end_date - on_date > timedelta(days=365) else "current"


def _load(db: Session, model, organization_id: uuid.UUID, document_id: uuid.UUID):
    row = db.scalar(
        select(model)
        .join(Document, Document.id == model.document_id)
        .where(model.document_id == document_id, Document.organization_id == organization_id)
    )
    if row is None:
        raise PostingError("Documentul nu a fost găsit")
    return row


# ───────────────────────── factura primită ─────────────────────────


@dataclass
class _LineContext:
    line: InvoiceLine
    grant: Grant | None
    funding: str | None


def _line_context(db: Session, organization_id: uuid.UUID, line: InvoiceLine) -> _LineContext:
    if line.budget_line_id is None:
        return _LineContext(line, None, None)
    grant = db.scalar(
        select(Grant)
        .join(BudgetLine, BudgetLine.grant_id == Grant.id)
        .where(BudgetLine.id == line.budget_line_id, Grant.organization_id == organization_id)
    )
    if grant is None:
        raise PostingError(f"Rândul „{line.description}”: linia de buget nu aparține organizației")
    return _LineContext(line, grant, funding_of(grant))


def invoice_operations(
    db: Session, organization_id: uuid.UUID, doc: Document, invoice: Invoice
) -> list[OperationInput]:
    if not invoice.lines:
        raise PostingError("Factura nu are rânduri")
    if doc.doc_date is None:
        raise PostingError("Factura nu are dată")
    policy = policy_in_force(db, organization_id, doc.doc_date)
    supplier = (
        [AnalyticsInput(side="K", subconto_type=SubcontoType.counterparty, ref_id=doc.counterparty_id)]
        if doc.counterparty_id
        else []
    )
    ops: list[OperationInput] = []
    for no, line in enumerate(invoice.lines, start=1):
        ctx = _line_context(db, organization_id, line)
        attrs: dict = {"line_kind": line.line_kind.value}
        if ctx.funding:
            attrs["funding"] = ctx.funding

        def op(operation: str, extra: dict | None = None, main: bool = False, line=line, attrs=attrs, ctx=ctx):
            return OperationInput(
                operation=operation,
                amount=line.amount,
                attributes={**attrs, **(extra or {})},
                grant_id=ctx.grant.id if ctx.grant else None,
                budget_line_id=line.budget_line_id,
                cost_item_id=line.cost_item_id,
                quantity=line.quantity,
                description=line.description,
                analytics=list(supplier) if main else [],
                debit_account_id=line.account_id if main else None,
            )

        consumed = line.line_kind in EXPENSE_KINDS or (line.line_kind == LineKind.low_value_item and line.put_into_use)
        if consumed:
            # cheltuiala se ține pe proiecte (docs/11 §1, SEM): fără linie de buget nu știm sursa
            if ctx.funding is None:
                raise PostingError(f"Rândul {no} („{line.description}”): alegeți linia de buget (proiectul)")
            ops.append(op("expense", main=True))
            if ctx.funding == "special_purpose":
                ops.append(op("income_recognition"))
        elif line.line_kind == LineKind.fixed_asset:
            ops.append(op("fixed_asset_receipt", main=True))
            if ctx.funding == "special_purpose":
                ops.append(op("fixed_asset_fund", {"term": _term(ctx.grant, doc.doc_date)}))
        else:  # materiale, mărfuri, OMVSD care nu se dau încă în exploatare
            ops.append(op("stock_receipt", main=True))
            if ctx.funding == "special_purpose" and policy and policy.stock_to_deferred_income == "all":
                ops.append(op("deferred_income"))
    return ops


def _create_fixed_assets(
    db: Session, organization_id: uuid.UUID, doc: Document, invoice: Invoice, generated: list[GeneratedLine]
) -> None:
    """Fișa MF pentru fiecare rând „mijloc fix” (ToR F2b.2); punerea în funcțiune la data facturii,
    amortizarea din luna următoare."""
    receipts = iter(g for g in generated if g.rule.operation == "fixed_asset_receipt")
    count = db.scalar(select(func.count()).select_from(FixedAsset).where(FixedAsset.organization_id == organization_id))
    depreciation_account = db.scalar(
        select(Account.id).where(Account.organization_id == organization_id, Account.code == "124")
    )
    for line in invoice.lines:
        if line.line_kind != LineKind.fixed_asset:
            continue
        generated_line = next(receipts).line
        count += 1
        in_use = bool(line.put_into_use)
        next_month = (doc.doc_date.replace(day=1) + timedelta(days=32)).replace(day=1)
        asset = FixedAsset(
            organization_id=organization_id,
            inventory_no=f"MF-{count:05d}",
            name=line.description,
            initial_cost=line.amount,
            account_id=generated_line.debit_account_id,
            depreciation_account_id=depreciation_account,
            commissioning_date=doc.doc_date if in_use else None,
            depreciation_start=next_month if in_use else None,
            status="in_use" if in_use else "suspended",
            grant_id=generated_line.grant_id,
            budget_line_id=line.budget_line_id,
            document_id=doc.id,
        )
        db.add(asset)
        db.flush()
        line.fixed_asset_id = asset.id


def _remove_fixed_assets(db: Session, doc: Document) -> None:
    db.execute(
        update(InvoiceLine)
        .where(InvoiceLine.invoice_id == select(Invoice.id).where(Invoice.document_id == doc.id).scalar_subquery())
        .values(fixed_asset_id=None)
        .execution_options(synchronize_session="fetch")
    )
    for asset in db.scalars(select(FixedAsset).where(FixedAsset.document_id == doc.id)):
        db.delete(asset)
    db.flush()


def preview_invoice(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> list[GeneratedLine]:
    invoice = _load(db, Invoice, organization_id, document_id)
    doc = db.get(Document, document_id)
    ops = invoice_operations(db, organization_id, doc, invoice)
    return build_lines(
        db, organization_id=organization_id, document_type="invoice", doc_date=doc.doc_date, operations=ops
    )


def post_invoice(
    db: Session, organization_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID | None
) -> list[EntryLine]:
    generated = preview_invoice(db, organization_id, document_id)
    invoice = _load(db, Invoice, organization_id, document_id)
    doc = db.get(Document, document_id)
    entries = post_document(
        db,
        organization_id=organization_id,
        document_id=document_id,
        lines=[g.line for g in generated],
        user_id=user_id,
        rule_refs=[f"{g.rule.id} ({g.rule.source_ref})" for g in generated],
    )
    _remove_fixed_assets(db, doc)  # la reînregistrare fișele se refac
    _create_fixed_assets(db, organization_id, doc, invoice, generated)
    return entries


def unpost_invoice(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    unpost_document(db, organization_id=organization_id, document_id=document_id, user_id=user_id)
    _remove_fixed_assets(db, db.get(Document, document_id))


# ───────────────────────── ordinul de plată ─────────────────────────


def _mdl(amount: Decimal, currency: str | None, rate: Decimal | None) -> tuple[Decimal, Decimal | None]:
    if not currency or currency == BASE_CURRENCY:
        return amount, None
    if not rate:
        raise PostingError(f"Plata în {currency}: lipsește cursul BNM")
    return (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP), amount


def payment_operations(
    db: Session, organization_id: uuid.UUID, doc: Document, order: PaymentOrder
) -> tuple[str, list[OperationInput]]:
    if doc.total_amount is None or doc.total_amount <= 0:
        raise PostingError("Ordinul de plată nu are sumă")
    if order.kind == "grouped_tax":
        raise PostingError("Plata cumulată a impozitelor vine odată cu modulul salarii")
    bank = db.get(BankAccount, order.bank_account_id) if order.bank_account_id else None
    if bank is None or bank.organization_id != organization_id:
        raise PostingError("Alegeți contul bancar al organizației")
    amount, currency_amount = _mdl(doc.total_amount, doc.currency, order.exchange_rate)
    counterparty = doc.counterparty_id
    if counterparty is None and order.invoice_id:
        counterparty = db.scalar(
            select(Document.counterparty_id)
            .join(Invoice, Invoice.document_id == Document.id)
            .where(Invoice.id == order.invoice_id)
        )
    grant_id = bank.grant_id or next((ln.grant_id for ln in order.lines if ln.grant_id), None)
    common = dict(
        amount=amount,
        currency=doc.currency if currency_amount is not None else None,
        currency_amount=currency_amount,
        grant_id=grant_id,
        description=order.purpose,
    )

    if order.direction == PaymentDirection.outgoing:
        analytics = (
            [AnalyticsInput(side="D", subconto_type=SubcontoType.counterparty, ref_id=counterparty)]
            if counterparty
            else []
        )
        return "payment_order", [
            OperationInput(
                operation="supplier_payment", analytics=analytics, credit_account_id=bank.account_id, **common
            )
        ]

    # încasare: deocamdată tranșa grantului (alte încasări vin cu documentele lor)
    if grant_id is None:
        raise PostingError(
            "Încasarea fără grant nu are încă regulă; indicați grantul (cont bancar dedicat sau rândul plății)"
        )
    return "grant_income", [OperationInput(operation="tranche_received", debit_account_id=bank.account_id, **common)]


def preview_payment(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> list[GeneratedLine]:
    order = _load(db, PaymentOrder, organization_id, document_id)
    doc = db.get(Document, document_id)
    document_type, ops = payment_operations(db, organization_id, doc, order)
    return build_lines(
        db, organization_id=organization_id, document_type=document_type, doc_date=doc.doc_date, operations=ops
    )


def post_payment(
    db: Session, organization_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID | None
) -> list[EntryLine]:
    generated = preview_payment(db, organization_id, document_id)
    return post_document(
        db,
        organization_id=organization_id,
        document_id=document_id,
        lines=[g.line for g in generated],
        user_id=user_id,
        rule_refs=[f"{g.rule.id} ({g.rule.source_ref})" for g in generated],
    )
