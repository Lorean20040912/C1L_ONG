"""„Plată către persoană fizică” (docs/05 §2): chirie (FOL), arendă teren agricol (PLs),
servicii (PL), donație (DON pf), dobândă (DOB), royalty (ROY).

Tipul plății dă codul IPC21 și cota de reținere din `tax_rates` valabilă la data
calculării; înregistrarea: Dt cheltuieli (716 / 717 / 718 după sursa liniei de
buget) — Kt 544, Dt 544 — Kt 534 (impozitul reținut), plus 537/616 pentru granturi.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import SubcontoType
from app.documents.models import Document
from app.documents.posting import funding_of
from app.grants.models import BudgetLine, Grant
from app.payroll.calc import money, rate_in_force
from app.payroll.models import IndividualPayment, Person
from app.posting.engine import AnalyticsInput, PostingError, post_document
from app.posting.models import EntryLine
from app.posting.rules import GeneratedLine, OperationInput, build_lines

DOCUMENT_TYPE = "individual_payment"

# tipul plății → (codul sursei de venit IPC21, codul cotei de reținere, denumirea)
PAYMENT_KINDS = {
    "rent": ("FOL", "WITHHOLDING_FOL", "Chirie (locațiune)"),
    "agri_land_rent": ("PLs", "WITHHOLDING_PLS", "Arendă teren agricol"),
    "services": ("PL", "WITHHOLDING_PL", "Servicii prestate"),
    "donation": ("DON pf", "WITHHOLDING_DON_PF", "Donație către persoană fizică"),
    "interest": ("DOB", "WITHHOLDING_DOB", "Dobândă"),
    "royalty": ("ROY", "WITHHOLDING_ROY", "Royalty"),
}


def compute(db: Session, payment: IndividualPayment) -> None:
    """Completează codul IPC21, cota, impozitul și suma netă după tip și dată."""
    kind = PAYMENT_KINDS.get(payment.payment_kind)
    if kind is None:
        raise PostingError("Tip de plată necunoscut")
    income_code, rate_code, _ = kind
    rate = rate_in_force(db, rate_code, None, payment.accrual_date)
    payment.income_code = income_code
    payment.tax_rate_id = rate.id
    payment.income_tax = money(payment.gross * rate.value / 100) if rate.is_percent is not False else money(rate.value)
    payment.net = payment.gross - payment.income_tax


def _grant(db: Session, organization_id: uuid.UUID, payment: IndividualPayment) -> Grant:
    if payment.budget_line_id is None:
        raise PostingError("Alegeți linia de buget (proiectul) din care se plătește")
    grant = db.scalar(
        select(Grant)
        .join(BudgetLine, BudgetLine.grant_id == Grant.id)
        .where(BudgetLine.id == payment.budget_line_id, Grant.organization_id == organization_id)
    )
    if grant is None:
        raise PostingError("Linia de buget nu aparține organizației")
    return grant


def load(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> tuple[Document, IndividualPayment]:
    row = db.execute(
        select(Document, IndividualPayment)
        .join(IndividualPayment, IndividualPayment.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == organization_id)
    ).first()
    if row is None:
        raise PostingError("Documentul nu a fost găsit")
    return row[0], row[1]


def operations(db: Session, organization_id: uuid.UUID, doc: Document, payment: IndividualPayment):
    compute(db, payment)
    grant = _grant(db, organization_id, payment)
    payment.grant_id = grant.id
    funding = funding_of(grant)
    person = db.get(Person, payment.person_id)
    label = f"{PAYMENT_KINDS[payment.payment_kind][2]} ({payment.income_code}) — {person.full_name}"
    common = dict(
        attributes={"funding": funding, "income_code": payment.income_code},
        entry_date=payment.accrual_date,
        grant_id=grant.id,
        budget_line_id=payment.budget_line_id,
        cost_item_id=payment.cost_item_id,
    )
    ops = [
        OperationInput(
            operation="expense",
            amount=payment.gross,
            description=label,
            analytics=[AnalyticsInput(side="K", subconto_type=SubcontoType.person, ref_id=person.id)],
            **common,
        )
    ]
    if funding == "special_purpose":
        ops.append(OperationInput(operation="income_recognition", amount=payment.gross, description=label, **common))
    if payment.income_tax and payment.income_tax > 0:
        ops.append(
            OperationInput(
                operation="income_tax_withholding",
                amount=payment.income_tax,
                description=f"Impozit reținut: {label}",
                analytics=[AnalyticsInput(side="D", subconto_type=SubcontoType.person, ref_id=person.id)],
                **common,
            )
        )
    return ops


def preview(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID) -> list[GeneratedLine]:
    doc, payment = load(db, organization_id, document_id)
    if payment.gross is None or payment.gross <= 0:
        raise PostingError("Suma brută trebuie să fie pozitivă")
    return build_lines(
        db,
        organization_id=organization_id,
        document_type=DOCUMENT_TYPE,
        doc_date=payment.accrual_date,
        operations=operations(db, organization_id, doc, payment),
    )


def post(db: Session, organization_id: uuid.UUID, document_id: uuid.UUID, user_id) -> list[EntryLine]:
    generated = preview(db, organization_id, document_id)
    doc, payment = load(db, organization_id, document_id)
    doc.total_amount = payment.gross
    return post_document(
        db,
        organization_id=organization_id,
        document_id=document_id,
        lines=[g.line for g in generated],
        user_id=user_id,
        rule_refs=[f"{g.rule.id} ({g.rule.source_ref})" for g in generated],
    )

