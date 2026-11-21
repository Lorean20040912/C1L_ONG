"""Amortizarea lunară a mijloacelor fixe (ToR F2b.4–F2b.5), pas al închiderii lunii.

- metoda liniară: (valoarea inițială − valoarea reziduală) / durata în luni,
  rotunjită la bani; în ultima lună se ia restul, ca suma totală să fie exactă;
- se amortizează fișele „în funcțiune” cu începutul amortizării ≤ luna calculată;
- amortizarea acumulată se citește din înregistrări: rândurile cu analitica
  `fixed_asset` = fișa, pe partea K (contul amortizării);
- formula vine din `posting_rules` (month_close.depreciation / depreciation):
  pentru MF din grant Dt 3411 — Kt 124 (amortizarea diminuează fondul, docs/11
  §2.4); pentru celelalte surse contabilul-șef adaugă corecția, iar contul de
  cheltuieli al fișei (`expense_account_id`) înlocuiește contul din formulă.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.enums import SubcontoType
from app.documents.posting import funding_of
from app.fixed_assets.models import FixedAsset
from app.grants.models import Grant
from app.posting.engine import AnalyticsInput, PostingError
from app.posting.models import EntryLine, EntryLineAnalytics
from app.posting.rules import GeneratedLine, OperationInput, build_lines

CENT = Decimal("0.01")
DOCUMENT_TYPE = "month_close.depreciation"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:
        raise PostingError("Luna trebuie să fie între 1 și 12")
    start = date(year, month, 1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def _months_between(first: date, current: date) -> int:
    """Câte luni de amortizare au trecut de la `first` până la `current` inclusiv."""
    return (current.year - first.year) * 12 + current.month - first.month + 1


def accumulated(
    db: Session, organization_id: uuid.UUID, asset_ids: list[uuid.UUID], exclude_document: uuid.UUID | None = None
) -> dict[uuid.UUID, Decimal]:
    if not asset_ids:
        return {}
    query = (
        select(EntryLineAnalytics.ref_id, func.sum(EntryLine.amount))
        .join(
            EntryLine,
            and_(
                EntryLine.id == EntryLineAnalytics.entry_line_id, EntryLine.entry_date == EntryLineAnalytics.entry_date
            ),
        )
        .where(
            EntryLine.organization_id == organization_id,
            EntryLineAnalytics.subconto_type == SubcontoType.fixed_asset,
            EntryLineAnalytics.side == "K",
            EntryLineAnalytics.ref_id.in_(asset_ids),
        )
        .group_by(EntryLineAnalytics.ref_id)
    )
    if exclude_document is not None:
        query = query.where(EntryLine.document_id != exclude_document)
    return dict(db.execute(query).all())


@dataclass
class DepreciationRow:
    asset: FixedAsset
    amount: Decimal = Decimal(0)
    accumulated_before: Decimal = Decimal(0)
    generated: GeneratedLine | None = None
    error: str | None = None


@dataclass
class DepreciationPlan:
    year: int
    month: int
    entry_date: date
    rows: list[DepreciationRow] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [f"{r.asset.inventory_no} {r.asset.name}: {r.error}" for r in self.rows if r.error]

    @property
    def lines(self) -> list[GeneratedLine]:
        return [r.generated for r in self.rows if r.generated]

    @property
    def total(self) -> Decimal:
        return sum((r.amount for r in self.rows if r.generated), Decimal(0))


def plan(
    db: Session, organization_id: uuid.UUID, year: int, month: int, exclude_document: uuid.UUID | None = None
) -> DepreciationPlan:
    """Calculează amortizarea lunii fără a înregistra nimic (previzualizarea pasului)."""
    start, end = month_bounds(year, month)
    assets = db.scalars(
        select(FixedAsset)
        .where(
            FixedAsset.organization_id == organization_id,
            FixedAsset.status == "in_use",
            FixedAsset.depreciation_start.is_not(None),
            FixedAsset.depreciation_start <= start,
        )
        .order_by(FixedAsset.inventory_no)
    ).all()
    done = accumulated(db, organization_id, [a.id for a in assets], exclude_document)
    grants = {
        g.id: g for g in db.scalars(select(Grant).where(Grant.id.in_({a.grant_id for a in assets if a.grant_id})))
    }
    result = DepreciationPlan(year=year, month=month, entry_date=end)
    for asset in assets:
        row = DepreciationRow(asset=asset, accumulated_before=done.get(asset.id, Decimal(0)))
        base = asset.initial_cost - (asset.residual_value or Decimal(0))
        remaining = base - row.accumulated_before
        if remaining <= 0:
            continue  # amortizat integral
        if not asset.useful_life_months:
            row.error = "lipsește durata de utilizare (luni)"
            result.rows.append(row)
            continue
        monthly = (base / asset.useful_life_months).quantize(CENT, rounding=ROUND_HALF_UP)
        last_month = _months_between(asset.depreciation_start, start) >= asset.useful_life_months
        row.amount = remaining if last_month else min(monthly, remaining)

        grant = grants.get(asset.grant_id)
        funding = funding_of(grant) if grant else None
        attributes = {"funding": funding} if funding else {}
        try:
            row.generated = build_lines(
                db,
                organization_id=organization_id,
                document_type=DOCUMENT_TYPE,
                doc_date=end,
                operations=[
                    OperationInput(
                        operation="depreciation",
                        amount=row.amount,
                        attributes=attributes,
                        grant_id=asset.grant_id,
                        department_id=asset.department_id,
                        description=f"Amortizare {asset.inventory_no} {asset.name}",
                        analytics=[AnalyticsInput(side="K", subconto_type=SubcontoType.fixed_asset, ref_id=asset.id)],
                        # MF din grant: amortizarea diminuează fondul 3411, nu merge pe cheltuieli
                        debit_account_id=asset.expense_account_id if funding != "special_purpose" else None,
                        credit_account_id=asset.depreciation_account_id,
                    )
                ],
            )[0]
        except PostingError as exc:
            row.error = str(exc)
        result.rows.append(row)
    return result
