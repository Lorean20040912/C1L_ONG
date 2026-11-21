"""Calculul salariului pe contract (ToR M3, F3.2–F3.3) — pasul „payroll” al închiderii lunii.

Pentru fiecare contract activ în lună:

- **CIM**: salariul lunar proporțional cu zilele lucrătoare (luni–vineri) din
  perioada contractului; contribuția CNAS a angajatorului, prima CNAM reținută,
  impozitul pe venit cu scutirile din `exemption_claims` — **doar la locul de
  muncă de bază**; codul IPC21 `SAL`;
- **contract civil**: onorariul lunar întreg, aceleași reținerea CNAM și
  contribuția CNAS, impozitul reținut la sursă **fără nicio scutire**; codul `PL`.

Baza impozabilă = brut − CNAM − scutiri (nu poate fi negativă). Toate cotele vin
din `tax_rates`, valabile la ultima zi a lunii; ce cotă s-a folosit rămâne în
`calc_details`. Sumele se repartizează pe granturi după `contract_funding`
(cotele valabile în lună trebuie să dea 100%); diferența de rotunjire merge la
ultima cotă, ca suma părților să fie exact totalul.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import ContractType, SubcontoType
from app.documents.posting import funding_of
from app.grants.models import BudgetLine, Grant
from app.month_close.depreciation import month_bounds
from app.payroll.models import Contract, PayrollInput, Person
from app.posting.engine import AnalyticsInput, PostingError
from app.posting.rules import GeneratedLine, OperationInput, build_lines
from app.taxes.models import TaxRate

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
DOCUMENT_TYPE = "payroll"

INCOME_CODES = {ContractType.cim: "SAL", ContractType.civil: "PL"}
INSURED_CATEGORY = {ContractType.cim: "angajat", ContractType.civil: "prestator"}
# componentele care se repartizează pe granturi
AMOUNTS = ("gross", "cnas", "cnam", "income_tax", "net")
EXEMPTION_KINDS = {
    "personal": "PERSONAL_EXEMPTION_YEAR",
    "major_personal": "MAJOR_PERSONAL_EXEMPTION_YEAR",
    "dependents": "DEPENDENT_EXEMPTION_YEAR",
    "disabled_dependents": "DISABLED_DEPENDENT_EXEMPTION_YEAR",
}


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def rate_in_force(db: Session, code: str, contract_type: ContractType | None, on_date: date) -> TaxRate:
    """Cota valabilă la dată; cota specifică tipului de contract are prioritate față de cea comună."""
    candidates = db.scalars(
        select(TaxRate)
        .where(
            TaxRate.code == code,
            TaxRate.valid_from <= on_date,
            or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= on_date),
            or_(TaxRate.applies_to.is_(None), TaxRate.applies_to == contract_type)
            if contract_type
            else TaxRate.applies_to.is_(None),
        )
        .order_by(TaxRate.valid_from.desc())
    ).all()
    if not candidates:
        raise PostingError(f"Lipsește cota {code} valabilă la {on_date:%d.%m.%Y}")
    candidates.sort(key=lambda r: (r.applies_to is not None, r.valid_from), reverse=True)
    return candidates[0]


def _percent(amount: Decimal, rate: TaxRate) -> Decimal:
    return money(amount * rate.value / HUNDRED) if rate.is_percent is not False else money(rate.value)


def working_days(start: date, end: date) -> int:
    days, d = 0, start
    while d <= end:
        days += d.weekday() < 5
        d += timedelta(days=1)
    return days


def split(amount: Decimal, shares: list[Decimal]) -> list[Decimal]:
    """Împarte suma după cote (procente); ultima parte ia restul rotunjirii."""
    total_share = sum(shares, Decimal(0))
    parts = [money(amount * s / total_share) for s in shares[:-1]]
    return [*parts, amount - sum(parts, Decimal(0))]


def _active(valid_from: date, valid_to: date | None, start: date, end: date) -> bool:
    return valid_from <= end and (valid_to is None or valid_to >= start)


@dataclass
class FundingPart:
    grant: Grant
    budget_line_id: uuid.UUID | None
    share: Decimal
    amounts: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class ContractCalc:
    contract: Contract
    person: Person
    income_code: str
    period_start: date
    period_end: date
    gross: Decimal
    cnas: Decimal
    cnas_tariff: Decimal
    cnam: Decimal
    personal_exemption: Decimal
    dependents_exemption: Decimal
    taxable: Decimal
    income_tax: Decimal
    net: Decimal
    details: dict
    parts: list[FundingPart] = field(default_factory=list)
    error: str | None = None
    sick_benefit: Decimal = Decimal(0)  # plătită de CNAS: doar se raportează (IPC21 c10), nu intră în brut


def calculate_contract(db: Session, contract: Contract, year: int, month: int) -> ContractCalc | None:
    """Calculul unui contract pentru lună; None dacă contractul nu e activ în lună."""
    start, end = month_bounds(year, month)
    if not _active(contract.start_date, contract.end_date, start, end):
        return None
    period_start = max(start, contract.start_date)
    period_end = min(end, contract.end_date) if contract.end_date else end
    ctype = contract.type
    details: dict = {"rates": {}}

    def rate(code: str) -> TaxRate:
        r = rate_in_force(db, code, ctype, end)
        details["rates"][code] = {"id": str(r.id), "value": str(r.value), "legal_basis": r.legal_basis}
        return r

    entry_input = db.scalar(
        select(PayrollInput).where(
            PayrollInput.contract_id == contract.id, PayrollInput.year == year, PayrollInput.month == month
        )
    )
    sick_benefit = money(entry_input.sick_benefit) if entry_input and entry_input.sick_benefit else Decimal(0)
    if sick_benefit:
        details["sick_benefit"] = str(sick_benefit)
    if ctype == ContractType.cim:
        month_days = working_days(start, end)
        worked = working_days(period_start, period_end)
        if entry_input is not None and entry_input.worked_days is not None:
            if entry_input.worked_days > worked:  # contractul s-a scurtat după pontaj: se limitează, cu avertisment
                details["timesheet_warning"] = (
                    f"pontaj de {entry_input.worked_days} zile, perioada contractului are {worked}; s-au luat {worked}"
                )
            else:
                worked = entry_input.worked_days
            details["timesheet"] = True
        details["working_days"] = {"month": month_days, "worked": worked}
        gross = money(contract.gross_amount * worked / month_days) if month_days else Decimal(0)
    else:
        gross = money(contract.gross_amount)

    cnas_rate = rate("CNAS_EMPLOYER")
    cnas = _percent(gross, cnas_rate)
    cnam = _percent(gross, rate("CNAM_EMPLOYEE"))

    personal = dependents = Decimal(0)
    if ctype == ContractType.cim and contract.is_main_job:
        claims = [c for c in contract.exemptions if _active(c.valid_from, c.valid_to, start, end)]
        details["exemptions"] = []
        for claim in claims:
            code = EXEMPTION_KINDS.get(claim.kind)
            if code is None:
                continue
            monthly = money(rate(code).value / 12)
            if claim.kind in ("personal", "major_personal"):
                personal = max(personal, monthly)  # scutirea majoră înlocuiește scutirea personală
                amount = monthly
            else:
                amount = monthly * (claim.dependents_count or 0)
                dependents += amount
            details["exemptions"].append({"kind": claim.kind, "count": claim.dependents_count, "amount": str(amount)})
    taxable = max(Decimal(0), gross - cnam - personal - dependents)
    income_tax = _percent(taxable, rate("INCOME_TAX"))
    net = gross - cnam - income_tax

    calc = ContractCalc(
        contract=contract,
        person=contract.person,
        income_code=INCOME_CODES[ctype],
        period_start=period_start,
        period_end=period_end,
        gross=gross,
        cnas=cnas,
        cnas_tariff=cnas_rate.value,
        cnam=cnam,
        personal_exemption=personal,
        dependents_exemption=dependents,
        taxable=taxable,
        income_tax=income_tax,
        net=net,
        details=details,
        sick_benefit=sick_benefit,
    )
    _split_funding(db, calc, start, end)
    return calc


def _split_funding(db: Session, calc: ContractCalc, start: date, end: date) -> None:
    """Cotele se ponderează cu zilele pe care le acoperă în perioada lucrată a lunii, deci
    finanțarea se poate schimba de la un grant la altul în mijlocul lunii; în fiecare zi
    suma cotelor trebuie să fie 100%."""
    first, last = calc.period_start, calc.period_end
    rows = [f for f in calc.contract.funding if _active(f.valid_from, f.valid_to, first, last)]
    day, uncovered = first, []
    while day <= last:
        total = sum((f.share_percent for f in rows if _active(f.valid_from, f.valid_to, day, day)), Decimal(0))
        if total != HUNDRED:
            uncovered.append((day, total))
        day += timedelta(days=1)
    if uncovered:
        day, total = uncovered[0]
        calc.error = (
            f"finanțarea contractului acoperă {total}% la {day:%d.%m.%Y} — completați repartizarea pe granturi "
            "până la 100% în fiecare zi"
        )
        return
    period_days = (last - first).days + 1
    weights = []
    for f in rows:
        days = (min(last, f.valid_to or last) - max(first, f.valid_from)).days + 1
        weights.append(f.share_percent * days)
    grants = {g.id: g for g in db.scalars(select(Grant).where(Grant.id.in_({f.grant_id for f in rows})))}
    calc.parts = [
        FundingPart(grants[f.grant_id], f.budget_line_id, money(w / period_days)) for f, w in zip(rows, weights, strict=True)
    ]
    shares = weights
    for name in AMOUNTS:
        for part, value in zip(calc.parts, split(getattr(calc, name), shares), strict=True):
            part.amounts[name] = value
    calc.details["funding"] = [
        {
            "grant_id": str(p.grant.id),
            "grant_code": p.grant.code,
            "budget_line_id": str(p.budget_line_id) if p.budget_line_id else None,
            "share": str(p.share),
            **{k: str(v) for k, v in p.amounts.items()},
        }
        for p in calc.parts
    ]


def contract_operations(calc: ContractCalc, year: int, month: int) -> list[OperationInput]:
    person = [AnalyticsInput(side="K", subconto_type=SubcontoType.person, ref_id=calc.person.id)]
    person_d = [AnalyticsInput(side="D", subconto_type=SubcontoType.person, ref_id=calc.person.id)]
    label = f"{calc.income_code} {month:02d}.{year} — {calc.person.full_name}"
    ops: list[OperationInput] = []
    for part in calc.parts:
        funding = funding_of(part.grant)
        a = part.amounts

        def op(operation: str, amount: Decimal, analytics: list, what: str, part=part, funding=funding):
            return OperationInput(
                operation=operation,
                amount=amount,
                attributes={"funding": funding, "income_code": calc.income_code},
                grant_id=part.grant.id,
                budget_line_id=part.budget_line_id,
                description=f"{what}: {label}",
                analytics=list(analytics),
            )

        candidates = [
            op("salary_expense", a["gross"], person, "Salariu calculat"),
            op("employer_contribution", a["cnas"], [], "Contribuția CNAS"),
        ]
        if funding == "special_purpose":
            candidates.append(op("income_recognition", a["gross"] + a["cnas"], [], "Venituri din grant"))
        candidates += [
            op("cnam_withholding", a["cnam"], person_d, "Prima CNAM reținută"),
            op("income_tax_withholding", a["income_tax"], person_d, "Impozit pe venit reținut"),
        ]
        ops += [o for o in candidates if o.amount > 0]
    return ops


@dataclass
class PayrollPlan:
    year: int
    month: int
    calcs: list[ContractCalc] = field(default_factory=list)
    lines: list[GeneratedLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def active_contracts(db: Session, organization_id: uuid.UUID, start: date, end: date) -> list[Contract]:
    return list(
        db.scalars(
            select(Contract)
            .join(Person, Person.id == Contract.person_id)
            .where(
                Person.organization_id == organization_id,
                Contract.start_date <= end,
                or_(Contract.end_date.is_(None), Contract.end_date >= start),
            )
            .options(
                selectinload(Contract.person), selectinload(Contract.funding), selectinload(Contract.exemptions)
            )
            .order_by(Person.full_name, Contract.start_date)
        )
    )


def plan(db: Session, organization_id: uuid.UUID, year: int, month: int) -> PayrollPlan:
    """Calculul lunii fără să scrie nimic (previzualizare); `run` îl înregistrează."""
    start, end = month_bounds(year, month)
    result = PayrollPlan(year, month)
    for contract in active_contracts(db, organization_id, start, end):
        who = f"{contract.person.full_name} ({contract.number or contract.type.value})"
        try:
            calc = calculate_contract(db, contract, year, month)
        except PostingError as exc:
            result.errors.append(f"{who}: {exc}")
            continue
        if calc is None:
            continue
        result.calcs.append(calc)
        if calc.error:
            result.errors.append(f"{who}: {calc.error}")
            continue
        ops = contract_operations(calc, year, month)
        if not ops:
            continue
        try:
            result.lines += build_lines(
                db, organization_id=organization_id, document_type=DOCUMENT_TYPE, doc_date=end, operations=ops
            )
        except PostingError as exc:
            result.errors.append(f"{who}: {exc}")
    return result


def ensure_budget_line(db: Session, organization_id: uuid.UUID, grant_id: uuid.UUID, line_id: uuid.UUID | None):
    """Verifică grantul și linia de buget (linia trebuie să fie a grantului)."""
    grant = db.scalar(select(Grant).where(Grant.id == grant_id, Grant.organization_id == organization_id))
    if grant is None:
        raise PostingError("Grantul nu aparține organizației")
    if line_id is not None and db.scalar(
        select(BudgetLine.id).where(BudgetLine.id == line_id, BudgetLine.grant_id == grant_id)
    ) is None:
        raise PostingError("Linia de buget nu aparține grantului")
    return grant


def exemption_allowed(contract: Contract) -> bool:
    return contract.type == ContractType.cim and bool(contract.is_main_job)

