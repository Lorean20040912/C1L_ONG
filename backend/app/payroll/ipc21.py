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


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def to_xml(report: Ipc21) -> bytes:
    """Fișierul pentru e-Cabinet SFS, cu elementele din docs/05 §1 (structura simplificată;
    se validează cu schema XSD a versiunii formularului înainte de depunere)."""
    org = report.organization
    root = ET.Element("dec", {"TypeName": "IPC21"})
    fisc = ET.SubElement(root, "fiscCod")
    ET.SubElement(fisc, "fiscal").text = org.idno or ""
    ET.SubElement(fisc, "name").text = org.name
    ET.SubElement(fisc, "cuatm").text = org.cuatm or ""
    ET.SubElement(fisc, "caem").text = org.caem or ""
    ET.SubElement(fisc, "cnas").text = org.cnas_code or ""
    period = ET.SubElement(root, "peroidnalog")
    ET.SubElement(period, "datefisc").text = f"L/{report.month:02d}/{report.year}"
    table1 = ET.SubElement(root, "table1")
    row = ET.SubElement(table1, "row")
    for x in [*report.table1, report.total]:
        if x.c4 or x.c5 or x.c6 or x.row == "61":
            ET.SubElement(row, f"r{x.row}c4").text = _money(x.c4)
            ET.SubElement(row, f"r{x.row}c5").text = _money(x.c5)
            if x.row in ("11", "12", "61"):
                ET.SubElement(row, f"r{x.row}c6").text = _money(x.c6)
    ET.SubElement(root, "summContr").text = _money(report.control_sum)
    dyn = ET.SubElement(root, "dinamicTable")
    for a in report.annex:
        r = ET.SubElement(dyn, "row")
        for key, value in (("c1", a["no"]), ("c2", a["cuatm"]), ("c3", a["c3"]), ("c4", a["c4"]), ("c5", a["c5"])):
            ET.SubElement(r, key).text = _money(value) if isinstance(value, Decimal) else str(value)
    dyn2 = ET.SubElement(root, "dinamicTable2")
    for n in report.nominal:
        r = ET.SubElement(dyn2, "row")
        values = [
            ("c1", str(n.no)), ("c2", n.full_name), ("c3", n.idnp), ("c4", n.cpas or ""),
            ("c5", n.period_start.strftime("%d.%m.%Y") if n.period_start else ""),
            ("c6", n.period_end.strftime("%d.%m.%Y") if n.period_end else ""),
            ("c7", n.insured_category or ""), ("c8", _money(n.tariff)), ("c81", n.function_code or ""),
            ("c9", _money(n.base)), ("c10", _money(n.sick_benefit)), ("c11", _money(n.contribution)),
        ]  # fmt: skip
        for key, value in values:
            ET.SubElement(r, key).text = value
    total = ET.SubElement(dyn2, "total")
    ET.SubElement(total, "tot2c9").text = _money(sum((n.base for n in report.nominal), ZERO))
    ET.SubElement(total, "tot2c10").text = _money(sum((n.sick_benefit for n in report.nominal), ZERO))
    ET.SubElement(total, "tot2c11").text = _money(sum((n.contribution for n in report.nominal), ZERO))
    table2 = ET.SubElement(root, "table2")
    trow = ET.SubElement(table2, "row")
    for t in report.tariffs:
        ET.SubElement(trow, f"{t['row']}c9").text = _money(t["c9"])
        ET.SubElement(trow, f"{t['row']}c11").text = _money(t["c11"])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
