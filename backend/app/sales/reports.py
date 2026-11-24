"""Rapoarte de vânzări: sold clienți cu vechime, jurnalul vânzărilor (TVA colectată)."""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.documents.models import Document
from app.posting.models import EntryLine
from app.sales import service
from app.sales.models import SalesInvoice, SalesSettlement
from app.treasury.models import TreasuryDoc

router = APIRouter(prefix="/organizations/{organization_id}/sales/reports", tags=["rapoarte vânzări"])
ZERO = Decimal(0)


class OpenInvoice(BaseModel):
    document_id: uuid.UUID
    number: str
    doc_date: date
    due_date: date
    currency: str
    gross_mdl: Decimal
    open_mdl: Decimal
    age_days: int
    overdue_days: int


class CustomerRow(BaseModel):
    counterparty_id: uuid.UUID
    name: str
    idno: str | None
    invoiced: Decimal
    credited: Decimal
    received: Decimal
    balance: Decimal
    unallocated_receipts: Decimal
    not_due: Decimal
    age_0_30: Decimal
    age_31_60: Decimal
    age_61_90: Decimal
    age_over_90: Decimal
    overdue: Decimal
    invoices: list[OpenInvoice]


class CustomerBalances(BaseModel):
    as_of: date
    rows: list[CustomerRow]
    total_balance: Decimal
    total_overdue: Decimal
    buckets: dict[str, Decimal]
    ledger_balance: Decimal


def _bucket(days: int) -> str:
    return "age_0_30" if days <= 30 else "age_31_60" if days <= 60 else "age_61_90" if days <= 90 else "age_over_90"


def customer_balances(db: Session, org_id: uuid.UUID, as_of: date, counterparty_id: uuid.UUID | None = None) -> CustomerBalances:
    q = (
        select(Document, SalesInvoice)
        .join(SalesInvoice, SalesInvoice.document_id == Document.id)
        .where(Document.organization_id == org_id, Document.is_posted.is_(True), SalesInvoice.status == "active",
               Document.doc_date <= as_of)
    )
    if counterparty_id:
        q = q.where(Document.counterparty_id == counterparty_id)
    docs = db.execute(q.order_by(Document.doc_date, SalesInvoice.number)).all()
    by_client: dict[uuid.UUID, dict] = {}
    inv_state: dict[uuid.UUID, dict] = {}
    for doc, inv in docs:
        c = by_client.setdefault(doc.counterparty_id, dict(invoiced=ZERO, credited=ZERO, received=ZERO, invoices=[]))
        rate = service.rate_of(doc, inv)
        gross = service.money(service.totals(inv).gross * rate)
        if inv.kind == "credit_note":
            c["credited"] += gross
            if inv.storno_of_id in inv_state:
                inv_state[inv.storno_of_id]["open"] -= gross
            continue
        c["invoiced"] += gross
        state = dict(doc=doc, inv=inv, rate=rate, gross=gross, open=gross, client=doc.counterparty_id)
        inv_state[inv.id] = state
        c["invoices"].append(state)
    # încasările legate explicit (doar cele înregistrate până la dată)
    explicit_by_receipt: dict[uuid.UUID, Decimal] = {}
    if inv_state:
        rows = db.execute(
            select(SalesSettlement, Document).join(Document, Document.id == SalesSettlement.receipt_document_id)
            .where(SalesSettlement.sales_invoice_id.in_(inv_state), Document.is_posted.is_(True),
                   Document.deletion_mark.is_not(True), Document.doc_date <= as_of)
        ).all()
        for s, rdoc in rows:
            st = inv_state[s.sales_invoice_id]
            mdl = service.money(s.amount * st["rate"])
            st["open"] -= mdl
            by_client[st["client"]]["received"] += mdl
            explicit_by_receipt[rdoc.id] = explicit_by_receipt.get(rdoc.id, ZERO) + mdl
    # încasările fără legare: se sting facturile cele mai vechi (FIFO)
    receipts = db.execute(
        select(Document, func.coalesce(func.sum(EntryLine.amount), 0))
        .join(TreasuryDoc, TreasuryDoc.document_id == Document.id)
        .join(EntryLine, EntryLine.document_id == Document.id)
        .join(Account, Account.id == EntryLine.credit_account_id)
        .where(Document.organization_id == org_id, Document.is_posted.is_(True), Document.deletion_mark.is_not(True),
               Document.doc_date <= as_of, TreasuryDoc.operation == "customer",
               TreasuryDoc.kind.in_(("bank_receipt", "cash_receipt")), Account.code.like("221%"))
        .group_by(Document.id)
    ).all()
    pool: dict[uuid.UUID, Decimal] = {}
    for rdoc, mdl in receipts:
        if counterparty_id and rdoc.counterparty_id != counterparty_id:
            continue
        free = Decimal(mdl) - explicit_by_receipt.get(rdoc.id, ZERO)
        if free > 0:
            pool[rdoc.counterparty_id] = pool.get(rdoc.counterparty_id, ZERO) + free
    unallocated = dict(pool)
    for client_id, free in pool.items():
        c = by_client.setdefault(client_id, dict(invoiced=ZERO, credited=ZERO, received=ZERO, invoices=[]))
        for st in c["invoices"]:
            if free <= 0:
                break
            if st["open"] <= 0:
                continue
            used = min(free, st["open"])
            st["open"] -= used
            free -= used
            c["received"] += used
        unallocated[client_id] = free
        c["received"] += free
    names = {c.id: c for c in db.scalars(select(Counterparty).where(Counterparty.id.in_(by_client.keys()))) } if by_client else {}
    out_rows: list[CustomerRow] = []
    buckets = {k: ZERO for k in ("not_due", "age_0_30", "age_31_60", "age_61_90", "age_over_90")}
    total_overdue = ZERO
    for client_id, c in by_client.items():
        cp = names.get(client_id)
        row = dict(not_due=ZERO, age_0_30=ZERO, age_31_60=ZERO, age_61_90=ZERO, age_over_90=ZERO, overdue=ZERO)
        invoices = []
        for st in c["invoices"]:
            if st["open"] <= 0:
                continue
            doc, inv = st["doc"], st["inv"]
            due = inv.due_date or doc.doc_date
            age, overdue_days = (as_of - doc.doc_date).days, (as_of - due).days
            row[_bucket(age)] += st["open"]
            if overdue_days > 0:
                row["overdue"] += st["open"]
            else:
                row["not_due"] += st["open"]
            invoices.append(OpenInvoice(
                document_id=doc.id, number=f"{inv.series} {inv.number}".strip(), doc_date=doc.doc_date, due_date=due,
                currency=doc.currency or "MDL", gross_mdl=st["gross"], open_mdl=st["open"], age_days=age,
                overdue_days=max(overdue_days, 0)))  # fmt: skip
        balance = c["invoiced"] - c["credited"] - c["received"]
        if balance == 0 and not invoices and unallocated.get(client_id, ZERO) == 0:
            continue
        out_rows.append(CustomerRow(
            counterparty_id=client_id, name=cp.name if cp else "(client șters)", idno=cp.idno if cp else None,
            invoiced=c["invoiced"], credited=c["credited"], received=c["received"], balance=balance,
            unallocated_receipts=unallocated.get(client_id, ZERO), invoices=invoices, **row))  # fmt: skip
        for k in buckets:
            buckets[k] += row.get(k, ZERO)
        total_overdue += row["overdue"]
    out_rows.sort(key=lambda r: r.balance, reverse=True)
    # soldul din contabilitate (221*), pentru verificare încrucișată
    ids = list(db.scalars(select(Account.id).where(Account.organization_id == org_id, Account.code.like("221%"))))
    ledger = ZERO
    if ids:
        dt = db.scalar(select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
            EntryLine.organization_id == org_id, EntryLine.entry_date <= as_of, EntryLine.debit_account_id.in_(ids)))
        kt = db.scalar(select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
            EntryLine.organization_id == org_id, EntryLine.entry_date <= as_of, EntryLine.credit_account_id.in_(ids)))
        ledger = Decimal(dt) - Decimal(kt)
    return CustomerBalances(as_of=as_of, rows=out_rows, total_balance=sum((r.balance for r in out_rows), ZERO),
                            total_overdue=total_overdue, buckets=buckets, ledger_balance=ledger)


@router.get("/customer-balances", response_model=CustomerBalances)
def customer_balances_route(as_of: date | None = None, counterparty_id: uuid.UUID | None = None,
                            ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> CustomerBalances:
    """Sold clienți (221) cu vechimea creanțelor: după data facturii și după scadență; încasările fără legare sting cele mai vechi facturi."""
    return customer_balances(db, ctx.organization_id, as_of or date.today(), counterparty_id)


@router.get("/customer-balances.csv")
def customer_balances_csv(as_of: date | None = None, ctx: OrgContext = Depends(get_org_context),
                          db: Session = Depends(get_db)) -> Response:
    rep = customer_balances(db, ctx.organization_id, as_of or date.today())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Client", "IDNO", "Facturat", "Stornat", "Încasat", "Sold", "Nescadent", "0-30", "31-60", "61-90", ">90", "Restant"])
    for r in rep.rows:
        w.writerow([r.name, r.idno or "", r.invoiced, r.credited, r.received, r.balance, r.not_due, r.age_0_30,
                    r.age_31_60, r.age_61_90, r.age_over_90, r.overdue])
    w.writerow(["Total", "", "", "", "", rep.total_balance, rep.buckets["not_due"], rep.buckets["age_0_30"],
                rep.buckets["age_31_60"], rep.buckets["age_61_90"], rep.buckets["age_over_90"], rep.total_overdue])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="sold-clienti.csv"'})


# ───────────────────────── jurnalul vânzărilor (TVA colectată) ─────────────────────────


class SalesVatRow(BaseModel):
    document_id: uuid.UUID
    entry_date: date
    doc_number: str
    kind: str
    counterparty: str | None
    counterparty_idno: str | None
    vat_code: str | None
    rate: Decimal
    base: Decimal  # în MDL; negativ pentru stornări
    vat: Decimal
    total: Decimal
    is_posted: bool


def sales_vat_rows(db: Session, org_id: uuid.UUID, date_from: date, date_to: date, rate: Decimal | None = None) -> list[SalesVatRow]:
    q = (
        select(Document, SalesInvoice, Counterparty)
        .join(SalesInvoice, SalesInvoice.document_id == Document.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == org_id, SalesInvoice.status == "active",
               Document.doc_date.between(date_from, date_to))
        .order_by(Document.doc_date, SalesInvoice.number)
    )
    rows: list[SalesVatRow] = []
    for doc, inv, cp in db.execute(q).all():
        sign = -1 if inv.kind == "credit_note" else 1
        fx = service.rate_of(doc, inv)
        per_rate: dict[Decimal, list[Decimal]] = {}
        for ln in inv.lines:
            r = Decimal(ln.vat_rate or 0)
            if rate is not None and r != rate:
                continue
            acc = per_rate.setdefault(r, [ZERO, ZERO])
            acc[0] += service.money(Decimal(ln.amount) * fx)
            acc[1] += service.money(Decimal(ln.vat_amount) * fx)
        for r, (base, vat) in sorted(per_rate.items()):
            rows.append(SalesVatRow(
                document_id=doc.id, entry_date=doc.doc_date, doc_number=f"{inv.series} {inv.number}".strip(),
                kind=inv.kind, counterparty=cp.name if cp else None, counterparty_idno=cp.idno if cp else None,
                vat_code=cp.vat_code if cp else None, rate=r, base=sign * base, vat=sign * vat,
                total=sign * (base + vat), is_posted=bool(doc.is_posted)))  # fmt: skip
    return rows


class SalesJournal(BaseModel):
    date_from: date
    date_to: date
    rows: list[SalesVatRow]
    base_total: Decimal
    vat_total: Decimal


@router.get("/journal", response_model=SalesJournal)
def journal(date_from: date, date_to: date, rate: Decimal | None = None, ctx: OrgContext = Depends(get_org_context),
            db: Session = Depends(get_db)) -> SalesJournal:
    """Jurnalul vânzărilor: facturile și notele de stornare pe cote TVA (valori în MDL)."""
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")
    rows = sales_vat_rows(db, ctx.organization_id, date_from, date_to, rate)
    return SalesJournal(date_from=date_from, date_to=date_to, rows=rows,
                        base_total=sum((r.base for r in rows), ZERO), vat_total=sum((r.vat for r in rows), ZERO))
