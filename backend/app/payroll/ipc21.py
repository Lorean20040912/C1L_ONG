"""Raportul IPC21 (docs/05-specificatie-IPC21.md) din calculul salariului și plățile către persoane fizice.

- Tabelul 1: col.4 venitul calculat, col.5 impozitul reținut, col.6 CNAM (doar la SAL),
  pe codurile sursei de venit; rândul 61 = total; suma de control.
- Anexa la Tabelul 1: impozitul SAL pe subdiviziuni (CUATM).
- Tabelul 2: evidența nominală CNAS și totalurile pe tarife.
- Verificările din §5 înainte de export.

Sursele: `payroll_entries` ale lunii (codul vine din contract: CIM → SAL, civil → PL,
deci scutirea nu poate ajunge la PL) și documentele „Plată către persoană fizică”
înregistrate, cu data calculării în lună.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogs.models import Department
from app.core import crypto
from app.core import fisc_xml as fx
from app.core.enums import ContractType
from app.documents.models import Document
from app.month_close.depreciation import month_bounds
from app.payroll.models import IndividualPayment, Person
from app.payroll.service import period_entries
from app.workspaces.models import Organization

ZERO = Decimal(0)

# codul sursei de venit → rândul din Tabelul 1 (docs/05 §2)
ROWS = [
    ("11", "SAL", "Plăți salariale, art. 88 CF"),
    ("12", "SAL a)", "Salarii IT (Legea 1164/1997)"),
    ("21", "DOB a)", "Dobânzi, art. 89"),
    ("22", "DOB", "Dobânzi către persoane fizice rezidente, art. 90¹ alin.(3⁷)"),
    ("31", "PL", "Venituri din care se reține impozit, art. 90 (contracte civile)"),
    ("32", "PLs", "Venituri scutite de reținerea prealabilă, art. 90"),
    ("41", "FOL", "Locațiune / arendă / uzufruct, art. 90¹ alin.(3)"),
    ("42", "PUB", "Dividende, art. 90¹ alin.(3¹)"),
    ("44", "ROY", "Redevențe către persoane fizice"),
    ("49", "DON pf", "Donații către persoane fizice, art. 90¹ alin.(3¹)"),
]
ROW_BY_CODE = {code: row for row, code, _ in ROWS}
CONTROL_ROWS = {"41", "42", "43", "44", "45", "46", "47", "48", "49", "491"}
# tariful CNAS → rândul totalurilor din Tabelul 2
TARIFF_ROWS = {Decimal(29): "r11a", Decimal(24): "r11b", Decimal(39): "r12a", Decimal(32): "r12b", Decimal(6): "r17"}


@dataclass
class Table1Row:
    row: str
    code: str
    title: str
    c4: Decimal = ZERO
    c5: Decimal = ZERO
    c6: Decimal = ZERO


@dataclass
class NominalRow:
    no: int
    person_id: uuid.UUID
    full_name: str
    idnp: str
    cpas: str | None
    period_start: object
    period_end: object
    insured_category: str | None
    tariff: Decimal
    function_code: str | None
    base: Decimal
    sick_benefit: Decimal
    contribution: Decimal


@dataclass
class Ipc21:
    year: int
    month: int
    organization: Organization
    table1: list[Table1Row] = field(default_factory=list)
    total: Table1Row | None = None
    control_sum: Decimal = ZERO
    annex: list[dict] = field(default_factory=list)
    nominal: list[NominalRow] = field(default_factory=list)
    tariffs: list[dict] = field(default_factory=list)
    breakdown: list[dict] = field(default_factory=list)  # descifrarea: fiecare sumă cu sursa ei
    errors: list[str] = field(default_factory=list)


def build(db: Session, organization_id: uuid.UUID, year: int, month: int) -> Ipc21:
    start, end = month_bounds(year, month)
    org = db.get(Organization, organization_id)
    report = Ipc21(year=year, month=month, organization=org)
    rows = {row: Table1Row(row, code, title) for row, code, title in ROWS}

    def row_for(code: str) -> Table1Row:
        if code not in ROW_BY_CODE:
            report.errors.append(f"Codul sursei de venit {code} nu are rând în Tabelul 1")
            rows.setdefault(code, Table1Row(code, code, code))
            return rows[code]
        return rows[ROW_BY_CODE[code]]

    entries = period_entries(db, organization_id, year, month)
    departments = {d.id: d for d in db.scalars(select(Department).where(Department.organization_id == organization_id))}
    annex: dict[str, Decimal] = defaultdict(Decimal)
    tariffs: dict[Decimal, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for r in entries:
        e = r.entry
        target = row_for(e.income_code)
        target.c4 += e.gross
        target.c5 += e.income_tax or ZERO
        if e.income_code == "SAL":
            target.c6 += e.cnam_employee or ZERO
            dept = departments.get(r.contract.department_id)
            cuatm = (dept.cuatm if dept and dept.cuatm else None) or org.cuatm or "—"
            annex[cuatm] += e.income_tax or ZERO
        expected = "SAL" if r.contract.type == ContractType.cim else "PL"
        if e.income_code not in (expected, f"{expected}s", f"{expected} a)"):
            report.errors.append(f"{r.person.full_name}: contract {r.contract.type.value} declarat la {e.income_code}")
        if r.contract.type == ContractType.civil and ((e.personal_exemption or 0) or (e.dependents_exemption or 0)):
            report.errors.append(f"{r.person.full_name}: scutire aplicată la contract civil")
        report.breakdown.append(
            {
                "source": "payroll",
                "code": e.income_code,
                "person": r.person.full_name,
                "contract": r.contract.number,
                "c4": e.gross,
                "c5": e.income_tax or ZERO,
                "c6": (e.cnam_employee or ZERO) if e.income_code == "SAL" else ZERO,
            }
        )
        if e.cnas_employer and e.cnas_employer > 0:
            idnp = crypto.decrypt(r.person.idnp_enc)
            report.nominal.append(
                NominalRow(
                    no=len(report.nominal) + 1,
                    person_id=r.person.id,
                    full_name=r.person.full_name,
                    idnp=idnp,
                    cpas=r.person.cpas,
                    period_start=e.period_start,
                    period_end=e.period_end,
                    insured_category=e.insured_category,
                    tariff=e.cnas_tariff or ZERO,
                    function_code=r.contract.special_function_code,
                    base=e.cnas_base or ZERO,
                    sick_benefit=e.sick_benefit or ZERO,
                    contribution=e.cnas_employer,
                )
            )
            tariffs[e.cnas_tariff or ZERO][0] += e.cnas_base or ZERO
            tariffs[e.cnas_tariff or ZERO][1] += e.cnas_employer

    payments = db.execute(
        select(IndividualPayment, Person, Document)
        .join(Document, Document.id == IndividualPayment.document_id)
        .join(Person, Person.id == IndividualPayment.person_id)
        .where(
            Document.organization_id == organization_id,
            Document.is_posted.is_(True),
            Document.deletion_mark.is_not(True),
            IndividualPayment.accrual_date.between(start, end),
        )
        .order_by(IndividualPayment.accrual_date)
    ).all()
    for p, person, doc in payments:
        target = row_for(p.income_code)
        target.c4 += p.gross
        target.c5 += p.income_tax or ZERO
        report.breakdown.append(
            {
                "source": "individual_payment",
                "code": p.income_code,
                "person": person.full_name,
                "contract": doc.doc_number,
                "c4": p.gross,
                "c5": p.income_tax or ZERO,
                "c6": ZERO,
            }
        )

    report.table1 = sorted(rows.values(), key=lambda x: x.row)
    report.total = Table1Row(
        "61",
        "",
        "TOTAL",
        sum((x.c4 for x in report.table1), ZERO),
        sum((x.c5 for x in report.table1), ZERO),
        sum((x.c6 for x in report.table1), ZERO),
    )
    report.control_sum = report.total.c5 - sum((x.c5 for x in report.table1 if x.row in CONTROL_ROWS), ZERO)
    report.annex = [
        {"no": i, "cuatm": cuatm, "c3": tax, "c4": tax, "c5": ZERO}
        for i, (cuatm, tax) in enumerate(sorted(annex.items()), start=1)
    ]
    report.tariffs = [
        {"row": TARIFF_ROWS.get(t, f"tarif {t}%"), "tariff": t, "c9": base, "c11": contribution}
        for t, (base, contribution) in sorted(tariffs.items())
    ]
    _checks(report)
    return report


def _checks(report: Ipc21) -> None:
    """Regulile din docs/05 §5."""
    annex_total = sum((a["c3"] for a in report.annex), ZERO)
    sal = sum((x.c5 for x in report.table1 if x.code in ("SAL", "SAL a)")), ZERO)
    if annex_total != sal:
        report.errors.append(f"Anexa: total {annex_total} ≠ impozitul SAL din Tabelul 1 {sal}")
    nominal_total = sum((n.contribution for n in report.nominal), ZERO)
    if nominal_total != sum((t["c11"] for t in report.tariffs), ZERO):
        report.errors.append("Tabelul 2: totalul nominal ≠ totalul pe tarife")
    for n in report.nominal:
        if not (len(n.idnp) == 13 and n.idnp.isdigit()):
            report.errors.append(f"{n.full_name}: IDNP lipsă sau incorect")
        if not n.cpas:
            report.errors.append(f"{n.full_name}: lipsește CPAS (Tabelul 2)")
        if n.tariff not in TARIFF_ROWS:
            report.errors.append(f"{n.full_name}: tariful CNAS {n.tariff}% nu are rând în totaluri")


def _money(value: Decimal, *, empty_zero: bool = False) -> str:
    return fx.money(value, empty_zero=empty_zero)


# Tabelul 1 în ordinea exportului oficial: (rând, coloane). Rândurile 12 și 23 rămân
# goale când nu au sume; rândul 61 are coloanele în ordinea 6, 5, 4.
TABLE1_CELLS = [
    ("11", (4, 5, 6)), ("12", (4, 5, 6)), ("21", (4, 5)), ("22", (4, 5)), ("23", (4, 5)), ("31", (4, 5)),
    ("32", (4,)), ("41", (4, 5)), ("42", (4, 5)), ("43", (4, 5)), ("44", (4, 5)), ("45", (4, 5)),
    ("46", (4, 5)), ("47", (4, 5)), ("48", (4, 5)), ("49", (4, 5)), ("491", (4, 5)), ("51", (4, 5)),
    ("52", (4, 5)), ("53", (4, 5)), ("54", (4, 5)), ("55", (4, 5)), ("56", (4, 5)), ("61", (6, 5, 4)),
]  # fmt: skip
EMPTY_WHEN_ZERO = {"12", "23"}
# Tabelul 2, totaluri pe tarife: (rând, coloane), în ordinea exportului oficial
TABLE2_CELLS = [
    ("r11a", (9, 11)), ("r11b", (9, 11)), ("r12a", (9, 11)), ("r12b", (9, 11)), ("r13", (9, 11)),
    ("r14a", (9, 11)), ("r14b", (11,)), ("r15", (11,)), ("r16", (11,)), ("r17", (9, 11)),
    ("r2", (10,)), ("r21", (10,)), ("r22", (10,)), ("r23", (10,)), ("r24", (10,)),
    ("r3", (10,)), ("r31", (10,)), ("r32", (10,)), ("r33", (10,)), ("r34", (10,)),
]  # fmt: skip
TABLE2_FILLED = {"r11a", "r11b", "r12a", "r12b", "r14a", "r14b", "r15", "r16"}  # restul rămâne gol


def _tariff_text(tariff: Decimal) -> str:
    return f"{tariff.normalize():f}%"


def to_xml(report: Ipc21) -> bytes:
    """Fișierul pentru e-Cabinet SFS, în structura exportului oficial IPC21 (docs/exemple-fisc/ipc21.xml).
    Câmpurile pe care aplicația nu le ține (e-mail, telefon, titlurile clasificatoarelor) rămân goale."""
    org = report.organization
    root = ET.Element("dec", {"TypeName": "ipc21"})
    fisc = fx.sub(root, "fiscCod")
    fx.sub(fisc, "fiscal", org.idno)
    fx.sub(fisc, "name", org.name)
    fx.sub(fisc, "cuatm", org.cuatm, title="")
    fx.sub(fisc, "fisc", org.sfs_office, title="")
    fx.sub(fisc, "caem", org.caem, title="")
    fx.sub(fisc, "email")
    fx.sub(fisc, "telefon")
    fx.sub(fisc, "cnas", org.cnas_code)
    fx.sub(fx.sub(root, "peroidnalog"), "datefisc", fx.month_period(report.year, report.month))
    director = fx.sub(root, "director")
    fx.sub(director, "director", org.director_name)
    fx.sub(director, "contabil", org.chief_accountant_name)

    table1 = fx.sub(root, "table1")
    ds = fx.sub(table1, "ds")
    for tag, value in (("flag", 0), ("flag1", 1), ("flag2", 0)):  # 1 = declarația primară
        fx.sub(ds, tag, value)
    fx.sub(fx.sub(table1, "it"), "flag1", 0)
    cf = fx.sub(table1, "cf")
    fx.sub(cf, "flag1", 0)
    fx.sub(cf, "flag2", 0)
    by_row = {x.row: x for x in [*report.table1, report.total]}
    row = fx.sub(table1, "row")
    for number, columns in TABLE1_CELLS:
        x = by_row.get(number)
        for column in columns:
            value = getattr(x, f"c{column}") if x else Decimal(0)
            fx.sub(row, f"r{number}c{column}", _money(value, empty_zero=number in EMPTY_WHEN_ZERO))
    fx.sub(root, "summContr", _money(report.control_sum))

    dyn = fx.sub(root, "dinamicTable")
    for line, a in enumerate(report.annex or [None], start=1):
        r = fx.sub(dyn, "row", line=str(line))
        fx.sub(r, "c1", a["no"] if a else line)
        fx.sub(r, "c2", a["cuatm"] if a else None, title="")
        for key in ("c3", "c4", "c5"):
            fx.sub(r, key, _money(a[key]) if a else None)
    total = fx.sub(dyn, "total")
    for n in (3, 4, 5):
        fx.sub(total, f"tot1c{n}", _money(sum((a[f"c{n}"] for a in report.annex), ZERO)) if report.annex else None)

    table11 = fx.sub(root, "table11")
    for n in (1, 2, 3):
        r = fx.sub(table11, f"row{n}")
        for c in (3, 4, 5, 6, 7):
            fx.sub(r, f"c{c}")

    dyn2 = fx.sub(root, "dinamicTable2")
    for line, n in enumerate(report.nominal or [None], start=1):
        r = fx.sub(dyn2, "row", line=str(line))
        fx.sub(r, "c1", n.no if n else line)
        fx.sub(r, "c2", n.full_name if n else None)
        fx.sub(r, "c3", n.idnp if n else None)
        fx.sub(r, "c4", n.cpas if n else None)
        fx.sub(r, "c5", fx.date_text(n.period_start) if n else None)
        fx.sub(r, "c6", fx.date_text(n.period_end) if n else None)
        fx.sub(r, "c7", n.insured_category if n else None)
        fx.sub(r, "c71", _tariff_text(n.tariff) if n else None)
        fx.sub(r, "c8", n.function_code if n else None)
        fx.sub(r, "c81", title="")
        fx.sub(r, "c9", _money(n.base) if n else None)
        fx.sub(r, "c10", _money(n.sick_benefit, empty_zero=True) if n else None)
        fx.sub(r, "c11", _money(n.contribution) if n else None)
    total2 = fx.sub(dyn2, "total")
    fx.sub(total2, "tot2c9", _money(sum((n.base for n in report.nominal), ZERO)))
    fx.sub(total2, "tot2c10", _money(sum((n.sick_benefit for n in report.nominal), ZERO)))
    fx.sub(total2, "tot2c11", _money(sum((n.contribution for n in report.nominal), ZERO)))

    by_tariff = {t["row"]: t for t in report.tariffs}
    trow = fx.sub(fx.sub(root, "table2"), "row")
    for name, columns in TABLE2_CELLS:
        t = by_tariff.get(name)
        for column in columns:
            value = None
            if name in TABLE2_FILLED or t:
                value = _money(t[f"c{column}"] if t else ZERO)
            fx.sub(trow, f"{name}c{column}", value)
    return fx.serialize(root)
