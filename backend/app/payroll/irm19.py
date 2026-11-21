"""Notificarea IRM19 — angajările lunii (contractele individuale de muncă care încep în lună).

Sursa: contractele CIM ale organizației cu `start_date` în luna raportată. Codul evenimentului
îl cunoaștem din exemplul oficial doar pentru angajarea pe perioadă determinată (`05`); pentru
contractele fără dată de sfârșit codul nu e inventat — exportul se oprește cu o eroare de
verificare, ca să-l completeze contabilul după formularul oficial.
Structura XML: docs/exemple-fisc/irm19.xml.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core import fisc_xml as fx
from app.core.enums import ContractType
from app.month_close.depreciation import month_bounds
from app.payroll.models import Contract, Person
from app.workspaces.models import Organization

EVENTS = {"05": "ANGAJARE PE PERIOADĂ DETERMINATĂ"}


@dataclass
class Irm19Row:
    no: int
    full_name: str
    idnp: str
    cpas: str | None
    event_code: str | None
    event_date: date


@dataclass
class Irm19:
    year: int
    month: int
    organization: Organization
    rows: list[Irm19Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build(db: Session, organization_id: uuid.UUID, year: int, month: int) -> Irm19:
    start, end = month_bounds(year, month)
    report = Irm19(year=year, month=month, organization=db.get(Organization, organization_id))
    found = db.execute(
        select(Contract, Person)
        .join(Person, Person.id == Contract.person_id)
        .where(
            Person.organization_id == organization_id,
            Contract.type == ContractType.cim,
            Contract.start_date.between(start, end),
        )
        .order_by(Contract.start_date, Person.full_name)
    ).all()
    for contract, person in found:
        idnp = crypto.decrypt(person.idnp_enc)
        code = "05" if contract.end_date else None
        report.rows.append(Irm19Row(len(report.rows) + 1, person.full_name, idnp, person.cpas, code, contract.start_date))
        if not (len(idnp) == 13 and idnp.isdigit()):
            report.errors.append(f"{person.full_name}: IDNP lipsă sau incorect")
        if code is None:
            report.errors.append(
                f"{person.full_name}: contract pe perioadă nedeterminată — codul evenimentului IRM19 "
                "nu e cunoscut, se completează în e-Cabinet"
            )
    return report


def to_xml(report: Irm19) -> bytes:
    org = report.organization
    root = ET.Element("dec", {"TypeName": "irm19"})
    fisc = fx.sub(root, "fiscCod")
    fx.sub(fisc, "fiscal", org.idno)
    fx.sub(fisc, "name", org.name)
    fx.sub(fisc, "cnas", org.cnas_code)
    fx.sub(fisc, "fisc", org.sfs_office, title="")
    fx.sub(fisc, "email")
    fx.sub(fisc, "telefon")
    fx.sub(root, "dataPrezent")
    ds = fx.sub(fx.sub(root, "table"), "ds")
    fx.sub(ds, "primara", 1)
    fx.sub(ds, "corectare", 0)
    fx.sub(root, "dlncds")
    dyn = fx.sub(root, "dinamicTable")
    for line, n in enumerate(report.rows or [None], start=1):
        r = fx.sub(dyn, "row", line=str(line))
        fx.sub(r, "c1", n.no if n else line)
        fx.sub(r, "c2", n.full_name if n else None)
        fx.sub(r, "c3", n.idnp if n else None)
        fx.sub(r, "c4", n.cpas if n else None)
        fx.sub(r, "c5", title="")
        fx.sub(r, "c6")
        fx.sub(r, "c7")
        if n and n.event_code:
            fx.sub(r, "c8", n.event_code, title=f"{n.event_code}, {EVENTS[n.event_code]}")
        else:
            fx.sub(r, "c8", title="")
        fx.sub(r, "c9", title="")
        fx.sub(r, "c10", fx.date_text(n.event_date) if n else None)
        fx.sub(r, "c11", title="")
        fx.sub(r, "c12")
    return fx.serialize(root)
