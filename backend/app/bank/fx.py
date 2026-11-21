"""Pasul „Diferențe de curs valutar” al închiderii lunii (docs/11 §2.5).

Soldurile conturilor monetare în valută (`accounts.is_currency`: 243, 234.4/235, 521 în valută...)
se reevaluează la cursul BNM din ultima zi a lunii:

    diferența = sold în valută × curs − sold în MDL (pe cont, grant și valută)

- diferență pozitivă (contul crește în Dt): Dt cont — Kt 537 pe mijloacele cu destinație specială,
  Kt 622 în rest;
- negativă: Dt 537 — Kt cont pe mijloacele cu destinație specială, Dt 722 în rest.

Formulele sunt reguli `month_close.fx` (migrarea bnk_0001); contul reevaluat vine din rând.
Rândul de reevaluare are valuta, dar suma în valută 0 (soldul în valută nu se schimbă).
"""

import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bank.rates import RateError, fresh_rate
from app.catalogs.models import Account
from app.documents.posting import BASE_CURRENCY, funding_of
from app.grants.models import Grant
from app.month_close.depreciation import month_bounds
from app.month_close.steps import StepResult, StepRow
from app.posting.engine import PostingError
from app.posting.models import EntryLine
from app.posting.rules import OperationInput, build_lines

CENT = Decimal("0.01")


def _balances(db: Session, organization_id: uuid.UUID, end, exclude_document: uuid.UUID | None) -> dict:
    """(cont, grant, valută) → [sold MDL, sold valută] din rândurile cu valută până la `end`."""
    balances: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for side, sign in ((EntryLine.debit_account_id, 1), (EntryLine.credit_account_id, -1)):
        query = (
            select(side, EntryLine.grant_id, EntryLine.currency, EntryLine.amount, EntryLine.currency_amount)
            .join(Account, Account.id == side)
            .where(
                EntryLine.organization_id == organization_id,
                EntryLine.entry_date <= end,
                EntryLine.currency.is_not(None),
                EntryLine.currency != BASE_CURRENCY,
                Account.is_currency.is_(True),
            )
        )
        if exclude_document is not None:
            query = query.where(EntryLine.document_id != exclude_document)
        for account_id, grant_id, currency, amount, currency_amount in db.execute(query).all():
            acc = balances[(account_id, grant_id, currency)]
            acc[0] += sign * amount
            acc[1] += sign * (currency_amount or 0)
    return balances


def fx_plan(
    db: Session, organization_id: uuid.UUID, year: int, month: int, exclude_document: uuid.UUID | None
) -> StepResult:
    _, end = month_bounds(year, month)
    result = StepResult()
    balances = _balances(db, organization_id, end, exclude_document)
    if not balances:
        result.rows.append(StepRow(label="Nu există solduri în valută pe conturile monetare"))
        return result
    codes = dict(db.execute(select(Account.id, Account.code).where(Account.organization_id == organization_id)).all())
    grants = {g.id: g for g in db.scalars(select(Grant).where(Grant.organization_id == organization_id))}
    rates: dict[str, Decimal | None] = {}
    for (account_id, grant_id, currency), (mdl, cur) in sorted(
        balances.items(), key=lambda kv: (codes.get(kv[0][0], ""), str(kv[0][1]), kv[0][2])
    ):
        if currency not in rates:
            try:
                rates[currency] = fresh_rate(db, organization_id, currency, end).rate
            except RateError as exc:
                rates[currency] = None
                result.errors.append(str(exc))
        rate = rates[currency]
        if rate is None:
            continue
        diff = ((cur * rate).quantize(CENT, rounding=ROUND_HALF_UP)) - mdl
        grant = grants.get(grant_id)
        label = (
            f"{codes[account_id]} {currency}{' ' + grant.code if grant else ''}: "
            f"sold {cur} {currency} × {rate} = {(cur * rate).quantize(CENT)}, în contabilitate {mdl}"
        )
        if diff == 0:
            continue
        increase = diff > 0
        override = {"debit_account_id": account_id} if increase else {"credit_account_id": account_id}
        try:
            generated = build_lines(
                db,
                organization_id=organization_id,
                document_type="month_close.fx",
                doc_date=end,
                operations=[
                    OperationInput(
                        operation="revaluation_increase" if increase else "revaluation_decrease",
                        amount=abs(diff),
                        attributes={"funding": funding_of(grant) if grant else "unrestricted"},
                        grant_id=grant_id,
                        currency=currency,
                        currency_amount=Decimal(0),
                        description=f"Diferență de curs {currency} la {end:%d.%m.%Y} (curs {rate})",
                        **override,
                    )
                ],
            )[0]
        except PostingError as exc:
            result.errors.append(f"{codes[account_id]} {currency}: {exc}")
            continue
        result.lines.append(generated)
        dt = codes.get(generated.line.debit_account_id) or "?"
        kt = codes.get(generated.line.credit_account_id) or "?"
        result.rows.append(
            StepRow(label=label, amount=abs(diff), debit_account=dt, credit_account=kt, note=generated.rule.source_ref)
        )
    return result
