"""Întocmirea rapoartelor reglementate: completare → corecții → verificare → depunere.

Valorile unui raport = sursele calculate din contabilitate (`sources.py`),
corecțiile manuale ale contabilului (`manual_overrides`) și formulele
formularului (`report_forms.structure`). Raportul depus (`submitted`) e înghețat:
nu se mai recalculează și nu se mai corectează; o corectare = raport nou.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.catalogs.models import Account
from app.posting.models import AccountTurnover
from app.regulated import sources as src
from app.regulated.formulas import FormulaError, evaluate, quantize, references
from app.regulated.models import ReportForm, ReportingCalendar, ReportStatus, TaxReport
from app.workspaces.models import Organization

SUPPORTED = {"ONG17", "5-CON"}
UNSCALED_PREFIXES = ("stats.", "tax_rate.")
UNIT_DECIMALS = {"pers.": 0, "%": 2}


class ReportError(Exception):
    """Mesaj pentru utilizator (422)."""


class ReportFrozen(ReportError):
    """Raportul depus nu se mai modifică (409)."""


# ───────────────────────────── formulare și perioade ─────────────────────────────


def form_for(db: Session, code: str, period_from: date) -> ReportForm:
    form = db.scalar(
        select(ReportForm)
        .where(
            ReportForm.code == code,
            ReportForm.valid_from <= period_from,
            or_(ReportForm.valid_to.is_(None), ReportForm.valid_to >= period_from),
        )
        .order_by(ReportForm.valid_from.desc())
        .limit(1)
    )
    if form is None:
        # perioada dinaintea primei versiuni: se folosește cea mai veche versiune a formularului
        form = db.scalar(select(ReportForm).where(ReportForm.code == code).order_by(ReportForm.valid_from).limit(1))
    if form is None:
        raise ReportError(f"Formularul {code} nu există")
    return form


def _month_end(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def period_bounds(periodicity: str, period_from: date) -> date:
    """Sfârșitul perioadei; începutul trebuie să fie prima zi a lunii / trimestrului / anului."""
    if period_from.day != 1:
        raise ReportError("Perioada începe în prima zi a lunii")
    if periodicity == "month":
        return _month_end(period_from)
    if periodicity == "quarter":
        if period_from.month not in (1, 4, 7, 10):
            raise ReportError("Trimestrul începe în ianuarie, aprilie, iulie sau octombrie")
        return _month_end(period_from.replace(month=period_from.month + 2))
    if periodicity == "year":
        if period_from.month != 1:
            raise ReportError("Anul fiscal începe la 1 ianuarie")
        return date(period_from.year, 12, 31)
    raise ReportError(f"Periodicitate necunoscută: {periodicity}")


def due_date(rule: str | None, period_to: date) -> date:
    """`next_month:25` — ziua 25 a lunii următoare perioadei; `next_year:03-25` — 25 martie anul următor."""
    kind, _, value = (rule or "next_month:25").partition(":")
    if kind == "next_year":
        month, day = (int(x) for x in value.split("-"))
        return date(period_to.year + 1, month, day)
    next_month = period_to + timedelta(days=1)
    return next_month.replace(day=min(int(value or 25), 28))


def articles_of(structure: dict) -> set[str]:
    """Rândurile 5-CON care primesc cheltuieli după articol (`con5:<rând>`)."""
    found = set()
    for row in structure.get("rows", []):
        names = [row["source"]] if row.get("source") else []
        names += [key for kind, key in references(row.get("formula", "")) if kind == "source"] if row.get("formula") else []
        found |= {n.split(":", 1)[1] for n in names if n.startswith("con5:") and n.split(":", 1)[1].isdigit()}
    return found


# ───────────────────────────── calculul valorilor ─────────────────────────────


@dataclass
class Computed:
    values: dict[str, Decimal]
    checks: list[dict]


def _row_decimals(structure: dict, row: dict) -> int:
    return UNIT_DECIMALS.get(row.get("unit"), structure.get("decimals", 2))


def source_value(structure: dict, sources: dict[str, Decimal], name: str) -> Decimal:
    value = Decimal(sources.get(name, 0))
    scale = Decimal(structure.get("scale", 1))
    if scale != 1 and not name.startswith(UNSCALED_PREFIXES):
        return quantize(value / scale, structure.get("decimals", 2))
    return value


def compute(
    structure: dict,
    sources: dict[str, Decimal],
    overrides: dict[str, Decimal],
    *,
    has_activity: bool = True,
    warnings: list[str] | None = None,
) -> Computed:
    rows = {row["code"]: row for row in structure.get("rows", [])}
    values: dict[str, Decimal] = {}
    visiting: set[str] = set()

    def source(name: str) -> Decimal:
        return source_value(structure, sources, name)

    def calculated(code: str) -> Decimal:
        row = rows[code]
        if row.get("formula"):
            raw = evaluate(row["formula"], cell, source)
        elif row.get("source"):
            raw = source(row["source"])
        else:
            raw = Decimal(0)
        return quantize(raw, _row_decimals(structure, row))

    def cell(code: str) -> Decimal:
        if code not in rows:
            raise FormulaError(f"Rândul {code} nu există în formular")
        if code in values:
            return values[code]
        if code in visiting:
            raise FormulaError(f"Formula rândului {code} se referă la ea însăși")
        visiting.add(code)
        values[code] = Decimal(overrides[code]) if code in overrides else calculated(code)
        visiting.discard(code)
        return values[code]

    for code in rows:
        cell(code)

    checks: list[dict] = []
    for code, row in rows.items():
        if row.get("formula"):
            expected = quantize(evaluate(row["formula"], cell, source), _row_decimals(structure, row))
            if values[code] != expected:
                checks.append({"severity": "error", "cell": code,
                               "message": f"Rândul {code} = {values[code]}, dar formula dă {expected}"})  # fmt: skip
    for check in structure.get("checks", []):
        if not evaluate(check["expr"], cell, source):
            checks.append({"severity": check.get("severity", "error"), "message": check["message"]})
    if not has_activity:
        informative = {c for c, r in rows.items() if r.get("source", "").startswith("stats.")}
        if any(v for c, v in values.items() if c not in informative):
            checks.append({"severity": "error", "message": "Fără activitate în perioadă toate rândurile trebuie să fie 0"})
    checks += [{"severity": "warning", "message": w} for w in warnings or []]
    return Computed(values=values, checks=checks)


def calculate_sources(db: Session, organization_id: uuid.UUID, form: ReportForm, period_from: date, period_to: date):
    if form.code == "ONG17":
        result = src.ong17_sources(db, organization_id, period_from.year)
        _balance_check(db, organization_id, period_from, period_to, result)
        return result
    if form.code == "5-CON":
        return src.con5_sources(db, organization_id, period_from, period_to, articles_of(form.structure))
    raise ReportError(f"Raportul {form.code} se completează odată cu modulul lui")


def _balance_check(db: Session, organization_id: uuid.UUID, date_from: date, date_to: date, result) -> None:
    """docs/06 §4.5: totalurile 0101 / 0102 = rulajele claselor 6 / 7 din balanța anului
    (fără închiderea anului)."""
    for cls, side, keys in (("6", -1, ("special_purpose", "economic", "other")),
                            ("7", 1, ("special_purpose", "economic", "other"))):  # fmt: skip
        turnover = db.scalar(
            select(func.coalesce(func.sum(AccountTurnover.debit - AccountTurnover.credit), 0))
            .join(Account, Account.id == AccountTurnover.account_id)
            .where(
                AccountTurnover.organization_id == organization_id,
                AccountTurnover.period.between(date_from, date_to),
                Account.code.startswith(cls),
            )
        )
        closing = Decimal(0)
        for ln in src._lines(db, organization_id, date_from, date_to, src._class_filter(src.CLOSING_PREFIXES, src.CLOSING_PREFIXES)):
            if src._is(ln.debit, cls):
                closing += ln.entry.amount
            if src._is(ln.credit, cls):
                closing -= ln.entry.amount
        balance = side * (Decimal(turnover) - closing)
        kind = "income" if cls == "6" else "expense"
        ours = sum((result.value(f"ong17.{kind}.{k}") for k in keys), Decimal(0))
        if balance != ours:
            result.warnings.append(
                f"Totalul {'veniturilor' if cls == '6' else 'cheltuielilor'} ({ours}) diferă de rulajul clasei {cls} "
                f"din balanță ({balance})"
            )


# ───────────────────────────── antetul ─────────────────────────────


def header(org: Organization, form: ReportForm, period_from: date, user: User | None, has_activity: bool) -> dict:
    if form.code == "ONG17":
        return {
            "period": str(period_from.year), "ngo_category": org.ngo_category, "name": org.name, "idno": org.idno,
            "caem": org.caem, "sfs_office": org.sfs_office, "date": date.today().isoformat(),
        }  # fmt: skip
    return {
        "ENT_NAME": org.name, "IDNO": org.idno, "CUIIO": org.cuiio, "CFOJ": org.cfoj, "CFP": org.cfp,
        "CAEM": org.caem, "CUATM": org.cuatm, "YEAR": str(period_from.year),
        "TRIM": str((period_from.month - 1) // 3 + 1), "HEAD": org.director_name,
        "EXECUTOR": org.chief_accountant_name or (user.full_name if user else None),
        "flag1": "1" if has_activity else "0", "flag2": "0" if has_activity else "1",
    }  # fmt: skip


REQUIRED_HEADER = {
    "ONG17": {"ngo_category": "categoria ONG", "caem": "codul CAEM", "sfs_office": "subdiviziunea SFS"},
    "5-CON": {"CUIIO": "codul CUIIO", "CFOJ": "CFOJ", "CFP": "CFP", "CAEM": "codul CAEM", "CUATM": "codul CUATM"},
}


# ───────────────────────────── raportul ─────────────────────────────


def _decimal_map(raw: dict | None) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in (raw or {}).items()}


def _store(report: TaxReport, form: ReportForm, data: dict) -> None:
    overrides = _decimal_map(report.manual_overrides)
    computed = compute(
        form.structure, _decimal_map(data["sources"]), overrides,
        has_activity=data.get("has_activity", True), warnings=data.get("warnings"),
    )  # fmt: skip
    data["values"] = {k: str(v) for k, v in computed.values.items()}
    data["checks"] = computed.checks
    report.data = data


def generate(db: Session, org: Organization, user: User | None, code: str, period_from: date) -> TaxReport:
    """Completează raportul pentru perioadă: actualizează ciorna existentă (cu corecțiile ei)
    sau creează una nouă dacă perioada nu are ciornă."""
    if code not in SUPPORTED:
        raise ReportError(f"Raportul {code} se completează odată cu modulul lui")
    form = form_for(db, code, period_from)
    period_to = period_bounds(form.periodicity, period_from)
    report = db.scalar(
        select(TaxReport)
        .where(
            TaxReport.organization_id == org.id,
            TaxReport.form_id.in_(select(ReportForm.id).where(ReportForm.code == code)),
            TaxReport.period_from == period_from,
            TaxReport.status != ReportStatus.submitted,
        )
        .order_by(TaxReport.id)
        .limit(1)
        .with_for_update()
    )
    if report is None:
        report = TaxReport(organization_id=org.id, form_id=form.id, period_from=period_from, period_to=period_to,
                           manual_overrides={})  # fmt: skip
        db.add(report)
    report.form_id, report.period_to = form.id, period_to
    report.status = ReportStatus.draft
    report.prepared_by = user.id if user else None
    result = calculate_sources(db, org.id, form, period_from, period_to)
    head = header(org, form, period_from, user, result.has_activity)
    warnings = list(result.warnings)
    for key, label in REQUIRED_HEADER.get(code, {}).items():
        if not head.get(key):
            warnings.append(f"Antet: lipsește {label} (Date pentru rapoarte)")
    _store(
        report,
        form,
        {
            "form_version": form.version,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "header": head,
            "has_activity": result.has_activity,
            "sources": {k: str(v) for k, v in result.values.items()},
            "warnings": warnings,
            "annex_1d": result.annex_1d,
        },
    )
    db.flush()
    return report


def ensure_editable(report: TaxReport) -> None:
    if report.status == ReportStatus.submitted:
        raise ReportFrozen("Raportul este depus și nu se mai modifică; pentru corectare întocmiți un raport nou")


def set_overrides(db: Session, report: TaxReport, cells: dict[str, str | None]) -> TaxReport:
    ensure_editable(report)
    form = db.get(ReportForm, report.form_id)
    codes = {row["code"] for row in form.structure.get("rows", [])}
    overrides = dict(report.manual_overrides or {})
    for code, value in cells.items():
        if code not in codes:
            raise ReportError(f"Rândul {code} nu există în formular")
        if value is None or value == "":
            overrides.pop(code, None)
            continue
        try:
            overrides[code] = str(Decimal(str(value)))
        except InvalidOperation as exc:
            raise ReportError(f"Rândul {code}: valoare nenumerică") from exc
    report.manual_overrides = overrides
    report.status = ReportStatus.draft
    _store(report, form, dict(report.data or {}))
    db.flush()
    return report


def set_status(db: Session, report: TaxReport, status: ReportStatus) -> TaxReport:
    ensure_editable(report)
    if status in (ReportStatus.checked, ReportStatus.submitted):
        errors = [c["message"] for c in (report.data or {}).get("checks", []) if c["severity"] == "error"]
        if errors:
            raise ReportError("Raportul are erori: " + "; ".join(errors))
    report.status = status
    if status == ReportStatus.submitted:
        report.submitted_at = datetime.now()
        form = db.get(ReportForm, report.form_id)
        stmt = insert(ReportingCalendar).values(
            organization_id=report.organization_id, form_id=form.id, period_from=report.period_from,
            period_to=report.period_to, due_date=due_date(form.due_day_rule, report.period_to),
            tax_report_id=report.id,
        )  # fmt: skip
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["organization_id", "form_id", "period_from"], set_={"tax_report_id": report.id}
            )
        )
    db.flush()
    return report


def cell_sources(structure: dict, code: str) -> list[str]:
    """Sursele din care provine rândul (urmând formulele până la celulele calculate)."""
    rows = {row["code"]: row for row in structure.get("rows", [])}
    if code not in rows:
        raise ReportError(f"Rândul {code} nu există în formular")
    found: list[str] = []
    seen: set[str] = set()

    def walk(c: str) -> None:
        if c in seen or c not in rows:
            return
        seen.add(c)
        row = rows[c]
        if row.get("source") and row["source"] not in found:
            found.append(row["source"])
        for kind, key in references(row["formula"]) if row.get("formula") else []:
            if kind == "cell":
                walk(key)
            elif key not in found:
                found.append(key)

    walk(code)
    return found


# ───────────────────────────── calendarul ─────────────────────────────

STATUS_LABELS = {
    "submitted": "Prezentat",
    "overdue": "Restanță",
    "due_soon": "A rămas o săptămână",
    "upcoming": "În termen",
}


def _periods(periodicity: str, today: date, back_days: int = 400) -> list[date]:
    """Începuturile perioadelor încheiate în ultimele ~13 luni (și cea curentă, dacă s-a încheiat)."""
    starts = []
    d = date(today.year - 2, 1, 1)
    step = {"month": 1, "quarter": 3, "year": 12}[periodicity]
    while d <= today:
        end = period_bounds(periodicity, d)
        if end < today and end >= today - timedelta(days=back_days):
            starts.append(d)
        month = d.month - 1 + step
        d = date(d.year + month // 12, month % 12 + 1, 1)
    return starts


def sync_calendar(db: Session, org: Organization, today: date) -> None:
    """Adaugă în calendar termenele perioadelor încheiate (o dată pe perioadă)."""
    codes = db.scalars(select(ReportForm.code).distinct()).all()
    for code in codes:
        latest = form_for(db, code, today)
        applies = latest.structure.get("applies_to")
        if applies and org.entity_type.value not in applies:
            continue
        for start in _periods(latest.periodicity, today):
            form = form_for(db, code, start)
            end = period_bounds(form.periodicity, start)
            db.execute(
                insert(ReportingCalendar)
                .values(organization_id=org.id, form_id=form.id, period_from=start, period_to=end,
                        due_date=due_date(form.due_day_rule, end))  # fmt: skip
                .on_conflict_do_nothing(index_elements=["organization_id", "form_id", "period_from"])
            )
    db.flush()


def calendar_status(row: ReportingCalendar, report_status: ReportStatus | None, today: date) -> str:
    if row.tax_report_id is not None and report_status == ReportStatus.submitted:
        return "submitted"
    if today > row.due_date:
        return "overdue"
    if (row.due_date - today).days <= 7:
        return "due_soon"
    return "upcoming"
