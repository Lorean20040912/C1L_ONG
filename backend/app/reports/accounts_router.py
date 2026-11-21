"""Fișa contului și analiza contului (ToR F1.6), lângă balanța de verificare.

Contul include subconturile lui (codul „234” cuprinde „234.4”). Soldul inițial se
calculează din înregistrările dinaintea perioadei; filtrul pe contrapartidă
folosește analitica rândurilor (`entry_line_analytics`) de pe partea contului.
"""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import SubcontoType
from app.documents.models import Document
from app.grants.models import Grant
from app.posting.models import EntryLine, EntryLineAnalytics
from app.regulated.export import table_xlsx

router = APIRouter(prefix="/organizations/{organization_id}/reports", tags=["rapoarte"])


class CardRow(BaseModel):
    entry_line_id: int
    entry_date: date
    document_id: uuid.UUID
    doc_number: str | None
    doc_type: str | None
    description: str | None
    account: str
    corresponding_account: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    grant_code: str | None


class AccountCard(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    date_from: date
    date_to: date
    opening: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing: Decimal
    rows: list[CardRow]


class AnalysisRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    debit: Decimal
    credit: Decimal


class AccountAnalysis(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    date_from: date
    date_to: date
    opening: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing: Decimal
    rows: list[AnalysisRow]


def _account(db: Session, ctx: OrgContext, account_id: uuid.UUID) -> Account:
    acc = db.scalar(select(Account).where(Account.id == account_id, Account.organization_id == ctx.organization_id))
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contul nu a fost găsit")
    return acc


def _subtree(db: Session, ctx: OrgContext, acc: Account) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(Account.id).where(
                Account.organization_id == ctx.organization_id,
                or_(Account.code == acc.code, Account.code.startswith(acc.code + ".")),
            )
        )
    )


def _filters(ctx: OrgContext, db: Session, grant_id, counterparty_id, ids: set[uuid.UUID]):
    conds = [EntryLine.organization_id == ctx.organization_id]
    if grant_id is not None:
        if not db.scalar(select(Grant.id).where(Grant.id == grant_id, Grant.organization_id == ctx.organization_id)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Grantul nu a fost găsit")
        conds.append(EntryLine.grant_id == grant_id)
    side_counterparty = None
    if counterparty_id is not None:
        if not db.scalar(
            select(Counterparty.id).where(
                Counterparty.id == counterparty_id, Counterparty.organization_id == ctx.organization_id
            )
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contrapartida nu a fost găsită")

        def side_counterparty(side: str):
            return exists().where(
                EntryLineAnalytics.entry_line_id == EntryLine.id,
                EntryLineAnalytics.entry_date == EntryLine.entry_date,
                EntryLineAnalytics.side == side,
                EntryLineAnalytics.subconto_type == SubcontoType.counterparty,
                EntryLineAnalytics.ref_id == counterparty_id,
            )

    debit_side = EntryLine.debit_account_id.in_(ids)
    credit_side = EntryLine.credit_account_id.in_(ids)
    if side_counterparty is not None:
        debit_side = and_(debit_side, side_counterparty("D"))
        credit_side = and_(credit_side, side_counterparty("K"))
    return conds, debit_side, credit_side


def _check_period(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sfârșitul perioadei este înaintea începutului")


def _lines(db, conds, debit_side, credit_side, *extra):
    """Rândurile cu cel puțin o parte potrivită; ultimele două coloane spun care parte
    (D / K) e a contului — și, cu filtrul pe contrapartidă, care parte are contrapartida."""
    debit, credit = aliased(Account), aliased(Account)
    return db.execute(
        select(
            EntryLine, debit, credit, Document.doc_number, Document.type, Grant.code,
            debit_side.label("on_debit"), credit_side.label("on_credit"),
        )  # fmt: skip
        .join(debit, debit.id == EntryLine.debit_account_id)
        .join(credit, credit.id == EntryLine.credit_account_id)
        .join(Document, Document.id == EntryLine.document_id)
        .outerjoin(Grant, Grant.id == EntryLine.grant_id)
        .where(*conds, or_(debit_side, credit_side), *extra)
        .order_by(EntryLine.entry_date, EntryLine.id)
    ).all()


def _opening(db, conds, debit_side, credit_side, ids, date_from) -> Decimal:
    total = Decimal(0)
    for entry, *_, on_debit, on_credit in _lines(db, conds, debit_side, credit_side, EntryLine.entry_date < date_from):
        if on_debit:
            total += entry.amount
        if on_credit:
            total -= entry.amount
    return total


def _card(db, ctx, account_id, date_from, date_to, grant_id, counterparty_id) -> AccountCard:
    _check_period(date_from, date_to)
    acc = _account(db, ctx, account_id)
    ids = _subtree(db, ctx, acc)
    conds, debit_side, credit_side = _filters(ctx, db, grant_id, counterparty_id, ids)
    opening = _opening(db, conds, debit_side, credit_side, ids, date_from)
    balance, rows, dt_total, kt_total = opening, [], Decimal(0), Decimal(0)
    in_period = EntryLine.entry_date.between(date_from, date_to)
    for entry, debit, credit, number, doc_type, grant_code, on_debit, on_credit in _lines(
        db, conds, debit_side, credit_side, in_period
    ):
        # un rând între două subconturi ale aceluiași cont apare pe ambele părți
        for side, own, other, matched in (("D", debit, credit, on_debit), ("K", credit, debit, on_credit)):
            if not matched:
                continue
            dt = entry.amount if side == "D" else Decimal(0)
            kt = entry.amount if side == "K" else Decimal(0)
            balance += dt - kt
            dt_total += dt
            kt_total += kt
            rows.append(
                CardRow(
                    entry_line_id=entry.id, entry_date=entry.entry_date, document_id=entry.document_id,
                    doc_number=number, doc_type=doc_type.value if doc_type else None, description=entry.description,
                    account=own.code, corresponding_account=other.code, debit=dt, credit=kt, balance=balance,
                    grant_code=grant_code,
                )  # fmt: skip
            )
    return AccountCard(
        account_id=acc.id, code=acc.code, name=acc.name, date_from=date_from, date_to=date_to, opening=opening,
        turnover_debit=dt_total, turnover_credit=kt_total, closing=balance, rows=rows,
    )  # fmt: skip


@router.get("/account-card", response_model=AccountCard)
def account_card(
    account_id: uuid.UUID,
    date_from: date,
    date_to: date,
    grant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AccountCard:
    """Fișa contului: sold inițial, fiecare înregistrare cu contul corespondent și soldul curent."""
    return _card(db, ctx, account_id, date_from, date_to, grant_id, counterparty_id)


@router.get("/account-card.xlsx")
def account_card_xlsx(
    account_id: uuid.UUID,
    date_from: date,
    date_to: date,
    grant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> Response:
    card = _card(db, ctx, account_id, date_from, date_to, grant_id, counterparty_id)
    rows = [["", "Sold inițial", "", "", "", "", float(card.opening)]]
    rows += [
        [f"{r.entry_date:%d.%m.%Y}", r.doc_number or "", r.description or "", r.corresponding_account,
         float(r.debit) or None, float(r.credit) or None, float(r.balance)]  # fmt: skip
        for r in card.rows
    ]
    rows.append(["", "Total / sold final", "", "", float(card.turnover_debit), float(card.turnover_credit), float(card.closing)])
    content = table_xlsx(
        f"Fișa contului {card.code}", f"{card.name}, {date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}",
        ["Data", "Document", "Conținut", "Cont corespondent", "Debit", "Credit", "Sold"], rows,
        [12, 16, 50, 16, 14, 14, 14],
    )  # fmt: skip
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="fisa-{card.code}.xlsx"'},
    )


@router.get("/account-analysis", response_model=AccountAnalysis)
def account_analysis(
    account_id: uuid.UUID,
    date_from: date,
    date_to: date,
    grant_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AccountAnalysis:
    """Analiza contului: rulajele pe conturile corespondente (Dt — din creditul cui, Kt — în debitul cui)."""
    _check_period(date_from, date_to)
    acc = _account(db, ctx, account_id)
    ids = _subtree(db, ctx, acc)
    conds, debit_side, credit_side = _filters(ctx, db, grant_id, counterparty_id, ids)
    opening = _opening(db, conds, debit_side, credit_side, ids, date_from)
    by_account: dict[uuid.UUID, list] = defaultdict(lambda: [None, Decimal(0), Decimal(0)])
    in_period = EntryLine.entry_date.between(date_from, date_to)
    for entry, debit, credit, *_, on_debit, on_credit in _lines(db, conds, debit_side, credit_side, in_period):
        if debit.id in ids and credit.id in ids:
            continue  # mișcare între subconturile aceluiași cont
        if on_debit:
            row = by_account[credit.id]
            row[0] = credit
            row[1] += entry.amount
        if on_credit:
            row = by_account[debit.id]
            row[0] = debit
            row[2] += entry.amount
    rows = sorted(
        (AnalysisRow(account_id=a.id, code=a.code, name=a.name, debit=dt, credit=kt) for a, dt, kt in by_account.values()),
        key=lambda r: r.code,
    )
    dt_total = sum((r.debit for r in rows), Decimal(0))
    kt_total = sum((r.credit for r in rows), Decimal(0))
    return AccountAnalysis(
        account_id=acc.id, code=acc.code, name=acc.name, date_from=date_from, date_to=date_to, opening=opening,
        turnover_debit=dt_total, turnover_credit=kt_total, closing=opening + dt_total - kt_total, rows=rows,
    )  # fmt: skip
