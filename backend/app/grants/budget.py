"""Execuția bugetului: planificat / cheltuit / rest pe linii de buget (ToR F6.2).

„Cheltuit” = suma înregistrărilor care poartă linia de buget. Regulile „oglindă”
(537/616, 3411, 535) nu poartă linia (migrarea 0004), deci fiecare cheltuială se
numără o singură dată, indiferent dacă e serviciu, stoc sau mijloc fix.

Versiuni de buget (docs/02 §9a): liniile cu același cod din versiuni diferite sunt
aceeași linie; cheltuiala se adună pe cod, iar planul e cel al versiunii în vigoare
la data cerută (fără dată — versiunea curentă).

Depășirea nu blochează înregistrarea: contabilul primește avertismentul, iar
suma peste buget rămâne vizibilă în execuție (docs/11 §2.8: tot ce depășește
bugetul se adaugă la venitul impozabil în ONG17).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.grants.models import BudgetLine, BudgetVersion, Grant
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
    """Cheltuit pe fiecare linie dată, însumat pe toate versiunile aceluiași cod din grant."""
    if not line_ids:
        return {}
    asked = db.execute(select(BudgetLine.id, BudgetLine.grant_id, BudgetLine.code).where(BudgetLine.id.in_(line_ids))).all()
    siblings = db.execute(
        select(BudgetLine.id, BudgetLine.grant_id, BudgetLine.code).where(
            tuple_(BudgetLine.grant_id, BudgetLine.code).in_(list({(g, c) for _, g, c in asked}))
        )
    ).all()
    query = select(EntryLine.budget_line_id, func.sum(EntryLine.amount)).where(
        EntryLine.organization_id == organization_id, EntryLine.budget_line_id.in_([i for i, _, _ in siblings])
    )
    if date_to is not None:
        query = query.where(EntryLine.entry_date <= date_to)
    if exclude_document is not None:
        query = query.where(EntryLine.document_id != exclude_document)
    by_line = dict(db.execute(query.group_by(EntryLine.budget_line_id)).all())
    by_code: dict[tuple, Decimal] = defaultdict(Decimal)
    for line_id, grant_id, code in siblings:
        by_code[(grant_id, code)] += by_line.get(line_id, Decimal(0))
    return {line_id: by_code[(grant_id, code)] for line_id, grant_id, code in asked}


def version_in_force(db: Session, grant_id: uuid.UUID, on_date: date | None) -> uuid.UUID | None:
    """Versiunea în vigoare: la o dată — ultima cu `valid_from` ≤ data (sau prima, dacă data e mai veche);
    fără dată — cea de azi (o versiune cu `valid_from` în viitor nu se aplică încă). None = grantul nu are versiuni (liniile nu sunt legate de versiune)."""
    versions = db.execute(
        select(BudgetVersion.id, BudgetVersion.valid_from, BudgetVersion.is_current)
        .where(BudgetVersion.grant_id == grant_id)
        .order_by(BudgetVersion.version)
    ).all()
    if not versions:
        return None
    on_date = on_date or date.today()
    chosen = versions[0][0]
    for version_id, valid_from, _ in versions:
        if valid_from <= on_date:
            chosen = version_id
    return chosen


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
    in_force: dict[uuid.UUID, uuid.UUID | None] = {}
    shown = []
    for line, grant_code in rows:
        if line.grant_id not in in_force:
            in_force[line.grant_id] = version_in_force(db, line.grant_id, date_to)
        if line.budget_version_id == in_force[line.grant_id]:
            shown.append((line, grant_code))
    spent = _spent(db, organization_id, [line.id for line, _ in shown], date_to)
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
        for line, grant_code in shown
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
