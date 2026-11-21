"""Execuția bugetului: planificat / cheltuit / rest pe linii de buget (ToR F6.2).

„Cheltuit” = suma înregistrărilor care poartă linia de buget. Regulile „oglindă”
(537/616, 3411, 535) nu poartă linia (migrarea 0004), deci fiecare cheltuială se
numără o singură dată, indiferent dacă e serviciu, stoc sau mijloc fix.

Depășirea nu blochează înregistrarea: contabilul primește avertismentul, iar
suma peste buget rămâne vizibilă în execuție (docs/11 §2.8: tot ce depășește
bugetul se adaugă la venitul impozabil în ONG17).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.grants.models import BudgetLine, Grant
from app.posting.models import EntryLine


@dataclass
class LineExecution:
    grant_id: uuid.UUID
    grant_code: str
    budget_line_id: uuid.UUID
    code: str
    name: str
    planned: Decimal
    spent: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.planned - self.spent

    @property
    def over(self) -> Decimal:
        return max(Decimal(0), self.spent - self.planned)


@dataclass
class BudgetWarning:
    budget_line_id: uuid.UUID
    label: str
    planned: Decimal
    spent: Decimal
    over: Decimal

    @property
    def message(self) -> str:
        return (
            f"Linia de buget {self.label}: cheltuit {self.spent} din {self.planned} planificat, "
            f"depășire {self.over} — suma peste buget nu e deductibilă (ONG17)"
        )


def _spent(
    db: Session,
    organization_id: uuid.UUID,
    line_ids: list[uuid.UUID],
    date_to: date | None = None,
    exclude_document: uuid.UUID | None = None,
) -> dict[uuid.UUID, Decimal]:
    if not line_ids:
        return {}
    query = select(EntryLine.budget_line_id, func.sum(EntryLine.amount)).where(
        EntryLine.organization_id == organization_id, EntryLine.budget_line_id.in_(line_ids)
    )
    if date_to is not None:
        query = query.where(EntryLine.entry_date <= date_to)
    if exclude_document is not None:
        query = query.where(EntryLine.document_id != exclude_document)
    return dict(db.execute(query.group_by(EntryLine.budget_line_id)).all())


def execution(
    db: Session, organization_id: uuid.UUID, grant_id: uuid.UUID | None = None, date_to: date | None = None
) -> list[LineExecution]:
    query = (
        select(BudgetLine, Grant.code)
        .join(Grant, Grant.id == BudgetLine.grant_id)
        .where(Grant.organization_id == organization_id)
    )
    if grant_id is not None:
        query = query.where(Grant.id == grant_id)
    rows = db.execute(query.order_by(Grant.code, BudgetLine.code)).all()
    spent = _spent(db, organization_id, [line.id for line, _ in rows], date_to)
    return [
        LineExecution(
            grant_id=line.grant_id,
            grant_code=grant_code,
            budget_line_id=line.id,
            code=line.code,
            name=line.name,
            planned=line.planned_amount,
            spent=spent.get(line.id, Decimal(0)),
        )
        for line, grant_code in rows
    ]


def check_amounts(
    db: Session,
    organization_id: uuid.UUID,
    amounts: dict[uuid.UUID, Decimal],
    exclude_document: uuid.UUID | None = None,
) -> list[BudgetWarning]:
    """Avertismentele pentru liniile de buget dacă li se adaugă sumele date
    (fără înregistrările documentului exclus — la reînregistrare)."""
    amounts = {k: v for k, v in amounts.items() if k is not None}
    if not amounts:
        return []
    lines = db.execute(
        select(BudgetLine, Grant.code)
        .join(Grant, Grant.id == BudgetLine.grant_id)
        .where(BudgetLine.id.in_(amounts), Grant.organization_id == organization_id)
    ).all()
    spent = _spent(db, organization_id, list(amounts), exclude_document=exclude_document)
    warnings = []
    for line, grant_code in sorted(lines, key=lambda r: (r[1], r[0].code)):
        total = spent.get(line.id, Decimal(0)) + amounts[line.id]
        if total > line.planned_amount:
            warnings.append(
                BudgetWarning(
                    budget_line_id=line.id,
                    label=f"{grant_code} / {line.code} {line.name}",
                    planned=line.planned_amount,
                    spent=total,
                    over=total - line.planned_amount,
                )
            )
    return warnings


def check_document(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> list[BudgetWarning]:
    """Situația liniilor de buget atinse de înregistrările documentului (după înregistrare)."""
    amounts: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for line_id, amount in db.execute(
        select(EntryLine.budget_line_id, EntryLine.amount).where(
            EntryLine.organization_id == organization_id,
            EntryLine.document_id == document_id,
            EntryLine.budget_line_id.is_not(None),
        )
    ):
        amounts[line_id] += amount
    return check_amounts(db, organization_id, dict(amounts), exclude_document=document_id)
