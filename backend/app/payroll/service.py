"""Rezultatele calculului (payroll_entries) și plata cumulată a impozitelor (docs/09 §3).

Funcțiile nu fac commit (DEZVOLTARE.md, principiul 5).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.bank.models import BankAccount
from app.core.enums import DocumentType, PaymentDirection
from app.documents.models import Document, PaymentOrder, PaymentOrderLine
from app.grants.models import Grant
from app.payroll.calc import PayrollPlan
from app.payroll.models import Contract, PayrollEntry, PayrollPeriod, Person
from app.posting.engine import PostingError

TAX_KINDS = {
    "income_tax": ("IV", "income_tax"),
    "cnas": ("CAS", "cnas"),
    "cnam": ("CAM", "cnam"),
    "net_salary": ("Salariu", "net"),
}


def get_period(db: Session, organization_id: uuid.UUID, year: int, month: int, lock: bool = False):
    query = select(PayrollPeriod).where(
        PayrollPeriod.organization_id == organization_id, PayrollPeriod.year == year, PayrollPeriod.month == month
    )
    return db.scalar(query.with_for_update() if lock else query)


def _entries_in_payments(db: Session, period: PayrollPeriod) -> int:
    return len(
        db.scalars(
            select(PaymentOrderLine.id)
            .join(PayrollEntry, PayrollEntry.id == PaymentOrderLine.payroll_entry_id)
            .join(PaymentOrder, PaymentOrder.id == PaymentOrderLine.payment_order_id)
            .join(Document, Document.id == PaymentOrder.document_id)
            .where(PayrollEntry.period_id == period.id, Document.deletion_mark.is_not(True))
            .limit(1)
        ).all()
    )


def clear_entries(db: Session, organization_id: uuid.UUID, year: int, month: int) -> None:
    """Șterge rezultatele lunii (înainte de recalcul sau la anularea pasului)."""
    period = get_period(db, organization_id, year, month, lock=True)
    if period is None:
        return
    if period.is_closed:
        raise PostingError(f"Salariile pe {month:02d}.{year} sunt închise")
    if _entries_in_payments(db, period):
        raise PostingError("Pe calculul lunii există plăți cumulate; ștergeți-le întâi, apoi refaceți calculul")
    db.execute(delete(PayrollEntry).where(PayrollEntry.period_id == period.id))
    db.flush()


def store_entries(db: Session, organization_id: uuid.UUID, result: PayrollPlan, user_id: uuid.UUID | None) -> int:
    """Îngheață rezultatul calculului: un rând pe contract, cu cotele și repartizarea în calc_details."""
    clear_entries(db, organization_id, result.year, result.month)
    period = get_period(db, organization_id, result.year, result.month, lock=True)
    if period is None:
        period = PayrollPeriod(organization_id=organization_id, year=result.year, month=result.month)
        db.add(period)
        db.flush()
    for calc in result.calcs:
        single = calc.parts[0].budget_line_id if len(calc.parts) == 1 else None
        db.add(
            PayrollEntry(
                period_id=period.id,
                contract_id=calc.contract.id,
                income_code=calc.income_code,
                period_start=calc.period_start,
                period_end=calc.period_end,
                insured_category="angajat" if calc.income_code == "SAL" else "prestator",
                cnas_tariff=calc.cnas_tariff,
                cnas_base=calc.gross,
                sick_benefit=calc.sick_benefit,
                gross=calc.gross,
                personal_exemption=calc.personal_exemption,
                dependents_exemption=calc.dependents_exemption,
                taxable_income=calc.taxable,
                income_tax=calc.income_tax,
                cnam_employee=calc.cnam,
                cnas_employer=calc.cnas,
                net=calc.net,
                budget_line_id=single,
                calc_details=calc.details,
            )
        )
    db.flush()
    write_audit(
        db,
        action="payroll_calculated",
        entity="payroll_periods",
        entity_id=period.id,
        organization_id=organization_id,
        user_id=user_id,
        new_values={"entries": len(result.calcs), "gross": str(sum((c.gross for c in result.calcs), Decimal(0)))},
    )
    return len(result.calcs)


@dataclass
class EntryRow:
    entry: PayrollEntry
    contract: Contract
    person: Person


def period_entries(db: Session, organization_id: uuid.UUID, year: int, month: int) -> list[EntryRow]:
    rows = db.execute(
        select(PayrollEntry, Contract, Person)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollEntry.period_id)
        .join(Contract, Contract.id == PayrollEntry.contract_id)
        .join(Person, Person.id == Contract.person_id)
        .where(
            PayrollPeriod.organization_id == organization_id,
            PayrollPeriod.year == year,
            PayrollPeriod.month == month,
            Person.organization_id == organization_id,
        )
        .order_by(Person.full_name, Contract.start_date)
    ).all()
    return [EntryRow(*r) for r in rows]


# ───────────────────────── plata cumulată ─────────────────────────


def format_amount(value: Decimal) -> str:
    whole, cents = f"{value:.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return " ".join(groups) + "," + cents


def short_name(full_name: str, surname_only: bool) -> str:
    """„Popescu Ion” → „Popescu I.” sau „Popescu”: numele de familie e primul cuvânt."""
    parts = full_name.split()
    if surname_only or len(parts) < 2:
        return parts[0] if parts else full_name
    return f"{parts[0]} {parts[1][0]}."


def build_purpose(prefix: str, people: list[tuple[str, Decimal]], limit: int) -> str:
    """Destinația cu nume și sume; dacă nu încape, doar numele de familie; altfel eroare (de împărțit)."""
    for surname_only in (False, True):
        body = "; ".join(f"{short_name(name, surname_only)} {format_amount(amount)}" for name, amount in people)
        text = f"{prefix}: {body}"
        if len(text) <= limit:
            return text
    raise PostingError(
        f"Destinația nu încape în {limit} caractere nici cu numele de familie ({len(text)}); "
        "împărțiți plata, de exemplu pe granturi"
    )


@dataclass
class GroupedPaymentInput:
    year: int
    month: int
    tax_kind: str
    bank_account_id: uuid.UUID
    doc_number: str
    doc_date: date
    grant_id: uuid.UUID | None = None
    purpose_limit: int = 210
    beneficiary_name: str | None = None
    beneficiary_iban: str | None = None
    beneficiary_idno: str | None = None
    is_urgent: bool = False


def create_grouped_payment(
    db: Session, organization_id: uuid.UUID, data: GroupedPaymentInput, user_id: uuid.UUID | None
) -> tuple[Document, PaymentOrder]:
    if data.tax_kind not in TAX_KINDS:
        raise PostingError("Tipul plății: income_tax, cnas, cnam sau net_salary")
    label, component = TAX_KINDS[data.tax_kind]
    bank = db.get(BankAccount, data.bank_account_id)
    if bank is None or bank.organization_id != organization_id:
        raise PostingError("Contul bancar nu aparține organizației")
    if bank.currency != "MDL":
        raise PostingError("Impozitele și contribuțiile se plătesc din contul în MDL")
    grant = None
    if data.grant_id:
        grant = db.scalar(select(Grant).where(Grant.id == data.grant_id, Grant.organization_id == organization_id))
        if grant is None:
            raise PostingError("Grantul nu aparține organizației")

    # blocarea perioadei: două cereri simultane nu pot include aceleași sume în două ordine
    get_period(db, organization_id, data.year, data.month, lock=True)
    rows = period_entries(db, organization_id, data.year, data.month)
    if not rows:
        raise PostingError(f"Nu există calculul salariului pe {data.month:02d}.{data.year}")
    # ce e deja inclus în alte plăți cumulate de același tip (rând de calcul + grant)
    paid = set(
        db.execute(
            select(PaymentOrderLine.payroll_entry_id, PaymentOrderLine.grant_id)
            .join(PaymentOrder, PaymentOrder.id == PaymentOrderLine.payment_order_id)
            .join(Document, Document.id == PaymentOrder.document_id)
            .where(
                Document.organization_id == organization_id,
                Document.deletion_mark.is_not(True),
                PaymentOrder.kind == "grouped_tax",
                PaymentOrder.tax_kind == data.tax_kind,
                PaymentOrderLine.payroll_entry_id.in_([r.entry.id for r in rows]),
            )
        ).all()
    )
    lines: list[PaymentOrderLine] = []
    per_person: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    names: dict[uuid.UUID, str] = {}
    for row in rows:
        for part in (row.entry.calc_details or {}).get("funding", []):
            grant_id = uuid.UUID(part["grant_id"])
            amount = Decimal(part[component])
            if amount <= 0 or (grant and grant_id != grant.id) or (row.entry.id, grant_id) in paid:
                continue
            lines.append(
                PaymentOrderLine(
                    person_id=row.person.id, payroll_entry_id=row.entry.id, grant_id=grant_id, amount=amount
                )
            )
            per_person[row.person.id] += amount
            names[row.person.id] = row.person.full_name
    if not lines:
        raise PostingError("Nu există sume de plătit (sau sunt deja incluse în alte plăți cumulate)")
    total = sum((ln.amount for ln in lines), Decimal(0))
    prefix = f"{label} {data.month:02d}.{data.year}" + (f" proiect {grant.code}" if grant else "")
    people = sorted(((names[pid], amount) for pid, amount in per_person.items()), key=lambda x: x[0])
    purpose = build_purpose(prefix, people, data.purpose_limit)

    doc = Document(
        organization_id=organization_id,
        type=DocumentType.payment_order,
        doc_number=data.doc_number,
        doc_date=data.doc_date,
        total_amount=total,
        currency="MDL",
        uploaded_by=user_id,
    )
    db.add(doc)
    db.flush()
    order = PaymentOrder(
        document_id=doc.id,
        direction=PaymentDirection.outgoing,
        purpose=purpose,
        bank_account_id=bank.id,
        beneficiary_name=data.beneficiary_name,
        beneficiary_iban=data.beneficiary_iban,
        beneficiary_idno=data.beneficiary_idno,
        is_urgent=data.is_urgent,
        kind="grouped_tax",
        tax_kind=data.tax_kind,
        lines=lines,
    )
    db.add(order)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="documents",
        entity_id=doc.id,
        organization_id=organization_id,
        user_id=user_id,
        new_values={"kind": "grouped_tax", "tax_kind": data.tax_kind, "lines": len(lines), "total": str(total)},
    )
    return doc, order


def delete_grouped_payment(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID, user_id) -> None:
    row = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == organization_id)
        .with_for_update(of=Document)
    ).first()
    if row is None or row[1].kind != "grouped_tax":
        raise PostingError("Plata cumulată nu a fost găsită")
    doc, order = row
    if doc.is_posted:
        raise PostingError("Plata este înregistrată; anulați înregistrarea întâi")
    db.delete(order)
    db.flush()
    db.delete(doc)
    write_audit(
        db, action="delete", entity="documents", entity_id=document_id, organization_id=organization_id, user_id=user_id
    )
    db.flush()
