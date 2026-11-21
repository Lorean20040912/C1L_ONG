"""Motorul de înregistrare (partida dublă).

Singurul loc care scrie în `entry_lines` și `account_turnovers`. Funcțiile nu
fac commit: apelantul (endpoint-ul) confirmă tranzacția, astfel încât
înregistrările, rulajele, statutul documentului și auditul se salvează
împreună sau deloc.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, cast, delete, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.catalogs.models import Account, Department
from app.core.enums import SubcontoType
from app.documents.models import Document
from app.grants.models import CostItem, Grant
from app.posting.models import AccountingPeriod, AccountTurnover, EntryLine, EntryLineAnalytics

BASE_CURRENCY = "MDL"
CENT = Decimal("0.01")


class PostingError(Exception):
    """Documentul nu poate fi înregistrat / anulat; mesajul e pentru utilizator."""


class DocumentNotFound(PostingError):
    pass


@dataclass
class AnalyticsInput:
    side: str  # "D" sau "K"
    subconto_type: SubcontoType
    ref_id: uuid.UUID


@dataclass
class LineInput:
    debit_account_id: uuid.UUID
    credit_account_id: uuid.UUID
    amount: Decimal
    entry_date: date | None = None
    tax_amount: Decimal | None = None
    currency: str | None = None
    currency_amount: Decimal | None = None
    quantity: Decimal | None = None
    department_id: uuid.UUID | None = None
    grant_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    activity_type: str | None = None
    is_non_statutory: bool = False
    description: str | None = None
    analytics: list[AnalyticsInput] = field(default_factory=list)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _lock_document(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.organization_id == organization_id)
        .with_for_update()
    )
    if doc is None:
        raise DocumentNotFound("Documentul nu a fost găsit")
    return doc


def _ensure_periods_open(db: Session, organization_id: uuid.UUID, dates: set[date]) -> None:
    months = {(d.year, d.month) for d in dates}
    closed = db.execute(
        select(AccountingPeriod.year, AccountingPeriod.month).where(
            AccountingPeriod.organization_id == organization_id,
            AccountingPeriod.is_closed.is_(True),
            func.make_date(AccountingPeriod.year, AccountingPeriod.month, 1).in_([date(y, m, 1) for y, m in months]),
        )
    ).all()
    if closed:
        names = ", ".join(f"{m:02d}.{y}" for y, m in sorted(closed))
        raise PostingError(f"Perioada închisă: {names}")


def _ensure_owned(db: Session, model, organization_id: uuid.UUID, ids: set[uuid.UUID], label: str) -> None:
    ids.discard(None)
    if not ids:
        return
    found = set(db.scalars(select(model.id).where(model.id.in_(ids), model.organization_id == organization_id)))
    if found != ids:
        raise PostingError(f"{label} nu aparține organizației")


def _validate_accounts(db: Session, organization_id: uuid.UUID, ids: set[uuid.UUID]) -> None:
    rows = db.execute(
        select(Account.id, Account.code, Account.is_group).where(
            Account.id.in_(ids), Account.organization_id == organization_id
        )
    ).all()
    if len(rows) != len(ids):
        raise PostingError("Contul nu aparține organizației")
    groups = [code for _, code, is_group in rows if is_group]
    if groups:
        raise PostingError(f"Contul sintetic {', '.join(groups)} nu primește înregistrări directe")


def _apply_turnovers(db: Session, organization_id: uuid.UUID, lines: list[EntryLine], sign: int) -> None:
    """Adaugă (sign=1) sau scade (sign=-1) rulajele lunare ale rândurilor."""
    deltas: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0)] * 4)
    for line in lines:
        currency = line.currency or BASE_CURRENCY
        cur_amount = line.currency_amount or Decimal(0)
        period = _month_start(line.entry_date)
        debit = deltas[(line.debit_account_id, period, line.grant_id, currency)]
        debit[0] += line.amount
        debit[2] += cur_amount
        credit = deltas[(line.credit_account_id, period, line.grant_id, currency)]
        credit[1] += line.amount
        credit[3] += cur_amount

    for (account_id, period, grant_id, currency), (dt, kt, dt_cur, kt_cur) in sorted(
        deltas.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], str(kv[0][2]), kv[0][3])
    ):
        stmt = insert(AccountTurnover).values(
            organization_id=organization_id,
            account_id=account_id,
            period=period,
            grant_id=grant_id,
            currency=currency,
            debit=sign * dt,
            credit=sign * kt,
            debit_currency=sign * dt_cur,
            credit_currency=sign * kt_cur,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_account_turnovers_key",
            set_={
                "debit": AccountTurnover.debit + stmt.excluded.debit,
                "credit": AccountTurnover.credit + stmt.excluded.credit,
                "debit_currency": func.coalesce(AccountTurnover.debit_currency, 0) + stmt.excluded.debit_currency,
                "credit_currency": func.coalesce(AccountTurnover.credit_currency, 0) + stmt.excluded.credit_currency,
            },
        )
        db.execute(stmt)

    if sign < 0:
        # rulajele rămase la zero după anulare nu mai au rost
        db.execute(
            delete(AccountTurnover).where(
                AccountTurnover.organization_id == organization_id,
                AccountTurnover.debit == 0,
                AccountTurnover.credit == 0,
                func.coalesce(AccountTurnover.debit_currency, 0) == 0,
                func.coalesce(AccountTurnover.credit_currency, 0) == 0,
            )
        )


def _remove_entries(db: Session, doc: Document) -> list[EntryLine]:
    lines = list(
        db.scalars(
            select(EntryLine).where(EntryLine.organization_id == doc.organization_id, EntryLine.document_id == doc.id)
        )
    )
    if lines:
        _ensure_periods_open(db, doc.organization_id, {line.entry_date for line in lines})
        _apply_turnovers(db, doc.organization_id, lines, sign=-1)
        db.execute(
            delete(EntryLine)
            .where(EntryLine.organization_id == doc.organization_id, EntryLine.document_id == doc.id)
            .execution_options(synchronize_session=False)
        )
        for line in lines:
            db.expunge(line)
    return lines


def post_document(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    lines: list[LineInput],
    user_id: uuid.UUID | None,
) -> list[EntryLine]:
    """Înregistrează documentul. Un document deja înregistrat se reînregistrează
    (înregistrările vechi se șterg întâi, ca la „Провести” repetat în 1C)."""
    doc = _lock_document(db, organization_id, document_id)
    if doc.deletion_mark:
        raise PostingError("Documentul este marcat pentru ștergere")
    if not lines:
        raise PostingError("Documentul nu are înregistrări")

    dates: set[date] = set()
    total_debit = total_credit = Decimal(0)
    for i, line in enumerate(lines, start=1):
        amount = Decimal(line.amount)
        if amount <= 0 or amount != amount.quantize(CENT):
            raise PostingError(f"Rândul {i}: suma trebuie să fie pozitivă, cu cel mult 2 zecimale")
        entry_date = line.entry_date or doc.doc_date
        if entry_date is None:
            raise PostingError(f"Rândul {i}: lipsește data înregistrării")
        dates.add(entry_date)
        total_debit += amount
        total_credit += amount
        for a in line.analytics:
            if a.side not in ("D", "K"):
                raise PostingError(f"Rândul {i}: partea analiticii trebuie să fie D sau K")

    if total_debit != total_credit:
        raise PostingError(f"Dt ({total_debit}) ≠ Kt ({total_credit})")

    _validate_accounts(db, organization_id, {x.debit_account_id for x in lines} | {x.credit_account_id for x in lines})
    _ensure_owned(db, Grant, organization_id, {x.grant_id for x in lines}, "Grantul")
    _ensure_owned(db, CostItem, organization_id, {x.cost_item_id for x in lines}, "Articolul de cheltuieli")
    _ensure_owned(db, Department, organization_id, {x.department_id for x in lines}, "Subdiviziunea")
    _ensure_periods_open(db, organization_id, dates)

    was_posted = bool(doc.is_posted)
    _remove_entries(db, doc)

    created: list[EntryLine] = []
    for i, line in enumerate(lines, start=1):
        entry = EntryLine(
            organization_id=organization_id,
            document_id=doc.id,
            line_no=i,
            entry_date=line.entry_date or doc.doc_date,
            debit_account_id=line.debit_account_id,
            credit_account_id=line.credit_account_id,
            amount=Decimal(line.amount),
            tax_amount=line.tax_amount,
            department_id=line.department_id,
            currency=line.currency,
            currency_amount=line.currency_amount,
            quantity=line.quantity,
            grant_id=line.grant_id,
            budget_line_id=line.budget_line_id,
            cost_item_id=line.cost_item_id,
            activity_type=line.activity_type,
            is_non_statutory=line.is_non_statutory,
            description=line.description,
        )
        db.add(entry)
        created.append(entry)
    db.flush()

    for entry, line in zip(created, lines, strict=True):
        for a in line.analytics:
            db.add(
                EntryLineAnalytics(
                    entry_line_id=entry.id,
                    entry_date=entry.entry_date,
                    side=a.side,
                    subconto_type=a.subconto_type,
                    ref_id=a.ref_id,
                )
            )

    _apply_turnovers(db, organization_id, created, sign=1)

    doc.is_posted = True
    doc.version = (doc.version or 1) + 1
    write_audit(
        db,
        action="repost" if was_posted else "post",
        entity="documents",
        entity_id=doc.id,
        organization_id=organization_id,
        user_id=user_id,
        new_values={"lines": len(created), "total": str(total_debit)},
    )
    db.flush()
    return created


def unpost_document(
    db: Session, *, organization_id: uuid.UUID, document_id: uuid.UUID, user_id: uuid.UUID | None
) -> None:
    """Anulează înregistrarea: șterge înregistrările și scade rulajele."""
    doc = _lock_document(db, organization_id, document_id)
    if not doc.is_posted:
        raise PostingError("Documentul nu este înregistrat")
    removed = _remove_entries(db, doc)
    doc.is_posted = False
    doc.version = (doc.version or 1) + 1
    write_audit(
        db,
        action="unpost",
        entity="documents",
        entity_id=doc.id,
        organization_id=organization_id,
        user_id=user_id,
        old_values={"lines": len(removed)},
    )
    db.flush()


def turnover_differences(db: Session, organization_id: uuid.UUID) -> list[tuple]:
    """Compară account_turnovers cu suma reală din entry_lines.

    Întoarce rândurile (cont, lună, grant, valută, debit, credit) la care
    diferă; lista goală înseamnă totaluri corecte. Folosit de teste și de
    verificarea periodică.
    """
    period = cast(func.date_trunc("month", EntryLine.entry_date), Date)
    zero = cast(literal(0), Numeric(15, 2))
    currency = func.coalesce(EntryLine.currency, BASE_CURRENCY)
    org_lines = EntryLine.organization_id == organization_id
    sides = union_all(
        select(
            EntryLine.debit_account_id.label("account_id"),
            period.label("period"),
            EntryLine.grant_id.label("grant_id"),
            currency.label("currency"),
            EntryLine.amount.label("debit"),
            zero.label("credit"),
        ).where(org_lines),
        select(
            EntryLine.credit_account_id,
            period,
            EntryLine.grant_id,
            currency,
            zero,
            EntryLine.amount,
        ).where(org_lines),
    ).subquery()
    expected = {
        (r.account_id, r.period, r.grant_id, r.currency.strip()): (r.debit, r.credit)
        for r in db.execute(
            select(
                sides.c.account_id,
                sides.c.period,
                sides.c.grant_id,
                sides.c.currency,
                func.sum(sides.c.debit).label("debit"),
                func.sum(sides.c.credit).label("credit"),
            ).group_by(sides.c.account_id, sides.c.period, sides.c.grant_id, sides.c.currency)
        )
    }
    actual = {
        (t.account_id, t.period, t.grant_id, t.currency.strip()): (t.debit, t.credit)
        for t in db.scalars(select(AccountTurnover).where(AccountTurnover.organization_id == organization_id))
    }
    diffs = []
    for key in expected.keys() | actual.keys():
        if expected.get(key, (0, 0)) != actual.get(key, (0, 0)):
            diffs.append((*key, expected.get(key), actual.get(key)))
    return diffs
