"""Partida simplă (ÎI, GȚ): registrul-jurnal de venituri și cheltuieli (docs/13 §4)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import AccountingMethod
from app.documents.models import Document
from app.simple_ledger.models import SimpleLedgerEntry
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}/simple-ledger", tags=["partidă simplă"])


class EntryIn(BaseModel):
    document_id: uuid.UUID
    entry_date: date
    kind: Literal["income", "expense"]
    category: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    is_deductible: bool = True
    description: str | None = None


class EntryOut(EntryIn):
    id: int


class Journal(BaseModel):
    entries: list[EntryOut]
    income: Decimal
    expense: Decimal
    deductible_expense: Decimal
    result: Decimal  # venituri − cheltuieli deductibile (baza impozabilă înainte de ajustări)


def _out(e: SimpleLedgerEntry) -> EntryOut:
    return EntryOut(
        id=e.id,
        document_id=e.document_id,
        entry_date=e.entry_date,
        kind=e.kind,  # type: ignore[arg-type]
        category=e.category,
        amount=e.amount,
        is_deductible=bool(e.is_deductible),
        description=e.description,
    )


@router.get("", response_model=Journal)
def journal(
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Journal:
    q = select(SimpleLedgerEntry).where(SimpleLedgerEntry.organization_id == ctx.organization_id)
    if date_from:
        q = q.where(SimpleLedgerEntry.entry_date >= date_from)
    if date_to:
        q = q.where(SimpleLedgerEntry.entry_date <= date_to)
    rows = db.scalars(q.order_by(SimpleLedgerEntry.entry_date, SimpleLedgerEntry.id)).all()
    income = sum((e.amount for e in rows if e.kind == "income"), Decimal("0"))
    expense = sum((e.amount for e in rows if e.kind == "expense"), Decimal("0"))
    deductible = sum((e.amount for e in rows if e.kind == "expense" and e.is_deductible), Decimal("0"))
    return Journal(
        entries=[_out(e) for e in rows],
        income=income,
        expense=expense,
        deductible_expense=deductible,
        result=income - deductible,
    )


@router.post("/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def add_entry(body: EntryIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> EntryOut:
    ctx.require(POSTING_ROLES)
    method = db.scalar(select(Organization.accounting_method).where(Organization.id == ctx.organization_id))
    if method != AccountingMethod.single_entry:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Organizația ține partidă dublă, nu registru-jurnal")
    doc = db.scalar(
        select(Document.id).where(Document.id == body.document_id, Document.organization_id == ctx.organization_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul nu a fost găsit")
    entry = SimpleLedgerEntry(organization_id=ctx.organization_id, **body.model_dump())
    db.add(entry)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="simple_ledger_entries",
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"id": entry.id, "kind": body.kind, "amount": str(body.amount), "date": body.entry_date.isoformat()},
    )
    db.commit()
    return _out(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    entry = db.scalar(
        select(SimpleLedgerEntry).where(
            SimpleLedgerEntry.id == entry_id, SimpleLedgerEntry.organization_id == ctx.organization_id
        )
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Înregistrarea nu a fost găsită")
    write_audit(
        db,
        action="delete",
        entity="simple_ledger_entries",
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values={"id": entry.id, "kind": entry.kind, "amount": str(entry.amount)},
    )
    db.delete(entry)
    db.commit()
