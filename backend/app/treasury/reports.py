"""Rapoarte de achiziții: datorii față de furnizori și jurnalul facturilor fiscale primite."""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import SubcontoType
from app.documents.models import Document, Invoice
from app.posting.models import EntryLine, EntryLineAnalytics
from app.treasury.models import InvoiceSettlement
from app.treasury.settlements import paid_by_invoice, payment_status
from app.treasury.settlements import payment_status as payment_status_of

router = APIRouter(prefix="/organizations/{organization_id}/treasury/reports", tags=["rapoarte achiziții"])
CENT = Decimal("0.01")


class SupplierDebtRow(BaseModel):
    counterparty_id: uuid.UUID | None
    name: str
    idno: str | None
    opening: Decimal
    debit: Decimal
    credit: Decimal
    closing: Decimal
    invoices_total: Decimal = Decimal(0)  # suma facturilor primite (în perioadă, până la data de sfârșit)
    invoices_paid: Decimal = Decimal(0)  # cât din ele e stins prin plăți legate
    invoices_remaining: Decimal = Decimal(0)
    count_unpaid: int = 0
    count_partial: int = 0
    count_paid: int = 0
    age_0_30: Decimal
    age_31_60: Decimal
    age_61_90: Decimal
    age_over_90: Decimal


class SupplierDebts(BaseModel):
    date_from: date
    date_to: date
    rows: list[SupplierDebtRow]
    total_opening: Decimal
    total_debit: Decimal
    total_credit: Decimal
    total_closing: Decimal


def _lines(db: Session, org: uuid.UUID, prefix: str, date_to: date, counterparty_id: uuid.UUID | None):
    """Mișcările pe conturile de datorii (521*) cu analitica furnizorului: (data, doc, +credit/-debit, furnizor)."""
    accounts = set(db.scalars(select(Account.id).where(Account.organization_id == org, Account.code.like(f"{prefix}%"))))
    if not accounts:
        return []
    out = []
    for column, side, sign in ((EntryLine.credit_account_id, "K", 1), (EntryLine.debit_account_id, "D", -1)):
        rows = db.execute(
            select(EntryLine.entry_date, EntryLine.document_id, EntryLine.amount, EntryLine.description,
                   EntryLineAnalytics.ref_id)
            .outerjoin(EntryLineAnalytics, (EntryLineAnalytics.entry_line_id == EntryLine.id)
                       & (EntryLineAnalytics.entry_date == EntryLine.entry_date) & (EntryLineAnalytics.side == side)
                       & (EntryLineAnalytics.subconto_type == SubcontoType.counterparty))
            .where(EntryLine.organization_id == org, EntryLine.entry_date <= date_to, column.in_(accounts))
        ).all()
        for d, doc_id, amount, desc, cp in rows:
            if counterparty_id and cp != counterparty_id:
                continue
            out.append((d, doc_id, sign * amount, cp, desc))
    return out


@router.get("/supplier-debts", response_model=SupplierDebts)
def supplier_debts(
    date_from: date,
    date_to: date,
    counterparty_id: uuid.UUID | None = None,
    account_prefix: str = "521",
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> SupplierDebts:
    """Datorii față de furnizori (sold creditor pe 521) cu vechimea datoriei (FIFO pe facturi)."""
    if date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Data de început e după data de sfârșit")
    lines = _lines(db, ctx.organization_id, account_prefix, date_to, counterparty_id)
    by_cp: dict = defaultdict(list)
    for d, _doc, signed, cp, _desc in lines:
        by_cp[cp].append((d, signed))
    names = {c.id: c for c in db.scalars(select(Counterparty).where(
        Counterparty.organization_id == ctx.organization_id, Counterparty.id.in_([k for k in by_cp if k])))}
    rows: list[SupplierDebtRow] = []
    for cp, moves in by_cp.items():
        opening = sum((s for d, s in moves if d < date_from), Decimal(0))
        debit = -sum((s for d, s in moves if date_from <= d and s < 0), Decimal(0))
        credit = sum((s for d, s in moves if date_from <= d and s > 0), Decimal(0))
        closing = opening + credit - debit
        buckets = [Decimal(0)] * 4
        if closing > 0:  # FIFO: plățile sting cele mai vechi facturi
            paid = -sum((s for _d, s in moves if s < 0), Decimal(0))
            for d, s in sorted((m for m in moves if m[1] > 0), key=lambda m: m[0]):
                left = s - min(s, paid)
                paid -= min(s, paid)
                if left > 0:
                    age = (date_to - d).days
                    buckets[0 if age <= 30 else 1 if age <= 60 else 2 if age <= 90 else 3] += left
        c = names.get(cp)
        rows.append(SupplierDebtRow(
            counterparty_id=cp, name=c.name if c else "Fără furnizor indicat", idno=c.idno if c else None,
            opening=opening, debit=debit, credit=credit, closing=closing,
            age_0_30=buckets[0], age_31_60=buckets[1], age_61_90=buckets[2], age_over_90=buckets[3]))
    _fill_settlements(db, ctx.organization_id, date_to, rows)
    rows = [r for r in rows if any((r.opening, r.debit, r.credit, r.closing))]
    rows.sort(key=lambda r: r.name.lower())
    return SupplierDebts(
        date_from=date_from, date_to=date_to, rows=rows,
        total_opening=sum((r.opening for r in rows), Decimal(0)), total_debit=sum((r.debit for r in rows), Decimal(0)),
        total_credit=sum((r.credit for r in rows), Decimal(0)), total_closing=sum((r.closing for r in rows), Decimal(0)))


def _fill_settlements(db: Session, org: uuid.UUID, date_to: date, rows: list[SupplierDebtRow]) -> None:
    """Pe furnizor: facturile primite și cât din ele e achitat (stingeri), cu numărul facturilor neachitate / parțiale / achitate."""
    ids = [r.counterparty_id for r in rows if r.counterparty_id]
    if not ids:
        return
    invs = db.execute(
        select(Document.id, Document.counterparty_id, Document.total_amount)
        .join(Invoice, Invoice.document_id == Document.id)
        .where(Document.organization_id == org, Document.counterparty_id.in_(ids), Document.deletion_mark.is_not(True),
               Document.doc_date <= date_to)
    ).all()
    paid = paid_by_invoice(db, org, [i[0] for i in invs])
    by_cp = {r.counterparty_id: r for r in rows}
    for doc_id, cp, total in invs:
        row, total = by_cp[cp], total or Decimal(0)
        p = min(paid.get(doc_id, Decimal(0)), total)
        row.invoices_total += total
        row.invoices_paid += p
        row.invoices_remaining += total - p
        state = payment_status(total, p)
        if state == "paid":
            row.count_paid += 1
        elif state == "partial":
            row.count_partial += 1
        else:
            row.count_unpaid += 1


class DebtMove(BaseModel):
    entry_date: date
    document_id: uuid.UUID
    doc_number: str | None
    doc_type: str | None
    debit: Decimal
    credit: Decimal
    description: str | None
    invoice_paid: Decimal | None = None  # doar la facturi
    invoice_remaining: Decimal | None = None
    payment_status: str | None = None  # unpaid / partial / paid
    allocated: Decimal | None = None  # doar la plăți: cât din ele stinge facturi


@router.get("/supplier-debts/moves", response_model=list[DebtMove])
def supplier_debt_moves(
    date_from: date,
    date_to: date,
    counterparty_id: uuid.UUID | None = None,
    account_prefix: str = "521",
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[DebtMove]:
    """Documentele care au mișcat datoria unui furnizor (fără `counterparty_id`: mișcările fără furnizor)."""
    moves = [m for m in _lines(db, ctx.organization_id, account_prefix, date_to, None) if m[0] >= date_from]
    moves = [m for m in moves if m[3] == counterparty_id]
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({m[1] for m in moves})))}
    inv_ids = set(db.scalars(select(Invoice.document_id).where(Invoice.document_id.in_({m[1] for m in moves}))))
    paid = paid_by_invoice(db, ctx.organization_id, inv_ids)
    alloc = dict(db.execute(
        select(InvoiceSettlement.payment_document_id, func.sum(InvoiceSettlement.amount))
        .where(InvoiceSettlement.payment_document_id.in_({m[1] for m in moves}))
        .group_by(InvoiceSettlement.payment_document_id)).all())
    out = []
    for d, doc_id, s, _cp, desc in sorted(moves, key=lambda m: (m[0], str(m[1]))):
        move = DebtMove(entry_date=d, document_id=doc_id, doc_number=docs[doc_id].doc_number if doc_id in docs else None,
                        doc_type=docs[doc_id].type.value if doc_id in docs and docs[doc_id].type else None,
                        debit=-s if s < 0 else Decimal(0), credit=s if s > 0 else Decimal(0), description=desc)
        if doc_id in inv_ids and s > 0:
            total, p = docs[doc_id].total_amount or s, paid.get(doc_id, Decimal(0))
            move.invoice_paid, move.invoice_remaining, move.payment_status = p, max(total - p, Decimal(0)), payment_status(total, p)
        elif s < 0:
            move.allocated = alloc.get(doc_id, Decimal(0))
        out.append(move)
    return out


class InvoiceJournalRow(BaseModel):
    document_id: uuid.UUID
    doc_date: date | None
    series: str | None
    doc_number: str | None
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None
    idno: str | None
    vat_code: str | None
    e_invoice_id: str | None
    total: Decimal
    net: Decimal
    vat: Decimal
    is_posted: bool
    paid: Decimal = Decimal(0)
    remaining: Decimal = Decimal(0)
    payment_status: str = "unpaid"  # unpaid / partial / paid


class VatRateTotal(BaseModel):
    vat_rate: Decimal
    base: Decimal
    vat: Decimal


class InvoiceJournal(BaseModel):
    rows: list[InvoiceJournalRow]
    total: Decimal
    net: Decimal
    vat: Decimal
    paid: Decimal = Decimal(0)
    remaining: Decimal = Decimal(0)
    by_rate: list[VatRateTotal]


@router.get("/received-invoices", response_model=InvoiceJournal)
def received_invoices(
    date_from: date | None = None,
    date_to: date | None = None,
    counterparty_id: uuid.UUID | None = None,
    posted: bool | None = None,
    q: str | None = None,
    payment_status: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> InvoiceJournal:
    """Jurnalul facturilor fiscale primite; TVA se extrage din suma rândului (suma include TVA)."""
    query = (
        select(Document, Invoice, Counterparty)
        .join(Invoice, Invoice.document_id == Document.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == ctx.organization_id, Document.deletion_mark.is_not(True))
    )
    if date_from:
        query = query.where(Document.doc_date >= date_from)
    if date_to:
        query = query.where(Document.doc_date <= date_to)
    if counterparty_id:
        query = query.where(Document.counterparty_id == counterparty_id)
    if posted is not None:
        query = query.where(Document.is_posted.is_(True) if posted else Document.is_posted.is_not(True))
    if payment_status and payment_status not in ("unpaid", "partial", "paid"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Starea plății poate fi: neachitată, parțială sau achitată")
    rows: list[InvoiceJournalRow] = []
    by_rate: dict[Decimal, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    needle = (q or "").strip().lower()
    found = db.execute(query.order_by(Document.doc_date, Document.doc_number)).all()
    paid_map = paid_by_invoice(db, ctx.organization_id, [d.id for d, _i, _c in found])
    for doc, invoice, cp in found:
        total = doc.total_amount or Decimal(0)
        paid = min(paid_map.get(doc.id, Decimal(0)), total)
        state = payment_status_of(total, paid)
        if payment_status and state != payment_status:
            continue
        if needle and needle not in " ".join(filter(None, [doc.doc_number, invoice.series, cp.name if cp else None])).lower():
            continue
        vat = Decimal(0)
        for ln in invoice.lines:
            rate = ln.vat_rate or Decimal(0)
            line_vat = (ln.amount * rate / (100 + rate)).quantize(CENT, rounding=ROUND_HALF_UP) if rate else Decimal(0)
            vat += line_vat
            by_rate[rate][0] += ln.amount - line_vat
            by_rate[rate][1] += line_vat
        rows.append(InvoiceJournalRow(
            document_id=doc.id, doc_date=doc.doc_date, series=invoice.series, doc_number=doc.doc_number,
            counterparty_id=doc.counterparty_id, counterparty_name=cp.name if cp else None, idno=cp.idno if cp else None,
            vat_code=cp.vat_code if cp else None, e_invoice_id=invoice.e_invoice_id, total=total, net=total - vat,
            vat=vat, is_posted=bool(doc.is_posted), paid=paid, remaining=total - paid, payment_status=state))
    return InvoiceJournal(
        rows=rows, total=sum((r.total for r in rows), Decimal(0)), net=sum((r.net for r in rows), Decimal(0)),
        vat=sum((r.vat for r in rows), Decimal(0)), paid=sum((r.paid for r in rows), Decimal(0)),
        remaining=sum((r.remaining for r in rows), Decimal(0)),
        by_rate=[VatRateTotal(vat_rate=r, base=v[0], vat=v[1]) for r, v in sorted(by_rate.items())])
