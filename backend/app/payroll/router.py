"""Persoane fizice, contracte (CIM / civil) cu finanțarea și scutirile lor,
rezultatele calculului salariului, plata cumulată a impozitelor și cotele."""

import re
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Department
from app.core import crypto
from app.core.db import get_db
from app.core.enums import ContractType
from app.documents.models import Document, PaymentOrder, PaymentOrderLine
from app.payroll import ipc21
from app.payroll.calc import ensure_budget_line
from app.payroll.models import Contract, ContractFunding, ExemptionClaim, IndividualPayment, PayrollEntry, Person
from app.payroll.service import (
    TAX_KINDS,
    GroupedPaymentInput,
    create_grouped_payment,
    delete_grouped_payment,
    get_period,
    period_entries,
)
from app.posting.engine import PostingError
from app.posting.router import http_error
from app.taxes.models import TaxRate

router = APIRouter(prefix="/organizations/{organization_id}", tags=["salarii"])

EXEMPTION_KINDS = ("personal", "major_personal", "dependents", "disabled_dependents")


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


# ───────────────────────── persoane fizice ─────────────────────────


class PersonIn(BaseModel):
    full_name: str = Field(min_length=2)
    idnp: str
    birth_date: date | None = None
    cpas: str | None = None

    @field_validator("idnp")
    @classmethod
    def _idnp(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{13}", v):
            raise ValueError("IDNP are 13 cifre")
        return v


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str
    idnp: str
    idnp_masked: str
    birth_date: date | None
    cpas: str | None


def _person_out(p: Person) -> PersonOut:
    idnp = crypto.decrypt(p.idnp_enc)
    return PersonOut(
        id=p.id, full_name=p.full_name, idnp=idnp, idnp_masked=crypto.mask(idnp), birth_date=p.birth_date, cpas=p.cpas
    )


def _get_person(db: Session, ctx: OrgContext, person_id: uuid.UUID) -> Person:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.organization_id == ctx.organization_id))
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persoana nu a fost găsită")
    return person


def _check_idnp_unique(db: Session, ctx: OrgContext, idnp: str, except_id: uuid.UUID | None = None) -> None:
    # IDNP-ul e criptat nedeterminist: comparăm după decriptare (organizațiile au puține persoane)
    for other in db.scalars(select(Person).where(Person.organization_id == ctx.organization_id)):
        if other.id != except_id and crypto.decrypt(other.idnp_enc) == idnp:
            raise _unprocessable(f"Persoana cu acest IDNP există deja: {other.full_name}")


@router.get("/persons", response_model=list[PersonOut])
def list_persons(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    persons = db.scalars(
        select(Person).where(Person.organization_id == ctx.organization_id).order_by(Person.full_name)
    )
    return [_person_out(p) for p in persons]


@router.post("/persons", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create_person(body: PersonIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _check_idnp_unique(db, ctx, body.idnp)
    person = Person(
        organization_id=ctx.organization_id,
        full_name=body.full_name.strip(),
        idnp_enc=crypto.encrypt(body.idnp),
        birth_date=body.birth_date,
        cpas=body.cpas,
    )
    db.add(person)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="persons",
        entity_id=person.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"full_name": person.full_name},  # IDNP-ul nu intră în audit
    )
    db.commit()
    return _person_out(person)


@router.put("/persons/{person_id}", response_model=PersonOut)
def update_person(
    person_id: uuid.UUID, body: PersonIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    ctx.require(POSTING_ROLES)
    person = _get_person(db, ctx, person_id)
    _check_idnp_unique(db, ctx, body.idnp, person.id)
    old = {"full_name": person.full_name, "cpas": person.cpas}
    person.full_name = body.full_name.strip()
    person.idnp_enc = crypto.encrypt(body.idnp)
    person.birth_date = body.birth_date
    person.cpas = body.cpas
    write_audit(
        db,
        action="update",
        entity="persons",
        entity_id=person.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values=old,
        new_values={"full_name": person.full_name, "cpas": person.cpas},
    )
    db.commit()
    return _person_out(person)


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(person_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    person = _get_person(db, ctx, person_id)
    used = db.scalar(select(func.count()).select_from(Contract).where(Contract.person_id == person.id)) or 0
    used += db.scalar(
        select(func.count()).select_from(IndividualPayment).where(IndividualPayment.person_id == person.id)
    ) or 0
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Persoana are contracte sau plăți; nu se poate șterge")
    db.delete(person)
    write_audit(
        db, action="delete", entity="persons", entity_id=person_id, organization_id=ctx.organization_id, user_id=ctx.user.id
    )
    db.commit()


# ───────────────────────── contracte ─────────────────────────


class FundingIn(BaseModel):
    grant_id: uuid.UUID
    budget_line_id: uuid.UUID | None = None
    share_percent: Decimal = Field(gt=0, le=100, max_digits=5, decimal_places=2)
    valid_from: date
    valid_to: date | None = None


class ExemptionIn(BaseModel):
    kind: str
    dependents_count: int = Field(default=0, ge=0, le=20)
    valid_from: date
    valid_to: date | None = None


class ContractIn(BaseModel):
    person_id: uuid.UUID
    type: ContractType
    is_main_job: bool = False
    department_id: uuid.UUID | None = None
    special_function_code: str | None = None
    number: str | None = None
    start_date: date
    end_date: date | None = None
    gross_amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    funding: list[FundingIn] = []
    exemptions: list[ExemptionIn] = []


class ContractOut(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    type: ContractType
    is_main_job: bool
    department_id: uuid.UUID | None
    special_function_code: str | None
    number: str | None
    start_date: date
    end_date: date | None
    gross_amount: Decimal
    funding: list[FundingIn]
    exemptions: list[ExemptionIn]


def _contract_out(c: Contract) -> ContractOut:
    return ContractOut(
        id=c.id,
        person_id=c.person_id,
        person_name=c.person.full_name,
        type=c.type,
        is_main_job=bool(c.is_main_job),
        department_id=c.department_id,
        special_function_code=c.special_function_code,
        number=c.number,
        start_date=c.start_date,
        end_date=c.end_date,
        gross_amount=c.gross_amount,
        funding=[
            FundingIn(
                grant_id=f.grant_id,
                budget_line_id=f.budget_line_id,
                share_percent=f.share_percent,
                valid_from=f.valid_from,
                valid_to=f.valid_to,
            )
            for f in c.funding
        ],
        exemptions=[
            ExemptionIn(
                kind=e.kind, dependents_count=e.dependents_count or 0, valid_from=e.valid_from, valid_to=e.valid_to
            )
            for e in c.exemptions
        ],
    )


def _contracts_query(ctx: OrgContext):
    return (
        select(Contract)
        .join(Person, Person.id == Contract.person_id)
        .where(Person.organization_id == ctx.organization_id)
        .options(selectinload(Contract.person), selectinload(Contract.funding), selectinload(Contract.exemptions))
    )


def _get_contract(db: Session, ctx: OrgContext, contract_id: uuid.UUID) -> Contract:
    contract = db.scalar(_contracts_query(ctx).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contractul nu a fost găsit")
    return contract


def _overlap(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    return a_from <= (b_to or date.max) and b_from <= (a_to or date.max)


def _validate_contract(db: Session, ctx: OrgContext, body: ContractIn, contract_id: uuid.UUID | None) -> None:
    _get_person(db, ctx, body.person_id)
    if body.end_date and body.end_date < body.start_date:
        raise _unprocessable("Data sfârșitului contractului e înaintea începutului")
    if body.department_id and db.scalar(
        select(Department.id).where(
            Department.id == body.department_id, Department.organization_id == ctx.organization_id
        )
    ) is None:
        raise _unprocessable("Subdiviziunea nu aparține organizației")
    if body.type == ContractType.civil and body.is_main_job:
        raise _unprocessable("Locul de muncă de bază există doar la CIM")
    if body.is_main_job:
        others = db.scalars(
            _contracts_query(ctx).where(
                Contract.person_id == body.person_id,
                Contract.type == ContractType.cim,
                Contract.is_main_job.is_(True),
                Contract.id != (contract_id or uuid.uuid4()),
            )
        ).all()
        if any(_overlap(o.start_date, o.end_date, body.start_date, body.end_date) for o in others):
            raise _unprocessable("Persoana are deja un CIM de bază în aceeași perioadă (scutirea se acordă o singură dată)")
    # scutirile: doar la CIM, doar la locul de bază (CF art. 33–35)
    if body.exemptions and not (body.type == ContractType.cim and body.is_main_job):
        raise _unprocessable("Scutirile se acordă doar la contractul individual de muncă de bază")
    for e in body.exemptions:
        if e.kind not in EXEMPTION_KINDS:
            raise _unprocessable(f"Tip de scutire necunoscut: {e.kind}")
        if e.kind in ("dependents", "disabled_dependents") and e.dependents_count < 1:
            raise _unprocessable("Indicați numărul persoanelor întreținute")
    # finanțarea: granturile organizației, linia din grant, fără dublă finanțare (≤ 100% la orice dată)
    try:
        for f in body.funding:
            ensure_budget_line(db, ctx.organization_id, f.grant_id, f.budget_line_id)
    except PostingError as exc:
        raise _unprocessable(str(exc)) from None
    for f in body.funding:
        if f.valid_to and f.valid_to < f.valid_from:
            raise _unprocessable("Finanțarea: data de sfârșit e înaintea începutului")
        on = f.valid_from
        total = sum(
            (g.share_percent for g in body.funding if g.valid_from <= on and (g.valid_to is None or g.valid_to >= on)),
            Decimal(0),
        )
        if total > 100:
            raise _unprocessable(f"Finanțarea depășește 100% la {on:%d.%m.%Y} ({total}%) — dublă finanțare")


def _apply_contract(contract: Contract, body: ContractIn) -> None:
    for key in ("person_id", "type", "is_main_job", "department_id", "special_function_code", "number"):
        setattr(contract, key, getattr(body, key))
    contract.start_date = body.start_date
    contract.end_date = body.end_date
    contract.gross_amount = body.gross_amount
    contract.funding = [ContractFunding(**f.model_dump()) for f in body.funding]
    contract.exemptions = [ExemptionClaim(person_id=body.person_id, **e.model_dump()) for e in body.exemptions]


@router.get("/contracts", response_model=list[ContractOut])
def list_contracts(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return [_contract_out(c) for c in db.scalars(_contracts_query(ctx).order_by(Person.full_name, Contract.start_date))]


@router.get("/contracts/{contract_id}", response_model=ContractOut)
def get_contract(contract_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return _contract_out(_get_contract(db, ctx, contract_id))


@router.post("/contracts", response_model=ContractOut, status_code=status.HTTP_201_CREATED)
def create_contract(body: ContractIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _validate_contract(db, ctx, body, None)
    contract = Contract()
    _apply_contract(contract, body)
    db.add(contract)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="contracts",
        entity_id=contract.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"type": body.type.value, "gross_amount": str(body.gross_amount), "number": body.number},
    )
    db.commit()
    return _contract_out(_get_contract(db, ctx, contract.id))


@router.put("/contracts/{contract_id}", response_model=ContractOut)
def update_contract(
    contract_id: uuid.UUID, body: ContractIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    """Modificarea se aplică calculelor viitoare; lunile calculate rămân înghețate în payroll_entries."""
    ctx.require(POSTING_ROLES)
    contract = _get_contract(db, ctx, contract_id)
    _validate_contract(db, ctx, body, contract.id)
    old = {"type": contract.type.value, "gross_amount": str(contract.gross_amount), "end_date": str(contract.end_date)}
    _apply_contract(contract, body)
    db.flush()
    write_audit(
        db,
        action="update",
        entity="contracts",
        entity_id=contract.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values=old,
        new_values={"type": body.type.value, "gross_amount": str(body.gross_amount), "end_date": str(body.end_date)},
    )
    db.commit()
    return _contract_out(_get_contract(db, ctx, contract.id))


@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    contract = _get_contract(db, ctx, contract_id)
    if db.scalar(select(func.count()).select_from(PayrollEntry).where(PayrollEntry.contract_id == contract.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Contractul are salarii calculate; nu se poate șterge")
    db.delete(contract)
    write_audit(
        db,
        action="delete",
        entity="contracts",
        entity_id=contract_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()


# ───────────────────────── rezultatele calculului ─────────────────────────


class PayrollEntryOut(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    contract_type: ContractType
    contract_number: str | None
    person_id: uuid.UUID
    person_name: str
    income_code: str
    period_start: date | None
    period_end: date | None
    gross: Decimal
    cnas_employer: Decimal | None
    cnam_employee: Decimal | None
    personal_exemption: Decimal | None
    dependents_exemption: Decimal | None
    taxable_income: Decimal | None
    income_tax: Decimal | None
    net: Decimal | None
    calc_details: dict | None


class PayrollPeriodOut(BaseModel):
    year: int
    month: int
    calculated: bool
    is_closed: bool
    entries: list[PayrollEntryOut]
    totals: dict[str, Decimal]


@router.get("/payroll/{year}/{month}", response_model=PayrollPeriodOut)
def payroll_period(year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Statul de plată al lunii (rezultatele înghețate ale pasului „Calculul salariului”)."""
    period = get_period(db, ctx.organization_id, year, month)
    rows = period_entries(db, ctx.organization_id, year, month)
    entries = [
        PayrollEntryOut(
            id=r.entry.id,
            contract_id=r.contract.id,
            contract_type=r.contract.type,
            contract_number=r.contract.number,
            person_id=r.person.id,
            person_name=r.person.full_name,
            **{
                k: getattr(r.entry, k)
                for k in (
                    "income_code", "period_start", "period_end", "gross", "cnas_employer", "cnam_employee",
                    "personal_exemption", "dependents_exemption", "taxable_income", "income_tax", "net", "calc_details",
                )
            },
        )  # fmt: skip
        for r in rows
    ]
    totals = {
        k: sum((getattr(e, k) or Decimal(0) for e in entries), Decimal(0))
        for k in ("gross", "cnas_employer", "cnam_employee", "income_tax", "net")
    }
    return PayrollPeriodOut(
        year=year,
        month=month,
        calculated=bool(entries),
        is_closed=bool(period and period.is_closed),
        entries=entries,
        totals=totals,
    )


class GroupedPaymentIn(BaseModel):
    tax_kind: str
    bank_account_id: uuid.UUID
    doc_number: str = Field(min_length=1)
    doc_date: date
    grant_id: uuid.UUID | None = None
    purpose_limit: int = Field(default=210, ge=50, le=1000, description="OTP — 210; MAIB — 2 × 220 (DE1 + DE2)")
    beneficiary_name: str | None = None
    beneficiary_iban: str | None = None
    beneficiary_idno: str | None = None
    is_urgent: bool = False


class GroupedLineOut(BaseModel):
    person_id: uuid.UUID | None
    person_name: str | None
    grant_id: uuid.UUID | None
    amount: Decimal


class GroupedPaymentOut(BaseModel):
    document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    tax_kind: str | None
    amount: Decimal | None
    purpose: str | None
    is_posted: bool | None
    lines: list[GroupedLineOut]


def _grouped_out(db: Session, doc, order) -> GroupedPaymentOut:
    names = dict(
        db.execute(
            select(Person.id, Person.full_name).where(Person.id.in_({ln.person_id for ln in order.lines}))
        ).all()
    )
    return GroupedPaymentOut(
        document_id=doc.id,
        doc_number=doc.doc_number,
        doc_date=doc.doc_date,
        tax_kind=order.tax_kind,
        amount=doc.total_amount,
        purpose=order.purpose,
        is_posted=doc.is_posted,
        lines=[
            GroupedLineOut(
                person_id=ln.person_id, person_name=names.get(ln.person_id), grant_id=ln.grant_id, amount=ln.amount
            )
            for ln in order.lines
        ],
    )


@router.get("/payroll/{year}/{month}/grouped-payments", response_model=list[GroupedPaymentOut])
def list_grouped_payments(
    year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    entry_ids = [r.entry.id for r in period_entries(db, ctx.organization_id, year, month)]
    if not entry_ids:
        return []
    order_ids = select(PaymentOrderLine.payment_order_id).where(PaymentOrderLine.payroll_entry_id.in_(entry_ids))
    rows = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(
            Document.organization_id == ctx.organization_id,
            PaymentOrder.kind == "grouped_tax",
            PaymentOrder.id.in_(order_ids),
        )
        .order_by(Document.doc_date, Document.doc_number)
    ).all()
    return [_grouped_out(db, doc, order) for doc, order in rows]


@router.post(
    "/payroll/{year}/{month}/grouped-payments", response_model=GroupedPaymentOut, status_code=status.HTTP_201_CREATED
)
def create_grouped(
    year: int,
    month: int,
    body: GroupedPaymentIn,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    """Plata cumulată (docs/09 §3): un ordin pe tip de obligație (și, opțional, pe grant), cu rânduri pe persoane."""
    ctx.require(POSTING_ROLES)
    if body.tax_kind not in TAX_KINDS:
        raise _unprocessable("Tipul plății: income_tax, cnas, cnam sau net_salary")
    try:
        doc, order = create_grouped_payment(
            db, ctx.organization_id, GroupedPaymentInput(year=year, month=month, **body.model_dump()), ctx.user.id
        )
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _grouped_out(db, doc, order)


@router.delete("/grouped-payments/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grouped(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    try:
        delete_grouped_payment(db, ctx.organization_id, document_id, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()


# ───────────────────────── cotele ─────────────────────────


class TaxRateOut(BaseModel):
    id: uuid.UUID
    code: str
    applies_to: ContractType | None
    value: Decimal
    is_percent: bool | None
    valid_from: date
    valid_to: date | None
    legal_basis: str | None

    model_config = {"from_attributes": True}


@router.get("/tax-rates", response_model=list[TaxRateOut])
def list_tax_rates(
    on_date: date | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    """Cotele cu valabilitate (comune tuturor organizațiilor); `on_date` = doar cele în vigoare la dată."""
    query = select(TaxRate).order_by(TaxRate.code, TaxRate.valid_from)
    if on_date:
        query = query.where(TaxRate.valid_from <= on_date, or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= on_date))
    return list(db.scalars(query))


# ───────────────────────── IPC21 ─────────────────────────


class Table1RowOut(BaseModel):
    row: str
    code: str
    title: str
    c4: Decimal
    c5: Decimal
    c6: Decimal


class NominalRowOut(BaseModel):
    no: int
    person_id: uuid.UUID
    full_name: str
    idnp_masked: str
    cpas: str | None
    period_start: date | None
    period_end: date | None
    insured_category: str | None
    tariff: Decimal
    function_code: str | None
    base: Decimal
    sick_benefit: Decimal
    contribution: Decimal


class Ipc21Out(BaseModel):
    year: int
    month: int
    table1: list[Table1RowOut]
    total: Table1RowOut
    control_sum: Decimal
    annex: list[dict]
    nominal: list[NominalRowOut]
    tariffs: list[dict]
    breakdown: list[dict]
    errors: list[str]


@router.get("/reports/ipc21/{year}/{month}", response_model=Ipc21Out)
def ipc21_report(year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    try:
        r = ipc21.build(db, ctx.organization_id, year, month)
    except PostingError as exc:
        raise http_error(exc) from None
    return Ipc21Out(
        year=year,
        month=month,
        table1=[Table1RowOut(**vars(x)) for x in r.table1],
        total=Table1RowOut(**vars(r.total)),
        control_sum=r.control_sum,
        annex=r.annex,
        nominal=[
            NominalRowOut(**{k: v for k, v in vars(n).items() if k != "idnp"}, idnp_masked=crypto.mask(n.idnp))
            for n in r.nominal
        ],
        tariffs=r.tariffs,
        breakdown=r.breakdown,
        errors=r.errors,
    )


@router.get("/reports/ipc21/{year}/{month}/xml")
def ipc21_xml(year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Fișierul XML; cu erori de verificare (docs/05 §5) nu se exportă."""
    ctx.require(POSTING_ROLES)
    try:
        r = ipc21.build(db, ctx.organization_id, year, month)
    except PostingError as exc:
        raise http_error(exc) from None
    if r.errors:
        raise _unprocessable("IPC21 are erori de verificare: " + "; ".join(r.errors))
    write_audit(
        db,
        action="export",
        entity="tax_reports",
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"form": "IPC21", "period": f"{month:02d}.{year}"},
    )
    db.commit()
    return Response(
        content=ipc21.to_xml(r),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="IPC21_{year}_{month:02d}.xml"'},
    )
