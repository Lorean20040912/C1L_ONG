"""Pașii închiderii lunii în afară de amortizare.

- `special_purpose_income`: pe fiecare grant, cheltuielile lunii pe 716 trebuie
  acoperite de venituri pe 616 (docs/11 §2.2: Dt 537 — Kt 616 în aceeași sumă).
  Documentele generează deja venitul; pasul completează doar diferența (ex.
  cheltuieli din operațiuni manuale) și semnalează venitul mai mare decât cheltuiala.
- `checks`: totalurile = suma înregistrărilor, documentele neînregistrate ale lunii,
  conturile active cu sold creditor și pasive cu sold debitor. Nu înregistrează nimic.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.catalogs.models import Account
from app.core.enums import AccountKind
from app.documents.models import Document
from app.grants.models import Grant
from app.month_close.depreciation import month_bounds
from app.posting.engine import PostingError, turnover_differences
from app.posting.models import AccountTurnover, EntryLine
from app.posting.rules import GeneratedLine, OperationInput, build_lines

# conturile mijloacelor cu destinație specială (docs/11 §1)
SPECIAL_EXPENSE, SPECIAL_INCOME = "716", "616"


@dataclass
class StepRow:
    label: str
    amount: Decimal = Decimal(0)
    debit_account: str | None = None
    credit_account: str | None = None
    note: str | None = None


@dataclass
class StepResult:
    rows: list[StepRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lines: list[GeneratedLine] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((r.amount for r in self.rows), Decimal(0))


def income_plan(
    db: Session, organization_id: uuid.UUID, year: int, month: int, exclude_document: uuid.UUID | None
) -> StepResult:
    start, end = month_bounds(year, month)
    debit, credit = aliased(Account), aliased(Account)
    amount_716 = func.sum(case((debit.code == SPECIAL_EXPENSE, EntryLine.amount), else_=0))
    amount_616 = func.sum(case((credit.code == SPECIAL_INCOME, EntryLine.amount), else_=0))
    query = (
        select(Grant, amount_716, amount_616)
        .join(EntryLine, EntryLine.grant_id == Grant.id)
        .join(debit, debit.id == EntryLine.debit_account_id)
        .join(credit, credit.id == EntryLine.credit_account_id)
        .where(
            EntryLine.organization_id == organization_id,
            EntryLine.entry_date.between(start, end),
            (debit.code == SPECIAL_EXPENSE) | (credit.code == SPECIAL_INCOME),
        )
        .group_by(Grant.id)
        .order_by(Grant.code)
    )
    if exclude_document is not None:
        query = query.where(EntryLine.document_id != exclude_document)
    result = StepResult()
    for grant, expense, income in db.execute(query).all():
        gap = (expense or Decimal(0)) - (income or Decimal(0))
        label = f"{grant.code} {grant.title}: cheltuieli 716 {expense}, venituri 616 {income}"
        if gap < 0:
            result.rows.append(StepRow(label=label, note=f"venitul depășește cheltuiala cu {-gap} — de verificat"))
            continue
        if gap == 0:
            continue
        try:
            generated = build_lines(
                db,
                organization_id=organization_id,
                document_type="month_close.income",
                doc_date=end,
                operations=[
                    OperationInput(
                        operation="income_recognition",
                        amount=gap,
                        grant_id=grant.id,
                        description=f"Venituri din mijloace cu destinație specială {grant.code}",
                    )
                ],
            )[0]
        except PostingError as exc:
            result.errors.append(f"{grant.code}: {exc}")
            continue
        result.lines.append(generated)
        result.rows.append(
            StepRow(label=label, amount=gap, debit_account="537", credit_account="616", note=generated.rule.source_ref)
        )
    return result


def checks(
    db: Session, organization_id: uuid.UUID, year: int, month: int, own_documents: set[uuid.UUID] | None = None
) -> StepResult:
    """`own_documents` = documentele închiderii înseși (nu sunt „documente uitate”)."""
    start, end = month_bounds(year, month)
    result = StepResult()
    for diff in turnover_differences(db, organization_id):
        result.errors.append(f"Totalurile nu corespund înregistrărilor: cont {diff[0]}, luna {diff[1]:%m.%Y}")
    query = select(Document.doc_number, Document.doc_date).where(
        Document.organization_id == organization_id,
        Document.doc_date.between(start, end),
        Document.is_posted.is_not(True),
        Document.deletion_mark.is_not(True),
    )
    if own_documents:
        query = query.where(Document.id.not_in(own_documents))
    unposted = db.execute(query).all()
    for number, doc_date in unposted:
        result.errors.append(f"Document neînregistrat: nr. {number or '—'} din {doc_date:%d.%m.%Y}")
    balance = func.sum(AccountTurnover.debit - AccountTurnover.credit)
    for code, name, kind, value in db.execute(
        select(Account.code, Account.name, Account.account_kind, balance)
        .join(AccountTurnover, AccountTurnover.account_id == Account.id)
        .where(Account.organization_id == organization_id, AccountTurnover.period <= start)
        .group_by(Account.id)
        .order_by(Account.code)
    ).all():
        if (kind == AccountKind.active and value < 0) or (kind == AccountKind.passive and value > 0):
            side = "creditor" if value < 0 else "debitor"
            result.errors.append(f"Contul {code} {name} ({kind.value}) are sold {side} {abs(value)} la {end:%d.%m.%Y}")
    if not result.errors:
        result.rows.append(StepRow(label="Toate verificările au trecut"))
    return result
