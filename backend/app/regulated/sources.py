"""Sursele celulelor ONG17 și 5-CON: valorile calculate din contabilitate.

Fiecare sursă (ex. `ong17.income.special_purpose`, `con5:071`) are valoarea în
lei și lista contribuțiilor — înregistrările (sau depășirile de buget) din care
provine; lista servește la descifrarea celulei (ToR F6a.6).

Venitul = rulajul creditor al conturilor clasei 6 (minus cel debitor), cheltuiala
= rulajul debitor al clasei 7 (minus cel creditor); închiderea anului (conturile
de rezultat 33x) nu se numără.

Tipul activității (docs/06 §5) se stabilește pe fiecare înregistrare, în ordinea:
1. grantul din desemnarea procentuală → „mijloace nepredestinate” (docs/06: 01013
   include desemnarea), plus marcajul informativ 01014 / 01024;
2. `entry_lines.activity_type` pus de regula de înregistrare;
3. contul: 616/716 — destinație specială, 618/718 — economică, 617/717 — altele;
4. sursa de finanțare a grantului (`documents.posting.funding_of`);
5. altfel — „altele”.
"""

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.catalogs.models import Account
from app.documents.models import Document
from app.documents.posting import funding_of
from app.grants.models import BudgetLine, CostItem, Grant
from app.posting.models import EntryLine
from app.regulated.models import OrganizationStats
from app.taxes.models import TaxRate

DESIGNATION = "percentage_designation"
MEMBER_FUNDING = {"cotizatii", "cotizații", "membership_fees"}
CLOSING_PREFIXES = ("33",)  # conturile de rezultat: închiderea veniturilor și cheltuielilor la sfârșit de an
ACTIVITIES = ("special_purpose", "economic", "other")
DESIGNATION_CATEGORIES = ("public_utility", "social_charity", "administrative")
ACCOUNT_ACTIVITY = {
    "616": "special_purpose",
    "716": "special_purpose",
    "618": "economic",
    "718": "economic",
    "617": "other",
    "717": "other",
}
AMORTIZATION = {"124": "091", "113": "092"}  # amortizarea MF / activelor nemateriale → 5-CON 091 / 092


@dataclass
class Contribution:
    kind: str  # entry / budget_excess / stats / rate
    amount: Decimal
    entry_line_id: int | None = None
    entry_date: date | None = None
    document_id: uuid.UUID | None = None
    doc_number: str | None = None
    debit_account: str | None = None
    credit_account: str | None = None
    grant_code: str | None = None
    cost_item: str | None = None
    description: str | None = None
    label: str | None = None
    planned: Decimal | None = None
    spent: Decimal | None = None

    def as_json(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal | date | uuid.UUID) else v) for k, v in asdict(self).items()}


@dataclass
class SourceResult:
    values: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    details: dict[str, list[Contribution]] = field(default_factory=lambda: defaultdict(list))
    warnings: list[str] = field(default_factory=list)
    annex_1d: list[dict] = field(default_factory=list)
    has_activity: bool = False

    def add(self, source: str, c: Contribution) -> None:
        self.values[source] += c.amount
        self.details[source].append(c)

    def value(self, source: str) -> Decimal:
        return self.values.get(source, Decimal(0))


def _is(code: str, *prefixes: str) -> bool:
    return any(code == p or code.startswith(p) for p in prefixes)


@dataclass
class _Line:
    entry: EntryLine
    debit: str
    credit: str
    grant: Grant | None
    con5_article: str | None
    designation_category: str | None
    cost_item: str | None
    doc_number: str | None

    def contribution(self, amount: Decimal) -> Contribution:
        e = self.entry
        return Contribution(
            kind="entry", amount=amount, entry_line_id=e.id, entry_date=e.entry_date, document_id=e.document_id,
            doc_number=self.doc_number, debit_account=self.debit, credit_account=self.credit,
            grant_code=self.grant.code if self.grant else None, cost_item=self.cost_item, description=e.description,
        )  # fmt: skip

    @property
    def designation(self) -> bool:
        return self.grant is not None and (self.grant.funding_type or "").strip().lower() == DESIGNATION

    def activity(self, account_code: str) -> str:
        if self.designation:
            return "other"
        if self.entry.activity_type in ACTIVITIES:
            return self.entry.activity_type
        for prefix, activity in ACCOUNT_ACTIVITY.items():
            if _is(account_code, prefix):
                return activity
        if self.grant is not None:
            return {"unrestricted": "other"}.get(funding_of(self.grant), funding_of(self.grant))
        return "other"

    def income(self) -> tuple[str, Decimal] | None:
        """Contul de venituri și suma (pozitivă = venit, negativă = stornare)."""
        if _is(self.credit, "6") and not _is(self.debit, *CLOSING_PREFIXES):
            return self.credit, self.entry.amount
        if _is(self.debit, "6") and not _is(self.credit, *CLOSING_PREFIXES):
            return self.debit, -self.entry.amount
        return None

    def expense(self) -> tuple[str, Decimal] | None:
        if _is(self.debit, "7") and not _is(self.credit, *CLOSING_PREFIXES):
            return self.debit, self.entry.amount
        if _is(self.credit, "7") and not _is(self.debit, *CLOSING_PREFIXES):
            return self.credit, -self.entry.amount
        return None


def _lines(db: Session, organization_id: uuid.UUID, date_from: date, date_to: date, *extra) -> list[_Line]:
    debit, credit = aliased(Account), aliased(Account)
    line_item, budget_item = aliased(CostItem), aliased(CostItem)
    query = (
        select(
            EntryLine, debit.code, credit.code, Grant, Document.doc_number,
            func.coalesce(line_item.con5_article, budget_item.con5_article),
            func.coalesce(line_item.designation_category, budget_item.designation_category),
            func.coalesce(line_item.name, budget_item.name),
        )
        .join(debit, debit.id == EntryLine.debit_account_id)
        .join(credit, credit.id == EntryLine.credit_account_id)
        .join(Document, Document.id == EntryLine.document_id)
        .outerjoin(Grant, Grant.id == EntryLine.grant_id)
        .outerjoin(BudgetLine, BudgetLine.id == EntryLine.budget_line_id)
        .outerjoin(line_item, line_item.id == EntryLine.cost_item_id)
        .outerjoin(budget_item, budget_item.id == BudgetLine.cost_item_id)
        .where(
            EntryLine.organization_id == organization_id,
            EntryLine.entry_date.between(date_from, date_to),
            *extra,
        )
        .order_by(EntryLine.entry_date, EntryLine.id)
    )  # fmt: skip
    return [
        _Line(entry, d, k, grant, (con5 or "").strip() or None, category, item, number)
        for entry, d, k, grant, number, con5, category, item in db.execute(query).all()
    ]


def _class_filter(debit_prefixes: tuple[str, ...], credit_prefixes: tuple[str, ...]):
    debit, credit = aliased(Account), aliased(Account)
    return or_(
        EntryLine.debit_account_id.in_(
            select(debit.id).where(or_(*(debit.code.startswith(p) for p in debit_prefixes)))
        ),
        EntryLine.credit_account_id.in_(
            select(credit.id).where(or_(*(credit.code.startswith(p) for p in credit_prefixes)))
        ),
    )


# ───────────────────────────── ONG17 ─────────────────────────────


def _tax_rate(db: Session, code: str, on_date: date) -> Decimal | None:
    return db.scalar(
        select(TaxRate.value)
        .where(
            TaxRate.code == code,
            TaxRate.valid_from <= on_date,
            or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= on_date),
        )
        .order_by(TaxRate.valid_from.desc())
        .limit(1)
    )


def _non_statutory_source(activity: str, designation: bool) -> str | None:
    if designation:
        return "ong17.expense.designation.non_statutory"
    return {
        "special_purpose": "ong17.expense.special_purpose.non_statutory",
        "other": "ong17.expense.other.non_statutory",
    }.get(activity)


def _budget_spent(db: Session, organization_id: uuid.UUID, line_ids: list[uuid.UUID], up_to: date) -> dict:
    """Cheltuit pe linia de buget până la data dată, fără înregistrările marcate deja
    „contrar destinației” (ca să nu se numere de două ori în 010211)."""
    if not line_ids:
        return {}
    return dict(
        db.execute(
            select(EntryLine.budget_line_id, func.sum(EntryLine.amount))
            .where(
                EntryLine.organization_id == organization_id,
                EntryLine.budget_line_id.in_(line_ids),
                EntryLine.entry_date <= up_to,
                EntryLine.is_non_statutory.is_not(True),
            )
            .group_by(EntryLine.budget_line_id)
        ).all()
    )


def _budget_excess(db: Session, organization_id: uuid.UUID, date_from: date, date_to: date, result: SourceResult):
    """Depășirea bugetului apărută în perioadă (docs/11 §2.8): tot ce trece peste linia
    de buget nu e deductibil → 010211 (sau 010231 / 010241 după sursa de finanțare)."""
    rows = db.execute(
        select(BudgetLine, Grant)
        .join(Grant, Grant.id == BudgetLine.grant_id)
        .where(Grant.organization_id == organization_id)
        .order_by(Grant.code, BudgetLine.code)
    ).all()
    ids = [line.id for line, _ in rows]
    spent_end = _budget_spent(db, organization_id, ids, date_to)
    spent_before = _budget_spent(db, organization_id, ids, date_from - timedelta(days=1))
    for line, grant in rows:
        end = spent_end.get(line.id, Decimal(0))
        over = max(Decimal(0), end - line.planned_amount) - max(
            Decimal(0), spent_before.get(line.id, Decimal(0)) - line.planned_amount
        )
        if over <= 0:
            continue
        designation = (grant.funding_type or "").strip().lower() == DESIGNATION
        funding = funding_of(grant)
        source = _non_statutory_source("other" if funding == "unrestricted" else funding, designation)
        if source is None:  # activitatea economică nu intră în 020
            continue
        result.add(
            source,
            Contribution(
                kind="budget_excess", amount=over, grant_code=grant.code,
                label=f"{grant.code} / {line.code} {line.name}: peste buget", planned=line.planned_amount, spent=end,
            ),
        )  # fmt: skip


def ong17_sources(db: Session, organization_id: uuid.UUID, year: int) -> SourceResult:
    date_from, date_to = date(year, 1, 1), date(year, 12, 31)
    result = SourceResult()
    for ln in _lines(db, organization_id, date_from, date_to, _class_filter(("6", "7"), ("6", "7"))):
        result.has_activity = True
        if (inc := ln.income()) is not None:
            account, amount = inc
            c = ln.contribution(amount)
            result.add(f"ong17.income.{ln.activity(account)}", c)
            if ln.designation:
                result.add("ong17.income.designation", c)
        if (exp := ln.expense()) is not None:
            account, amount = exp
            activity = ln.activity(account)
            c = ln.contribution(amount)
            result.add(f"ong17.expense.{activity}", c)
            if ln.designation:
                result.add("ong17.expense.designation", c)
            if ln.entry.is_non_statutory and (source := _non_statutory_source(activity, ln.designation)):
                result.add(source, c)
    _budget_excess(db, organization_id, date_from, date_to, result)

    rate = _tax_rate(db, "INCOME_TAX_LEGAL", date_to)
    if rate is None:
        result.warnings.append("Lipsește cota INCOME_TAX_LEGAL valabilă în an (tax_rates)")
    else:
        result.add("tax_rate.INCOME_TAX_LEGAL", Contribution(kind="rate", amount=rate, label="INCOME_TAX_LEGAL"))

    result.annex_1d = annex_1d(db, organization_id, year, result)
    return result


def annex_1d(db: Session, organization_id: uuid.UUID, year: int, result: SourceResult) -> list[dict]:
    """Anexa 1D: pentru fiecare an al desemnării (granturile `percentage_designation`),
    primite, cheltuite în anul desemnării și în următorii doi, rămase de restituit."""
    grants = db.scalars(
        select(Grant).where(Grant.organization_id == organization_id, func.lower(Grant.funding_type) == DESIGNATION)
    ).all()
    rows = []
    for grant in sorted(grants, key=lambda g: (g.designation_year or g.start_date.year, g.code)):
        y = grant.designation_year or grant.start_date.year
        if not (year - 2 <= y <= year):
            continue
        last = min(year, y + 2)
        received = Decimal(0)
        spent = {offset: dict.fromkeys((*DESIGNATION_CATEGORIES, "unclassified"), Decimal(0)) for offset in range(3)}
        cash = _class_filter(("24", "7"), ("6", "7"))
        for ln in _lines(db, organization_id, date(y, 1, 1), date(last, 12, 31), cash, EntryLine.grant_id == grant.id):
            if _is(ln.debit, "24"):
                received += ln.entry.amount
            if (exp := ln.expense()) is not None:
                category = ln.designation_category if ln.designation_category in DESIGNATION_CATEGORIES else "unclassified"
                spent[ln.entry.entry_date.year - y][category] += exp[1]
        if received == 0:
            received = grant.total_amount  # tranșa nu e încă înregistrată: suma din decizia SFS
        totals = [sum(spent[o].values(), Decimal(0)) if y + o <= year else None for o in range(3)]
        remaining = received - sum((t for t in totals if t is not None), Decimal(0))
        to_refund = remaining > 0 and year >= y + 2
        if any(spent[o]["unclassified"] for o in range(3)):
            result.warnings.append(
                f"Anexa 1D, {grant.code}: cheltuieli fără categoria desemnării (articolul de cheltuieli)"
            )
        if to_refund:
            result.warnings.append(
                f"Anexa 1D, {grant.code} (desemnarea {y}): {remaining} lei neutilizați în 2 ani — "
                "de restituit la buget până la termenul declarației"
            )
        rows.append(
            {
                "grant_id": str(grant.id),
                "grant_code": grant.code,
                "designation_year": y,
                "received": str(received),
                "columns": [
                    None
                    if totals[o] is None
                    else {"year": y + o, "total": str(totals[o]), **{k: str(v) for k, v in spent[o].items()}}
                    for o in range(3)
                ],
                "remaining": str(remaining),
                "to_refund": to_refund,
            }
        )
    return rows


# ───────────────────────────── 5-CON ─────────────────────────────


def _income_form(debit_code: str) -> str:
    if _is(debit_code, "341"):
        return "fixed_assets"
    if _is(debit_code, "535", "21"):
        return "stocks"
    return "cash"


def con5_sources(
    db: Session, organization_id: uuid.UUID, date_from: date, date_to: date, articles: set[str]
) -> SourceResult:
    """`articles` — rândurile care au sursa `con5:<rând>` în versiunea formularului;
    cheltuiala cu alt articol (sau fără) intră la `con5:unassigned` (rândul 230)."""
    result = SourceResult()
    flt = _class_filter(("6", "7", *AMORTIZATION), ("6", "7", *AMORTIZATION))
    for ln in _lines(db, organization_id, date_from, date_to, flt):
        result.has_activity = True
        if (inc := ln.income()) is not None:
            account, amount = inc
            c = ln.contribution(amount)
            funding = (ln.grant.funding_type or "").strip().lower() if ln.grant else ""
            if _is(account, "616", "617", "618") or ln.entry.activity_type in ACTIVITIES or ln.grant:
                activity = ln.activity(account)
                if activity == "other" and (funding in MEMBER_FUNDING or _is(ln.debit, "234")):
                    result.add("con5.income.members", c)
                elif activity == "economic":
                    result.add("con5.income.economic.other", c)
                else:
                    result.add(f"con5.income.{activity}.{_income_form(ln.debit)}", c)
            else:
                result.add("con5.income.misc", c)
        amortization = next((AMORTIZATION[p] for p in AMORTIZATION if _is(ln.credit, p)), None)
        reversal = next((AMORTIZATION[p] for p in AMORTIZATION if _is(ln.debit, p)), None)
        if (exp := ln.expense()) is not None:
            amount = exp[1]
            article = amortization or ln.con5_article
        elif amortization or reversal:
            amount = ln.entry.amount if amortization else -ln.entry.amount
            article = amortization or reversal
        else:
            continue
        article = article.zfill(3) if article and article.isdigit() else article
        result.add(f"con5:{article}" if article in articles else "con5:unassigned", ln.contribution(amount))

    stats = db.scalar(
        select(OrganizationStats)
        .where(OrganizationStats.organization_id == organization_id, OrganizationStats.period_end <= date_to)
        .order_by(OrganizationStats.period_end.desc())
        .limit(1)
    )
    if stats is None:
        result.warnings.append("Nu sunt date despre membri și voluntari (rândurile 300, 320) — completați „Statistica ONG”")
    else:
        label = f"la {stats.period_end:%d.%m.%Y}"
        result.add("stats.members", Contribution(kind="stats", amount=Decimal(stats.members_count or 0), label=label))
        result.add("stats.volunteers", Contribution(kind="stats", amount=Decimal(stats.volunteers_count or 0), label=label))
    # numărul mediu al salariaților vine din contractele CIM (modulul salarii): până atunci — corecție manuală
    return result
