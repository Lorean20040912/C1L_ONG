"""Pașii închiderii lunii în afară de amortizare.

- `special_purpose_income`: pe fiecare grant, cheltuielile lunii pe 716 trebuie
  acoperite de venituri pe 616 (docs/11 §2.2: Dt 537 — Kt 616 în aceeași sumă).
  Documentele generează deja venitul; pasul completează doar diferența (ex.
  cheltuieli din operațiuni manuale) și semnalează venitul mai mare decât cheltuiala.
- `account_closing`: conturile de venituri (6) și cheltuieli (7) cu sold de la 1 ianuarie la
  sfârșitul lunii se închid la contul de rezultat 33x (ToR F2b.4): venit Dt 6xx — Kt 331,
  cheltuială Dt 331 — Kt 7xx, pe grant. Contul se alege din politică (`settings.closing_account`),
  altfel 331, altfel primul cont 33x al planului.
- `checks`: totalurile = suma înregistrărilor, documentele neînregistrate ale lunii,
  conturile active cu sold creditor și pasive cu sold debitor. Nu înregistrează nimic.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
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


def closing_account(db: Session, organization_id: uuid.UUID, on_date) -> Account:
    from app.posting.rules import policy_in_force

    policy = policy_in_force(db, organization_id, on_date)
    wanted = ((policy.settings or {}).get("closing_account") if policy else None) or "331"
    base = select(Account).where(Account.organization_id == organization_id, Account.is_group.is_not(True))
    account = db.scalar(base.where(Account.code == wanted))
    if account is None:
        account = db.scalar(base.where(Account.code.like("33%")).order_by(Account.code).limit(1))
    if account is None:
        raise PostingError(f"Contul de rezultat {wanted} (33x) lipsește din planul de conturi")
    return account


def closing_plan(
    db: Session, organization_id: uuid.UUID, year: int, month: int, exclude_document: uuid.UUID | None
) -> StepResult:
    """Închiderea conturilor 6/7 (docs/11, ToR F2b.4): soldul anului până la sfârșitul lunii → 33x."""
    _, end = month_bounds(year, month)
    year_start = date(year, 1, 1)
    result = StepResult()
    try:
        target = closing_account(db, organization_id, end)
    except PostingError as exc:
        result.errors.append(str(exc))
        return result

    def side(account_column, sign):
        query = (
            select(account_column.label("account_id"), EntryLine.grant_id, (sign * EntryLine.amount).label("amount"))
            .where(
                EntryLine.organization_id == organization_id,
                EntryLine.entry_date.between(year_start, end),
            )
        )
        return query.where(EntryLine.document_id != exclude_document) if exclude_document else query

    union = side(EntryLine.debit_account_id, 1).union_all(side(EntryLine.credit_account_id, -1)).subquery()
    rows = db.execute(
        select(Account, union.c.grant_id, func.sum(union.c.amount))
        .join(Account, Account.id == union.c.account_id)
        .where(Account.organization_id == organization_id, Account.code.like("6%") | Account.code.like("7%"))
        .group_by(Account.id, union.c.grant_id)
        .order_by(Account.code)
    ).all()
    grants = {g.id: g for g in db.scalars(select(Grant).where(Grant.organization_id == organization_id))}
    for account, grant_id, net in rows:
        if not net:
            continue
        # sold creditor (venit) → Dt cont — Kt 33x; sold debitor (cheltuială) → Dt 33x — Kt cont
        income = net < 0
        amount = abs(net)
        operation = "close_income" if income else "close_expense"
        grant = grants.get(grant_id)
        try:
            generated = build_lines(
                db,
                organization_id=organization_id,
                document_type="month_close.account_closing",
                doc_date=end,
                operations=[
                    OperationInput(
                        operation=operation,
                        amount=amount,
                        grant_id=grant_id,
                        debit_account_id=account.id if income else target.id,
                        credit_account_id=target.id if income else account.id,
                        description=f"Închiderea contului {account.code}",
                    )
                ],
            )[0]
        except PostingError as exc:
            result.errors.append(f"{account.code}: {exc}")
            continue
        result.lines.append(generated)
        result.rows.append(
            StepRow(
                label=f"{account.code} {account.name}" + (f" — {grant.code}" if grant else ""),
                amount=amount,
                debit_account=account.code if income else target.code,
                credit_account=target.code if income else account.code,
                note=generated.rule.source_ref,
            )
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
