"""Pasul „Repartizarea cheltuielilor pe granturi” din închiderea lunii (ToR F2b.4, docs/11 §2.8).

Costurile comune (chirie, transport, salarii administrative) se înregistrează fără grant pe un cont de
cheltuieli ales (ex. 717). Pasul le repartizează pe liniile de buget după coeficienți documentați
(pontaj, %) cu Dt 716 — Kt <contul ales>, pe proiect și linie; veniturile 537/616 le completează pasul
următor („venituri din mijloace cu destinație specială”). Repartizarea se păstrează în `allocations`.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.catalogs.models import Account
from app.documents.models import Document
from app.grants.models import Allocation, BudgetLine, Grant
from app.month_close.depreciation import month_bounds
from app.month_close.steps import StepResult, StepRow
from app.posting.engine import PostingError
from app.posting.models import EntryLine
from app.posting.rules import OperationInput, build_lines

CENT = Decimal("0.01")


class AllocationLineIn(BaseModel):
    budget_line_id: uuid.UUID
    coefficient: Decimal = Field(gt=0, max_digits=12, decimal_places=4)


class AllocationParams(BaseModel):
    source_account_id: uuid.UUID
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)  # implicit: tot ce s-a adunat
    lines: list[AllocationLineIn] = Field(min_length=1)


def pool(
    db: Session, organization_id: uuid.UUID, year: int, month: int, account_id: uuid.UUID, exclude: uuid.UUID | None
) -> Decimal:
    """Costurile comune ale lunii: debitul contului ales fără proiect."""
    start, end = month_bounds(year, month)
    query = select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
        EntryLine.organization_id == organization_id,
        EntryLine.debit_account_id == account_id,
        EntryLine.grant_id.is_(None),
        EntryLine.entry_date.between(start, end),
    )
    if exclude is not None:
        query = query.where(EntryLine.document_id != exclude)
    return db.scalar(query)


def split(amount: Decimal, coefficients: list[Decimal]) -> list[Decimal]:
    """Împarte suma proporțional; diferența de rotunjire merge pe ultima linie (suma rămâne exactă)."""
    total = sum(coefficients, Decimal(0))
    parts = [(amount * c / total).quantize(CENT, rounding=ROUND_HALF_UP) for c in coefficients]
    parts[-1] += amount - sum(parts, Decimal(0))
    return parts


def plan(
    db: Session, organization_id: uuid.UUID, year: int, month: int, params: dict | None, exclude: uuid.UUID | None
) -> tuple[StepResult, list[tuple[BudgetLine, Decimal]]]:
    result = StepResult()
    if not params:
        result.errors.append("Alegeți contul cheltuielilor comune și liniile de buget cu coeficienți")
        return result, []
    p = AllocationParams.model_validate(params)
    account = db.scalar(
        select(Account).where(Account.id == p.source_account_id, Account.organization_id == organization_id)
    )
    if account is None:
        raise PostingError("Contul cheltuielilor comune nu aparține organizației")
    ids = [ln.budget_line_id for ln in p.lines]
    if len(set(ids)) != len(ids):
        raise PostingError("O linie de buget apare de două ori")
    rows = {
        line.id: (line, grant)
        for line, grant in db.execute(
            select(BudgetLine, Grant)
            .join(Grant, Grant.id == BudgetLine.grant_id)
            .where(BudgetLine.id.in_(ids), Grant.organization_id == organization_id)
        )
    }
    if len(rows) != len(ids):
        raise PostingError("O linie de buget nu aparține organizației")
    closed = [g.code for _, g in rows.values() if g.is_closed]
    if closed:
        raise PostingError(f"Grantul {closed[0]} este închis")
    available = pool(db, organization_id, year, month, account.id, exclude)
    amount = p.amount or available
    if amount <= 0:
        raise PostingError(f"Contul {account.code} nu are cheltuieli comune în luna aleasă")
    if amount > available:
        raise PostingError(f"Suma de repartizat ({amount}) depășește cheltuielile comune ale lunii ({available})")
    _, end = month_bounds(year, month)
    shares = split(amount, [ln.coefficient for ln in p.lines])
    allocations = []
    for line_in, share in zip(p.lines, shares):
        line, grant = rows[line_in.budget_line_id]
        if share <= 0:
            continue
        generated = build_lines(
            db,
            organization_id=organization_id,
            document_type="month_close.allocation",
            doc_date=end,
            operations=[
                OperationInput(
                    operation="cost_allocation",
                    amount=share,
                    attributes={"funding": "special_purpose"},
                    grant_id=grant.id,
                    budget_line_id=line.id,
                    credit_account_id=account.id,
                    description=f"Repartizare cheltuieli comune {account.code} pe {grant.code} / {line.code}",
                )
            ],
        )[0]
        result.lines.append(generated)
        result.rows.append(
            StepRow(
                label=f"{grant.code} / {line.code} {line.name} (coeficient {line_in.coefficient})",
                amount=share,
                debit_account="716",
                credit_account=account.code,
                note=generated.rule.source_ref,
            )
        )
        allocations.append((line, share))
    return result, allocations


def store(db: Session, document_id: uuid.UUID, allocations: list[tuple[BudgetLine, Decimal]]) -> None:
    clear(db, document_id)
    for line, share in allocations:
        db.add(Allocation(document_id=document_id, budget_line_id=line.id, amount=share, amount_mdl=share))
    db.flush()


def clear(db: Session, document_id: uuid.UUID) -> None:
    db.execute(delete(Allocation).where(Allocation.document_id == document_id))
