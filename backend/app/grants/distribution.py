"""Distribuirea stocurilor cumpărate din grant (docs/11 §2.3, ART sit.2).

Stocul intră cu Dt 211 — Kt 521 și poartă linia de buget (cheltuiala se numără la achiziție).
La distribuire: Dt 716 — Kt 211 (regula cu `budget_line = drop`, ca linia să nu se numere de două ori)
și, în aceeași sumă, veniturile: Dt 537 — Kt 616, sau Dt 535 — Kt 616 dacă suma fusese trecută la
venituri anticipate (`from_deferred`).
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import DocumentType
from app.documents.models import Document
from app.documents.posting import funding_of
from app.grants.admin_router import _grant
from app.posting.engine import PostingError, post_document, unpost_document
from app.posting.models import EntryLine
from app.posting.router import PreviewLine, http_error, preview_out
from app.posting.rules import GeneratedLine, OperationInput, build_lines

router = APIRouter(prefix="/organizations/{organization_id}", tags=["granturi avansat"])

PREFIX = "DS-"  # numărul documentului de distribuire


class DistributionIn(BaseModel):
    doc_date: date
    grant_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    description: str = Field(min_length=1)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    from_deferred: bool = False  # suma fusese trecută la venituri anticipate (535)


class DistributionOut(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    grant_id: uuid.UUID | None
    amount: Decimal | None
    is_posted: bool | None
    description: str | None = None


def _operations(grant, body: DistributionIn) -> list[OperationInput]:
    if funding_of(grant) != "special_purpose":
        raise PostingError("Distribuirea stocurilor se face doar din granturi cu destinație specială")
    attrs = {"funding": "special_purpose"}
    common = dict(amount=body.amount, grant_id=grant.id, description=body.description)
    return [
        OperationInput(operation="expense", attributes=attrs, quantity=body.quantity, **common),
        OperationInput(
            operation="income_recognition",
            attributes={**attrs, **({"income_from": "deferred"} if body.from_deferred else {})},
            **common,
        ),
    ]


def _stock_balance(
    db: Session, organization_id: uuid.UUID, grant_id: uuid.UUID, on_date: date, exclude_document: uuid.UUID | None
) -> Decimal:
    """Stocul grantului pe contul 211 la data distribuirii: intrările pe grant minus distribuirile lui."""
    account = db.scalar(select(Account.id).where(Account.organization_id == organization_id, Account.code == "211"))
    if account is None:
        raise PostingError("Contul 211 lipsește din planul de conturi")
    base = (EntryLine.organization_id == organization_id, EntryLine.grant_id == grant_id, EntryLine.entry_date <= on_date)
    if exclude_document is not None:
        base = (*base, EntryLine.document_id != exclude_document)
    total_in = db.scalar(select(func.coalesce(func.sum(EntryLine.amount), 0)).where(*base, EntryLine.debit_account_id == account))
    total_out = db.scalar(select(func.coalesce(func.sum(EntryLine.amount), 0)).where(*base, EntryLine.credit_account_id == account))
    return total_in - total_out


def _generate(
    db: Session, ctx: OrgContext, body: DistributionIn, exclude_document: uuid.UUID | None = None
) -> list[GeneratedLine]:
    grant = _grant(db, ctx, body.grant_id)
    if _stock_balance(db, ctx.organization_id, body.grant_id, body.doc_date, exclude_document) < body.amount:
        raise PostingError("Suma distribuită depășește stocul grantului (contul 211)")
    return build_lines(
        db,
        organization_id=ctx.organization_id,
        document_type="stock_distribution",
        doc_date=body.doc_date,
        operations=_operations(grant, body),
    )


@router.post("/stock-distributions/preview", response_model=list[PreviewLine])
def preview_distribution(
    body: DistributionIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[PreviewLine]:
    try:
        return preview_out(db, _generate(db, ctx, body))
    except PostingError as exc:
        raise http_error(exc) from exc


def _next_number(db: Session, organization_id: uuid.UUID, year: int) -> str:
    numbers = db.scalars(
        select(Document.doc_number).where(
            Document.organization_id == organization_id, Document.doc_number.like(f"{PREFIX}{year}-%")
        )
    ).all()
    last = max((int(n.rsplit("-", 1)[1]) for n in numbers if n.rsplit("-", 1)[1].isdigit()), default=0)
    return f"{PREFIX}{year}-{last + 1:03d}"


@router.post("/stock-distributions", response_model=DistributionOut, status_code=status.HTTP_201_CREATED)
def create_distribution(
    body: DistributionIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> DistributionOut:
    ctx.require(POSTING_ROLES)
    _grant(db, ctx, body.grant_id, lock=True)
    doc = Document(
        organization_id=ctx.organization_id, type=DocumentType.other,
        doc_number=_next_number(db, ctx.organization_id, body.doc_date.year), doc_date=body.doc_date,
        total_amount=body.amount, uploaded_by=ctx.user.id,
    )  # fmt: skip
    db.add(doc)
    db.flush()
    try:
        generated = _generate(db, ctx, body)
        post_document(
            db, organization_id=ctx.organization_id, document_id=doc.id, lines=[g.line for g in generated],
            user_id=ctx.user.id, rule_refs=sorted({f"{g.rule.id} ({g.rule.source_ref})" for g in generated}),
        )  # fmt: skip
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    write_audit(
        db, action="create", entity="stock_distributions", entity_id=doc.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        new_values=body.model_dump(mode="json"),
    )  # fmt: skip
    db.commit()
    return DistributionOut(
        document_id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date, grant_id=body.grant_id,
        amount=body.amount, is_posted=True, description=body.description,
    )  # fmt: skip


@router.get("/stock-distributions", response_model=list[DistributionOut])
def list_distributions(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[DistributionOut]:
    docs = db.scalars(
        select(Document)
        .where(
            Document.organization_id == ctx.organization_id,
            Document.doc_number.like(f"{PREFIX}%"),
            Document.deletion_mark.is_not(True),
        )
        .order_by(Document.doc_date.desc(), Document.doc_number.desc())
    ).all()
    first = {
        doc_id: (grant_id, desc)
        for doc_id, grant_id, desc in db.execute(
            select(EntryLine.document_id, EntryLine.grant_id, EntryLine.description)
            .where(EntryLine.document_id.in_([d.id for d in docs]))
            .distinct(EntryLine.document_id)
        )
    }
    return [
        DistributionOut(
            document_id=d.id, doc_number=d.doc_number, doc_date=d.doc_date, amount=d.total_amount,
            is_posted=d.is_posted, grant_id=first.get(d.id, (None, None))[0], description=first.get(d.id, (None, None))[1],
        )  # fmt: skip
        for d in docs
    ]


@router.delete("/stock-distributions/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_distribution(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> None:
    """Anulează distribuirea: înregistrările dispar și documentul se marchează pentru ștergere."""
    ctx.require(POSTING_ROLES)
    doc = db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.organization_id == ctx.organization_id,
            Document.doc_number.like(f"{PREFIX}%"),
        )
        .with_for_update()
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Distribuirea nu a fost găsită")
    try:
        if doc.is_posted:
            unpost_document(db, organization_id=ctx.organization_id, document_id=doc.id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    doc.deletion_mark = True
    write_audit(
        db, action="delete", entity="stock_distributions", entity_id=doc.id, organization_id=ctx.organization_id, user_id=ctx.user.id,
        old_values={"doc_number": doc.doc_number},
    )  # fmt: skip
    db.commit()
