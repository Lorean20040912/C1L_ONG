"""Registrul (jurnalul) TVA și decontul pe perioadă: achizițiile (facturi primite, TVA dedusă) și vânzările
(facturi emise, TVA colectată din `app/sales`); decontul net = colectată − dedusă.

Baza impozabilă e suma rândului facturii (fără TVA), cota — `vat_rate`; TVA = bază × cotă.
Facturile marcate pentru ștergere nu intră. Cota lipsă se tratează ca 0% (fără TVA).
"""

import uuid
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Counterparty
from app.core.db import get_db
from app.documents.models import Document, Invoice, InvoiceLine
from app.regulated.export import table_xlsx
from app.sales.reports import SalesVatRow, sales_vat_rows
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["TVA"])
CENT = Decimal("0.01")


class VatRow(BaseModel):
    document_id: uuid.UUID
    entry_date: date
    doc_number: str | None
    counterparty: str | None
    counterparty_idno: str | None
    vat_code: str | None
    rate: Decimal
    base: Decimal
    vat: Decimal
    total: Decimal
    is_posted: bool


class VatRateTotal(BaseModel):
    rate: Decimal
    base: Decimal
    vat: Decimal
    documents: int


class VatMonthTotal(BaseModel):
    month: date
    base: Decimal
    vat: Decimal


class VatReport(BaseModel):
    date_from: date
    date_to: date
    vat_payer: bool
    rows: list[VatRow]
    by_rate: list[VatRateTotal]
    by_month: list[VatMonthTotal]
    base_total: Decimal
    vat_total: Decimal
    posted_vat_total: Decimal
    # vânzările: TVA colectată și decontul net (colectată − dedusă; pozitiv = de plătit la buget)
    sales_rows: list[SalesVatRow] = []
    sales_by_rate: list[VatRateTotal] = []
    sales_base_total: Decimal = Decimal(0)
    collected_vat_total: Decimal = Decimal(0)
    deductible_vat_total: Decimal = Decimal(0)
    net_vat: Decimal = Decimal(0)
    posted_net_vat: Decimal = Decimal(0)


def _vat(base: Decimal, rate: Decimal) -> Decimal:
    return (base * rate / 100).quantize(CENT, ROUND_HALF_UP)


def build_report(db: Session, ctx: OrgContext, date_from: date, date_to: date, rate: Decimal | None) -> VatReport:
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")
    org = db.get(Organization, ctx.organization_id)
    q = (
        select(Document, InvoiceLine, Counterparty)
        .join(Invoice, Invoice.document_id == Document.id)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(
            Document.organization_id == ctx.organization_id,
            Document.deletion_mark.is_not(True),
            Document.doc_date.between(date_from, date_to),
        )
        .order_by(Document.doc_date, Document.doc_number, InvoiceLine.position)
    )
    # un rând al registrului = factura × cota
    groups: dict[tuple[uuid.UUID, Decimal], VatRow] = {}
    for doc, line, cp in db.execute(q).all():
        r = Decimal(line.vat_rate or 0)
        if rate is not None and r != rate:
            continue
        key = (doc.id, r)
        row = groups.get(key)
        if row is None:
            row = groups[key] = VatRow(
                document_id=doc.id, entry_date=doc.doc_date, doc_number=doc.doc_number,
                counterparty=cp.name if cp else None, counterparty_idno=cp.idno if cp else None,
                vat_code=cp.vat_code if cp else None, rate=r, base=Decimal(0), vat=Decimal(0),
                total=Decimal(0), is_posted=bool(doc.is_posted),
            )  # fmt: skip
        row.base += line.amount
    rows = list(groups.values())
    for row in rows:
        row.vat = _vat(row.base, row.rate)
        row.total = row.base + row.vat
    by_rate: dict[Decimal, VatRateTotal] = {}
    by_month: dict[date, VatMonthTotal] = {}
    for row in rows:
        t = by_rate.setdefault(row.rate, VatRateTotal(rate=row.rate, base=Decimal(0), vat=Decimal(0), documents=0))
        t.base += row.base
        t.vat += row.vat
        t.documents += 1
        m = by_month.setdefault(row.entry_date.replace(day=1), VatMonthTotal(month=row.entry_date.replace(day=1), base=Decimal(0), vat=Decimal(0)))  # fmt: skip
        m.base += row.base
        m.vat += row.vat
    sales = sales_vat_rows(db, ctx.organization_id, date_from, date_to, rate)
    sales_rate: dict[Decimal, VatRateTotal] = {}
    for sr in sales:
        t = sales_rate.setdefault(sr.rate, VatRateTotal(rate=sr.rate, base=Decimal(0), vat=Decimal(0), documents=0))
        t.base += sr.base
        t.vat += sr.vat
        t.documents += 1
    collected = sum((r.vat for r in sales), Decimal(0))
    deductible = sum((r.vat for r in rows), Decimal(0))
    posted_collected = sum((r.vat for r in sales if r.is_posted), Decimal(0))
    return VatReport(
        sales_rows=sales, sales_by_rate=sorted(sales_rate.values(), key=lambda t: t.rate),
        sales_base_total=sum((r.base for r in sales), Decimal(0)), collected_vat_total=collected,
        deductible_vat_total=deductible, net_vat=collected - deductible,
        posted_net_vat=posted_collected - sum((r.vat for r in rows if r.is_posted), Decimal(0)),
        date_from=date_from, date_to=date_to, vat_payer=bool(org and org.vat_payer_from), rows=rows,
        by_rate=sorted(by_rate.values(), key=lambda t: t.rate), by_month=sorted(by_month.values(), key=lambda t: t.month),
        base_total=sum((r.base for r in rows), Decimal(0)), vat_total=sum((r.vat for r in rows), Decimal(0)),
        posted_vat_total=sum((r.vat for r in rows if r.is_posted), Decimal(0)),
    )  # fmt: skip


@router.get("/vat", response_model=VatReport)
def vat_report(
    date_from: date,
    date_to: date,
    rate: Decimal | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> VatReport:
    """Jurnalul TVA al achizițiilor și decontul pe cote și luni."""
    return build_report(db, ctx, date_from, date_to, rate)


@router.get("/vat.xlsx")
def vat_xlsx(
    date_from: date,
    date_to: date,
    rate: Decimal | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Response:
    rep = build_report(db, ctx, date_from, date_to, rate)
    rows: list[list] = [
        [f"{r.entry_date:%d.%m.%Y}", r.doc_number or "", r.counterparty or "", r.counterparty_idno or "",
         r.vat_code or "", float(r.rate), float(r.base), float(r.vat), float(r.total)]  # fmt: skip
        for r in rep.rows
    ]
    rows.append(["", "", "Total", "", "", "", float(rep.base_total), float(rep.vat_total), float(rep.base_total + rep.vat_total)])
    rows.append([])
    rows.append(["Decont pe cote", "", "", "", "", "Cota %", "Baza", "TVA", "Documente"])
    rows += [["", "", "", "", "", float(t.rate), float(t.base), float(t.vat), t.documents] for t in rep.by_rate]
    rows.append([])
    rows.append(["Jurnalul vânzărilor", "", "", "", "", "Cota %", "Baza", "TVA colectată", "Total"])
    rows += [[f"{r.entry_date:%d.%m.%Y}", r.doc_number, r.counterparty or "", r.counterparty_idno or "",
              r.vat_code or "", float(r.rate), float(r.base), float(r.vat), float(r.total)] for r in rep.sales_rows]  # fmt: skip
    rows.append(["", "", "Decont net", "", "", "", "TVA colectată", float(rep.collected_vat_total), ""])
    rows.append(["", "", "", "", "", "", "TVA dedusă", float(rep.deductible_vat_total), ""])
    rows.append(["", "", "", "", "", "", "De plătit (+) / de recuperat (−)", float(rep.net_vat), ""])
    content = table_xlsx(
        "Jurnalul TVA", f"Achiziții și vânzări, {date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}",
        ["Data", "Document", "Furnizor", "IDNO", "Cod TVA", "Cota %", "Baza", "TVA", "Total"], rows,
        [12, 16, 36, 16, 14, 9, 14, 14, 14],
    )  # fmt: skip
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="jurnal-tva.xlsx"'},
    )
