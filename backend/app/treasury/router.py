"""Documente de bancă și casă, decont de avans, acte de servicii primite."""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.bank.models import BankAccount
from app.catalogs.models import Account, Counterparty
from app.core.db import get_db
from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants.budget import check_document
from app.grants.models import BudgetLine, CostItem, Grant
from app.grants.router import BudgetWarningOut, warnings_out
from app.payroll.models import Person
from app.posting.engine import PostingError, unpost_document
from app.posting.models import EntryLine
from app.posting.router import EntryLineOut, http_error
from app.treasury import service
from app.treasury.models import TreasuryDoc, TreasuryDocLine

router = APIRouter(prefix="/organizations/{organization_id}/treasury", tags=["bancă și casă"])


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    line_kind: str = "service"
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    account_id: uuid.UUID | None = None
    budget_line_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None


class DocIn(BaseModel):
    kind: str
    operation: str | None = None
    doc_number: str | None = None
    doc_date: date
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    bank_account_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    grant_id: uuid.UUID | None = None
    purpose: str | None = Field(default=None, max_length=210)
    basis: str | None = Field(default=None, max_length=210)
    lines: list[LineIn] = []
    version: int | None = None


class DocOut(BaseModel):
    document_id: uuid.UUID
    kind: str
    kind_label: str
    operation: str | None
    operation_label: str | None
    doc_number: str | None
    doc_date: date | None
    amount: Decimal | None
    currency: str | None
    exchange_rate: Decimal | None
    bank_account_id: uuid.UUID | None
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None
    person_id: uuid.UUID | None
    person_name: str | None
    account_id: uuid.UUID | None
    grant_id: uuid.UUID | None
    purpose: str | None
    basis: str | None
    is_posted: bool | None
    version: int | None
    lines: list[LineIn] = []


class PreviewOut(BaseModel):
    entry_date: date
    debit_account: str
    credit_account: str
    amount: Decimal
    source_ref: str


class EntryOut(BaseModel):
    entry_date: date
    debit_account: str
    credit_account: str
    amount: Decimal
    description: str | None


class PostResult(BaseModel):
    entries: list[EntryLineOut]
    warnings: list[BudgetWarningOut]


class OpMeta(BaseModel):
    code: str
    label: str
    needs: list[str]
    optional: list[str]
    explicit: str | None
    bank: str | None
    cash: str | None


class KindMeta(BaseModel):
    kind: str
    label: str
    operations: list[OpMeta]


@router.get("/meta", response_model=list[KindMeta])
def meta(ctx: OrgContext = Depends(get_org_context)) -> list[KindMeta]:
    out = []
    for kind, label in service.KINDS.items():
        ops = [
            OpMeta(code=code, label=d.label, needs=list(d.needs), optional=list(d.optional), explicit=d.explicit,
                   bank=d.bank, cash=d.cash)
            for code, d in service.OPS.get(kind, {}).items()
        ]
        out.append(KindMeta(kind=kind, label=label, operations=ops))
    return out


def _names(db: Session, doc: Document, td: TreasuryDoc) -> tuple[str | None, str | None]:
    cp = db.scalar(select(Counterparty.name).where(Counterparty.id == doc.counterparty_id)) if doc.counterparty_id else None
    pn = db.scalar(select(Person.full_name).where(Person.id == td.person_id)) if td.person_id else None
    return cp, pn


def _out(db: Session, doc: Document, td: TreasuryDoc) -> DocOut:
    cp, pn = _names(db, doc, td)
    opdef = service.OPS.get(td.kind, {}).get(td.operation or "")
    return DocOut(
        document_id=doc.id, kind=td.kind, kind_label=service.KINDS[td.kind], operation=td.operation,
        operation_label=opdef.label if opdef else None, doc_number=doc.doc_number, doc_date=doc.doc_date,
        amount=doc.total_amount, currency=doc.currency, exchange_rate=td.exchange_rate,
        bank_account_id=td.bank_account_id, counterparty_id=doc.counterparty_id, counterparty_name=cp,
        person_id=td.person_id, person_name=pn, account_id=td.account_id, grant_id=td.grant_id, purpose=td.purpose,
        basis=td.basis, is_posted=doc.is_posted, version=doc.version,
        lines=[LineIn(description=ln.description, amount=ln.amount, line_kind=ln.line_kind, quantity=ln.quantity,
                      account_id=ln.account_id, budget_line_id=ln.budget_line_id, cost_item_id=ln.cost_item_id)
               for ln in td.lines],
    )


def _get(db: Session, ctx: OrgContext, document_id: uuid.UUID, lock: bool = False) -> tuple[Document, TreasuryDoc]:
    q = (
        select(Document, TreasuryDoc)
        .join(TreasuryDoc, TreasuryDoc.document_id == Document.id)
        .where(Document.id == document_id, Document.organization_id == ctx.organization_id)
    )
    row = db.execute(q.with_for_update(of=Document) if lock else q).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul nu a fost găsit")
    return row[0], row[1]


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _owned(db: Session, model, org: uuid.UUID, ids: set, label: str) -> None:
    ids = {i for i in ids if i}
    if not ids:
        return
    if model is BudgetLine:
        q = select(BudgetLine.id).join(Grant, Grant.id == BudgetLine.grant_id).where(Grant.organization_id == org)
    else:
        q = select(model.id).where(model.organization_id == org)
    if set(db.scalars(q.where(model.id.in_(ids)))) != ids:
        raise _bad(f"{label} nu aparține organizației")


def _next_number(db: Session, org: uuid.UUID, kind: str, on: date) -> str:
    count = db.scalar(select(func.count()).select_from(TreasuryDoc).where(
        TreasuryDoc.organization_id == org, TreasuryDoc.kind == kind)) or 0
    while True:
        count += 1
        number = f"{service.PREFIX[kind]}-{on.year}-{count:05d}"
        taken = db.scalar(select(func.count()).select_from(Document).join(TreasuryDoc, TreasuryDoc.document_id == Document.id)
                          .where(Document.organization_id == org, TreasuryDoc.kind == kind, Document.doc_number == number))
        if not taken:
            return number


def _apply(db: Session, ctx: OrgContext, doc: Document, td: TreasuryDoc, body: DocIn, existing: bool) -> None:
    org = ctx.organization_id
    kind = body.kind
    if kind not in service.KINDS:
        raise _bad("Tip de document necunoscut")
    if existing and kind != td.kind:
        raise _bad("Tipul documentului nu se poate schimba")
    for model, ids, label in (
        (BankAccount, {body.bank_account_id}, "Contul bancar"), (Counterparty, {body.counterparty_id}, "Contrapartida"),
        (Person, {body.person_id}, "Persoana"), (Account, {body.account_id} | {ln.account_id for ln in body.lines}, "Contul"),
        (Grant, {body.grant_id}, "Grantul"), (BudgetLine, {ln.budget_line_id for ln in body.lines}, "Linia de buget"),
        (CostItem, {ln.cost_item_id for ln in body.lines}, "Articolul de cheltuieli"),
    ):
        _owned(db, model, org, ids, label)
    currency = (body.currency or "MDL").upper()
    amount = body.amount
    if kind in service.LINE_DOCS:
        if not body.lines:
            raise _bad("Adăugați cel puțin un rând")
        for i, ln in enumerate(body.lines, start=1):
            if ln.line_kind not in service.LINE_KINDS:
                raise _bad(f"Rândul {i}: tipul „{ln.line_kind}” nu e permis aici (mijloacele fixe se introduc prin factură)")
        amount = sum((ln.amount for ln in body.lines), Decimal(0))
        if kind == "service_act" and not body.counterparty_id:
            raise _bad("Alegeți prestatorul (contrapartida)")
        if kind == "advance_report" and not (body.person_id and body.account_id):
            raise _bad("Alegeți persoana responsabilă și contul de avans")
        currency = "MDL"
        operation = None
    else:
        operation = body.operation
        opdef = service.OPS[kind].get(operation or "")
        if opdef is None:
            raise _bad("Alegeți operațiunea documentului")
        if amount is None:
            raise _bad("Indicați suma")
        for need in opdef.needs:
            value = {"bank": body.bank_account_id, "counterparty": body.counterparty_id, "person": body.person_id,
                     "grant": body.grant_id, "account": body.account_id}[need]
            if value is None:
                raise _bad(f"Operațiunea „{opdef.label}” cere {service.NEED_LABELS[need]}")
        if body.bank_account_id:
            bank = db.get(BankAccount, body.bank_account_id)
            currency = bank.currency
            if currency != "MDL" and not body.exchange_rate:
                raise _bad(f"Contul bancar e în {currency}: indicați cursul BNM")
        else:
            currency = "MDL"
        if kind in service.CASH_KINDS and "bank" not in opdef.needs and body.bank_account_id:
            raise _bad("Documentul de casă nu folosește cont bancar")
    doc.doc_number = (body.doc_number or "").strip() or _next_number(db, org, kind, body.doc_date)
    doc.doc_date = body.doc_date
    doc.total_amount = amount
    doc.currency = currency
    doc.counterparty_id = body.counterparty_id
    td.kind = kind
    td.operation = operation
    td.bank_account_id = body.bank_account_id
    td.person_id = body.person_id
    td.account_id = body.account_id
    td.grant_id = body.grant_id
    td.exchange_rate = body.exchange_rate if currency != "MDL" else None
    td.purpose = body.purpose
    td.basis = body.basis
    td.organization_id = org
    td.lines = [
        TreasuryDocLine(organization_id=org, position=i, **ln.model_dump()) for i, ln in enumerate(body.lines)
    ] if kind in service.LINE_DOCS else []


@router.get("/docs", response_model=list[DocOut])
def list_docs(
    kind: str,
    date_from: date | None = None,
    date_to: date | None = None,
    posted: bool | None = None,
    q: str | None = None,
    bank_account_id: uuid.UUID | None = None,
    counterparty_id: uuid.UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[DocOut]:
    if kind not in service.KINDS:
        raise _bad("Tip de document necunoscut")
    query = (
        select(Document, TreasuryDoc)
        .join(TreasuryDoc, TreasuryDoc.document_id == Document.id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .outerjoin(Person, Person.id == TreasuryDoc.person_id)
        .where(Document.organization_id == ctx.organization_id, TreasuryDoc.kind == kind)
    )
    if date_from:
        query = query.where(Document.doc_date >= date_from)
    if date_to:
        query = query.where(Document.doc_date <= date_to)
    if posted is not None:
        query = query.where(Document.is_posted.is_(posted) if posted else or_(Document.is_posted.is_(False), Document.is_posted.is_(None)))
    if bank_account_id:
        query = query.where(TreasuryDoc.bank_account_id == bank_account_id)
    if counterparty_id:
        query = query.where(Document.counterparty_id == counterparty_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(Document.doc_number.ilike(like), TreasuryDoc.purpose.ilike(like),
                                Counterparty.name.ilike(like), Person.full_name.ilike(like)))
    rows = db.execute(query.order_by(Document.doc_date.desc(), Document.doc_number.desc()).limit(500)).all()
    return [_out(db, d, t) for d, t in rows]


@router.post("/docs", response_model=DocOut, status_code=status.HTTP_201_CREATED)
def create_doc(body: DocIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> DocOut:
    ctx.require(POSTING_ROLES)
    if body.kind not in service.KINDS:
        raise _bad("Tip de document necunoscut")
    doc = Document(organization_id=ctx.organization_id, type=DocumentType(service.DOC_TYPE.get(body.kind, "other")),
                   uploaded_by=ctx.user.id)
    td = TreasuryDoc(kind=body.kind, organization_id=ctx.organization_id)
    _apply(db, ctx, doc, td, body, existing=False)
    db.add(doc)
    db.flush()
    td.document_id = doc.id
    db.add(td)
    db.flush()
    write_audit(db, action="create", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)
    db.commit()
    return _out(db, doc, td)


@router.get("/docs/{document_id}", response_model=DocOut)
def get_doc(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> DocOut:
    doc, td = _get(db, ctx, document_id)
    return _out(db, doc, td)


@router.put("/docs/{document_id}", response_model=DocOut)
def update_doc(document_id: uuid.UUID, body: DocIn, ctx: OrgContext = Depends(get_org_context),
               db: Session = Depends(get_db)) -> DocOut:
    ctx.require(POSTING_ROLES)
    doc, td = _get(db, ctx, document_id, lock=True)
    if body.version is not None and body.version != doc.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul a fost modificat între timp; redeschideți-l")
    if doc.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este înregistrat; anulați înregistrarea ca să-l modificați")
    _apply(db, ctx, doc, td, body, existing=True)
    doc.version = (doc.version or 1) + 1
    db.flush()
    write_audit(db, action="update", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)
    db.commit()
    db.refresh(td)
    return _out(db, doc, td)


@router.delete("/docs/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_doc(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    doc, td = _get(db, ctx, document_id, lock=True)
    if doc.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este înregistrat; anulați întâi înregistrarea")
    has_entries = db.scalar(select(func.count()).select_from(EntryLine).where(
        EntryLine.organization_id == ctx.organization_id, EntryLine.document_id == doc.id))
    write_audit(db, action="delete", entity="documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)
    if has_entries:  # a avut înregistrări: rămâne în istoric, marcat pentru ștergere
        doc.deletion_mark = True
    else:
        db.delete(td)
        db.flush()
        db.delete(doc)
    db.commit()


def _codes(db: Session, ids: set) -> dict:
    return dict(db.execute(select(Account.id, Account.code).where(Account.id.in_(ids))).all())


@router.post("/docs/{document_id}/preview", response_model=list[PreviewOut])
def preview(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[PreviewOut]:
    doc, td = _get(db, ctx, document_id)
    try:
        rows = service.build_rows(db, ctx.organization_id, doc, td)
    except PostingError as exc:
        raise http_error(exc) from None
    code = _codes(db, {r.line.debit_account_id for r in rows} | {r.line.credit_account_id for r in rows})
    return [PreviewOut(entry_date=r.line.entry_date or doc.doc_date, debit_account=code[r.line.debit_account_id],
                       credit_account=code[r.line.credit_account_id], amount=r.line.amount, source_ref=r.source_ref)
            for r in rows]


@router.post("/docs/{document_id}/post", response_model=PostResult)
def post(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> PostResult:
    ctx.require(POSTING_ROLES)
    doc, td = _get(db, ctx, document_id)
    try:
        created = service.post_treasury(db, ctx.organization_id, doc, td, ctx.user.id)
        warnings = check_document(db, ctx.organization_id, document_id) if td.kind in service.LINE_DOCS else []
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return PostResult(entries=[EntryLineOut.model_validate(e) for e in created], warnings=warnings_out(warnings))


@router.post("/docs/{document_id}/unpost", status_code=status.HTTP_204_NO_CONTENT)
def unpost(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(POSTING_ROLES)
    _get(db, ctx, document_id)
    try:
        unpost_document(db, organization_id=ctx.organization_id, document_id=document_id, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()


@router.get("/docs/{document_id}/entries", response_model=list[EntryOut])
def entries(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[EntryOut]:
    _get(db, ctx, document_id)
    rows = db.scalars(select(EntryLine).where(EntryLine.organization_id == ctx.organization_id,
                                              EntryLine.document_id == document_id).order_by(EntryLine.line_no)).all()
    code = _codes(db, {r.debit_account_id for r in rows} | {r.credit_account_id for r in rows})
    return [EntryOut(entry_date=r.entry_date, debit_account=code[r.debit_account_id],
                     credit_account=code[r.credit_account_id], amount=r.amount, description=r.description) for r in rows]


class BalanceOut(BaseModel):
    balance: Decimal


@router.get("/cash-balance", response_model=BalanceOut)
def cash_balance(on_date: date = Query(default_factory=date.today), ctx: OrgContext = Depends(get_org_context),
                 db: Session = Depends(get_db)) -> BalanceOut:
    """Soldul casei (cont 241) la o dată."""
    return BalanceOut(balance=service.cash_balance(db, ctx.organization_id, on_date))


@router.get("/advance-balance", response_model=BalanceOut)
def advance_balance(person_id: uuid.UUID, account_id: uuid.UUID, on_date: date = Query(default_factory=date.today),
                    ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> BalanceOut:
    """Cât are de justificat persoana pe contul de avans (sold debitor)."""
    _owned(db, Person, ctx.organization_id, {person_id}, "Persoana")
    _owned(db, Account, ctx.organization_id, {account_id}, "Contul")
    return BalanceOut(balance=service.person_balance(db, ctx.organization_id, person_id, account_id, on_date))
