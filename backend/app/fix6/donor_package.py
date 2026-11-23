"""Pachetul pentru donator: pe fiecare linie de buget — planificat, cheltuit și documentele justificative
(cu semnalarea celor fără scan atașat)."""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Counterparty
from app.core.db import get_db
from app.documents.models import Document
from app.fix6.models import ScannedFile
from app.grants.budget import execution
from app.grants.models import Grant
from app.posting.models import EntryLine

router = APIRouter(prefix="/organizations/{organization_id}", tags=["pachet pentru donator"])


class PackageDoc(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    counterparty: str | None
    amount: Decimal
    has_file: bool


class PackageLine(BaseModel):
    budget_line_id: uuid.UUID
    code: str
    name: str
    planned: Decimal
    spent: Decimal
    remaining: Decimal
    documents: list[PackageDoc]
    missing_files: int


class PackageOut(BaseModel):
    grant_id: uuid.UUID
    grant_code: str
    title: str
    currency: str
    date_to: date | None
    total_planned: Decimal
    total_spent: Decimal
    missing_files: int
    lines: list[PackageLine]


def build_package(db: Session, ctx: OrgContext, grant_id: uuid.UUID, date_to: date | None) -> PackageOut:
    grant = db.scalar(select(Grant).where(Grant.id == grant_id, Grant.organization_id == ctx.organization_id))
    if grant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grantul nu a fost găsit")
    rows = execution(db, ctx.organization_id, grant_id, date_to)
    has_file = (Document.file_name.is_not(None)) | exists().where(ScannedFile.document_id == Document.id)
    q = (
        select(EntryLine.budget_line_id, Document, Counterparty.name, func.sum(EntryLine.amount), has_file)
        .join(Document, Document.id == EntryLine.document_id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(EntryLine.organization_id == ctx.organization_id, EntryLine.grant_id == grant_id,
               EntryLine.budget_line_id.is_not(None))
        .group_by(EntryLine.budget_line_id, Document.id, Counterparty.name)
        .order_by(Document.doc_date, Document.doc_number)
    )  # fmt: skip
    if date_to:
        q = q.where(EntryLine.entry_date <= date_to)
    docs: dict[uuid.UUID, list[PackageDoc]] = {}
    for line_id, doc, cp, amount, filed in db.execute(q).all():
        docs.setdefault(line_id, []).append(
            PackageDoc(document_id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date, counterparty=cp,
                       amount=amount, has_file=bool(filed))
        )  # fmt: skip
    lines = [
        PackageLine(budget_line_id=r.budget_line_id, code=r.code, name=r.name, planned=r.planned, spent=r.spent,
                    remaining=r.remaining, documents=docs.get(r.budget_line_id, []),
                    missing_files=sum(1 for d in docs.get(r.budget_line_id, []) if not d.has_file))
        for r in rows
    ]  # fmt: skip
    return PackageOut(
        grant_id=grant.id, grant_code=grant.code, title=grant.title, currency=grant.currency, date_to=date_to,
        total_planned=sum((x.planned for x in lines), Decimal(0)), total_spent=sum((x.spent for x in lines), Decimal(0)),
        missing_files=sum(x.missing_files for x in lines), lines=lines,
    )  # fmt: skip


@router.get("/grants/{grant_id}/donor-package", response_model=PackageOut)
def donor_package(grant_id: uuid.UUID, date_to: date | None = None, ctx: OrgContext = Depends(get_org_context),
                  db: Session = Depends(get_db)):  # fmt: skip
    return build_package(db, ctx, grant_id, date_to)


@router.get("/grants/{grant_id}/donor-package/csv")
def donor_package_csv(grant_id: uuid.UUID, date_to: date | None = None, ctx: OrgContext = Depends(get_org_context),
                      db: Session = Depends(get_db)):  # fmt: skip
    pkg = build_package(db, ctx, grant_id, date_to)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Linia de buget", "Denumirea", "Planificat", "Cheltuit", "Documentul", "Data", "Furnizorul", "Suma", "Scan atașat"])
    for ln in pkg.lines:
        if not ln.documents:
            w.writerow([ln.code, ln.name, ln.planned, ln.spent, "", "", "", "", ""])
        for i, d in enumerate(ln.documents):
            w.writerow([ln.code, ln.name, ln.planned if i == 0 else "", ln.spent if i == 0 else "", d.doc_number or "",
                        d.doc_date or "", d.counterparty or "", d.amount, "da" if d.has_file else "LIPSEȘTE"])
    data = "﻿" + out.getvalue()
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="pachet-{pkg.grant_code}.csv"'})  # fmt: skip
