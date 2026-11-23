"""Mijloace fixe (din factură, punere în funcțiune, casare), ajustarea perioadei, tipuri de calcul,
surse de documente, cataloage (subdiviziuni, contrapartide), finanțare primită, achiziții pe granturi."""

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account, Counterparty, Department
from app.core.db import get_db
from app.core.enums import DocumentType, LineKind, SubcontoType
from app.documents.models import Document, Invoice, InvoiceLine
from app.fix6.models import DocumentSource, FixedAssetEvent, PayrollCalcType, PeriodAdjustment
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, Donor, Grant, GrantTranche
from app.month_close.depreciation import accumulated
from app.payroll.models import Contract
from app.posting.engine import AnalyticsInput, LineInput, PostingError, post_document, unpost_document
from app.posting.models import EntryLine
from app.posting.router import http_error

router = APIRouter(prefix="/organizations/{organization_id}", tags=["ecrane complete"])


def _422(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def _audit(db: Session, ctx: OrgContext, action: str, entity: str, entity_id, old=None, new=None) -> None:
    write_audit(db, action=action, entity=entity, entity_id=entity_id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, old_values=old, new_values=new)  # fmt: skip


# ───────────── mijloace fixe din factură ─────────────


class AssetInvoiceLineOut(BaseModel):
    invoice_line_id: uuid.UUID
    document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    counterparty: str | None
    is_posted: bool
    description: str
    amount: Decimal
    put_into_use: bool | None
    fixed_asset_id: uuid.UUID | None
    inventory_no: str | None
    asset_status: str | None


@router.get("/fixed-assets/invoice-lines", response_model=list[AssetInvoiceLineOut])
def asset_invoice_lines(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Rândurile „mijloc fix” ale facturilor primite și fișele create din ele."""
    rows = db.execute(
        select(InvoiceLine, Document, Counterparty.name, FixedAsset)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Document, Document.id == Invoice.document_id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .outerjoin(FixedAsset, FixedAsset.id == InvoiceLine.fixed_asset_id)
        .where(
            Document.organization_id == ctx.organization_id,
            InvoiceLine.line_kind == LineKind.fixed_asset,
            Document.deletion_mark.is_not(True),
        )
        .order_by(Document.doc_date.desc(), InvoiceLine.position)
    ).all()
    return [
        AssetInvoiceLineOut(
            invoice_line_id=line.id, document_id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date,
            counterparty=cp, is_posted=bool(doc.is_posted), description=line.description, amount=line.amount,
            put_into_use=line.put_into_use, fixed_asset_id=asset.id if asset else None,
            inventory_no=asset.inventory_no if asset else None, asset_status=asset.status if asset else None,
        )
        for line, doc, cp, asset in rows
    ]  # fmt: skip


# ───────────── punere în funcțiune și casare ─────────────


class AssetEventOut(BaseModel):
    id: uuid.UUID
    fixed_asset_id: uuid.UUID
    inventory_no: str
    asset_name: str
    kind: str
    event_date: date
    status: str
    reason: str | None
    amount: Decimal | None
    document_id: uuid.UUID | None


class CommissioningIn(BaseModel):
    commissioning_date: date
    useful_life_months: int | None = Field(default=None, gt=0, le=1200)
    note: str | None = None


class WriteoffIn(BaseModel):
    writeoff_date: date
    reason: str = Field(min_length=3)
    loss_account_id: uuid.UUID | None = None


def _event_out(e: FixedAssetEvent, a: FixedAsset) -> AssetEventOut:
    return AssetEventOut(
        id=e.id, fixed_asset_id=a.id, inventory_no=a.inventory_no, asset_name=a.name, kind=e.kind,
        event_date=e.event_date, status=e.status, reason=e.reason, amount=e.amount, document_id=e.document_id,
    )  # fmt: skip


def _asset(db: Session, ctx: OrgContext, asset_id: uuid.UUID) -> FixedAsset:
    asset = db.scalar(
        select(FixedAsset)
        .where(FixedAsset.id == asset_id, FixedAsset.organization_id == ctx.organization_id)
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fișa nu a fost găsită")
    return asset


def _next_month(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1)


@router.get("/fixed-asset-events", response_model=list[AssetEventOut])
def list_asset_events(kind: str | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    query = (
        select(FixedAssetEvent, FixedAsset)
        .join(FixedAsset, FixedAsset.id == FixedAssetEvent.fixed_asset_id)
        .where(FixedAssetEvent.organization_id == ctx.organization_id)
        .order_by(FixedAssetEvent.event_date.desc(), FixedAssetEvent.created_at.desc())
    )
    if kind:
        query = query.where(FixedAssetEvent.kind == kind)
    return [_event_out(e, a) for e, a in db.execute(query).all()]


@router.post("/fixed-assets/{asset_id}/commissioning", response_model=AssetEventOut, status_code=201)
def commission_asset(asset_id: uuid.UUID, body: CommissioningIn, ctx: OrgContext = Depends(get_org_context),
                     db: Session = Depends(get_db)):  # fmt: skip
    """Punerea în funcțiune: fișa devine „în funcțiune”, amortizarea începe din luna următoare."""
    ctx.require(POSTING_ROLES)
    asset = _asset(db, ctx, asset_id)
    if asset.status == "in_use":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mijlocul fix este deja în funcțiune")
    if asset.status != "suspended":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mijlocul fix a fost casat și nu mai poate fi pus în funcțiune")
    if body.commissioning_date > date.today():
        raise _422("Data punerii în funcțiune nu poate fi în viitor")
    inv_doc = db.get(Document, asset.document_id) if asset.document_id else None
    if inv_doc and inv_doc.doc_date and body.commissioning_date < inv_doc.doc_date:
        raise _422("Data punerii în funcțiune nu poate precede data facturii")
    life = body.useful_life_months or asset.useful_life_months
    if not life:
        raise _422("Indicați durata de utilizare în luni")
    asset.useful_life_months = life
    asset.commissioning_date = body.commissioning_date
    asset.depreciation_start = _next_month(body.commissioning_date)
    asset.status = "in_use"
    event = FixedAssetEvent(
        organization_id=ctx.organization_id, fixed_asset_id=asset.id, kind="commissioning",
        event_date=body.commissioning_date, reason=body.note, previous_status="suspended", created_by=ctx.user.id,
    )  # fmt: skip
    db.add(event)
    db.flush()
    _audit(db, ctx, "create", "fixed_asset_events", event.id, new={"kind": "commissioning", "asset": asset.inventory_no})
    db.commit()
    return _event_out(event, asset)


def _event(db: Session, ctx: OrgContext, event_id: uuid.UUID, kind: str) -> FixedAssetEvent:
    event = db.scalar(
        select(FixedAssetEvent)
        .where(FixedAssetEvent.id == event_id, FixedAssetEvent.organization_id == ctx.organization_id,
               FixedAssetEvent.kind == kind)
        .with_for_update()
    )  # fmt: skip
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul nu a fost găsit")
    if event.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este deja anulat")
    return event


@router.post("/fixed-asset-events/{event_id}/cancel-commissioning", response_model=AssetEventOut)
def cancel_commissioning(event_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    event = _event(db, ctx, event_id, "commissioning")
    asset = _asset(db, ctx, event.fixed_asset_id)
    if asset.status != "in_use":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mijlocul fix nu mai este în funcțiune (casat)")
    if accumulated(db, ctx.organization_id, [asset.id]).get(asset.id, Decimal(0)) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pentru acest mijloc fix s-a calculat deja amortizarea; anulați întâi amortizarea")
    asset.status = "suspended"
    asset.commissioning_date = None
    asset.depreciation_start = None
    event.status = "cancelled"
    _audit(db, ctx, "update", "fixed_asset_events", event.id, old={"status": "posted"}, new={"status": "cancelled"})
    db.commit()
    return _event_out(event, asset)


@router.post("/fixed-assets/{asset_id}/writeoff", response_model=AssetEventOut, status_code=201)
def writeoff_asset(asset_id: uuid.UUID, body: WriteoffIn, ctx: OrgContext = Depends(get_org_context),
                   db: Session = Depends(get_db)):  # fmt: skip
    """Casarea: Dt amortizarea acumulată — Kt mijlocul fix; valoarea de bilanț rămasă — Dt contul de pierderi."""
    ctx.require(POSTING_ROLES)
    asset = _asset(db, ctx, asset_id)
    if asset.status == "written_off":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mijlocul fix este deja casat")
    if body.writeoff_date > date.today():
        raise _422("Data casării nu poate fi în viitor")
    if asset.commissioning_date and body.writeoff_date < asset.commissioning_date:
        raise _422("Data casării nu poate precede punerea în funcțiune")
    if not asset.account_id:
        raise _422("Fișa nu are contul mijlocului fix; completați-l înainte de casare")
    acc = accumulated(db, ctx.organization_id, [asset.id]).get(asset.id, Decimal(0))
    book = asset.initial_cost - acc
    if acc > 0 and not asset.depreciation_account_id:
        raise _422("Fișa nu are contul amortizării")
    if book > 0 and body.loss_account_id is None:
        raise _422("Alegeți contul de cheltuieli pentru valoarea de bilanț rămasă")
    if body.loss_account_id and db.scalar(
        select(Account.id).where(Account.id == body.loss_account_id, Account.organization_id == ctx.organization_id)
    ) is None:
        raise _422("Contul nu aparține organizației")

    doc = Document(organization_id=ctx.organization_id, type=DocumentType.other, doc_number=f"CAS-{asset.inventory_no}",
                   doc_date=body.writeoff_date, total_amount=asset.initial_cost, uploaded_by=ctx.user.id)  # fmt: skip
    db.add(doc)
    db.flush()
    asset_side = AnalyticsInput("K", SubcontoType.fixed_asset, asset.id)
    lines: list[LineInput] = []
    common = dict(grant_id=asset.grant_id, description=f"Casare {asset.inventory_no} {asset.name}")
    if acc > 0:
        lines.append(LineInput(asset.depreciation_account_id, asset.account_id, acc, **common,
                               analytics=[AnalyticsInput("D", SubcontoType.fixed_asset, asset.id)]))  # fmt: skip
    if book > 0:
        lines.append(LineInput(body.loss_account_id, asset.account_id, book, **common, analytics=[asset_side]))
    try:
        post_document(db, organization_id=ctx.organization_id, document_id=doc.id, lines=lines, user_id=ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    event = FixedAssetEvent(
        organization_id=ctx.organization_id, fixed_asset_id=asset.id, kind="writeoff", event_date=body.writeoff_date,
        reason=body.reason, document_id=doc.id, loss_account_id=body.loss_account_id, amount=book,
        previous_status=asset.status, created_by=ctx.user.id,
    )  # fmt: skip
    asset.status = "written_off"
    db.add(event)
    db.flush()
    _audit(db, ctx, "create", "fixed_asset_events", event.id, new={"kind": "writeoff", "asset": asset.inventory_no})
    db.commit()
    return _event_out(event, asset)


@router.post("/fixed-asset-events/{event_id}/cancel-writeoff", response_model=AssetEventOut)
def cancel_writeoff(event_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    event = _event(db, ctx, event_id, "writeoff")
    asset = _asset(db, ctx, event.fixed_asset_id)
    try:
        if event.document_id:
            unpost_document(db, organization_id=ctx.organization_id, document_id=event.document_id, user_id=ctx.user.id)
            doc = db.get(Document, event.document_id)
            doc.deletion_mark = True
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    asset.status = event.previous_status or "in_use"
    event.status = "cancelled"
    _audit(db, ctx, "update", "fixed_asset_events", event.id, old={"status": "posted"}, new={"status": "cancelled"})
    db.commit()
    return _event_out(event, asset)


# ───────────── ajustarea perioadei ─────────────


class AdjustmentIn(BaseModel):
    adjustment_date: date
    description: str = Field(min_length=3)
    debit_account_id: uuid.UUID
    credit_account_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    grant_id: uuid.UUID | None = None
    reverse_next_month: bool = False


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    adjustment_date: date
    description: str
    debit_account: str
    credit_account: str
    amount: Decimal
    grant_id: uuid.UUID | None
    status: str
    reversal_date: date | None
    document_id: uuid.UUID | None


def _adjustment_out(db: Session, a: PeriodAdjustment) -> AdjustmentOut:
    codes = dict(db.execute(select(Account.id, Account.code).where(Account.id.in_([a.debit_account_id, a.credit_account_id]))).all())
    rev = db.get(Document, a.reversal_document_id) if a.reversal_document_id else None
    return AdjustmentOut(
        id=a.id, adjustment_date=a.adjustment_date, description=a.description,
        debit_account=codes[a.debit_account_id], credit_account=codes[a.credit_account_id], amount=a.amount,
        grant_id=a.grant_id, status=a.status, reversal_date=rev.doc_date if rev else None, document_id=a.document_id,
    )  # fmt: skip


@router.get("/period-adjustments", response_model=list[AdjustmentOut])
def list_adjustments(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PeriodAdjustment)
        .where(PeriodAdjustment.organization_id == ctx.organization_id)
        .order_by(PeriodAdjustment.adjustment_date.desc(), PeriodAdjustment.created_at.desc())
    )
    return [_adjustment_out(db, a) for a in rows]


def _post_adjustment(db, ctx, a: PeriodAdjustment, on: date, debit, credit, label: str) -> Document:
    doc = Document(organization_id=ctx.organization_id, type=DocumentType.other, doc_number=f"AJ-{on:%Y%m%d}-{str(a.id)[:4]}",
                   doc_date=on, total_amount=a.amount, uploaded_by=ctx.user.id)  # fmt: skip
    db.add(doc)
    db.flush()
    post_document(db, organization_id=ctx.organization_id, document_id=doc.id, user_id=ctx.user.id,
                  lines=[LineInput(debit, credit, a.amount, grant_id=a.grant_id, description=f"{label}: {a.description}")])  # fmt: skip
    return doc


@router.post("/period-adjustments", response_model=AdjustmentOut, status_code=201)
def create_adjustment(body: AdjustmentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    if body.debit_account_id == body.credit_account_id:
        raise _422("Contul debitor și cel creditor trebuie să fie diferite")
    if body.grant_id and db.scalar(select(Grant.id).where(Grant.id == body.grant_id, Grant.organization_id == ctx.organization_id)) is None:
        raise _422("Grantul nu aparține organizației")
    a = PeriodAdjustment(organization_id=ctx.organization_id, created_by=ctx.user.id,
                         **body.model_dump(exclude={"reverse_next_month"}))  # fmt: skip
    db.add(a)
    db.flush()
    try:
        a.document_id = _post_adjustment(db, ctx, a, a.adjustment_date, a.debit_account_id, a.credit_account_id, "Ajustare").id
        if body.reverse_next_month:
            a.reversal_document_id = _post_adjustment(
                db, ctx, a, _next_month(a.adjustment_date), a.credit_account_id, a.debit_account_id, "Stornare ajustare"
            ).id
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    _audit(db, ctx, "create", "period_adjustments", a.id, new={"amount": str(a.amount), "date": str(a.adjustment_date)})
    db.commit()
    return _adjustment_out(db, a)


@router.post("/period-adjustments/{adjustment_id}/cancel", response_model=AdjustmentOut)
def cancel_adjustment(adjustment_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    a = db.scalar(select(PeriodAdjustment).where(PeriodAdjustment.id == adjustment_id,
                  PeriodAdjustment.organization_id == ctx.organization_id).with_for_update())  # fmt: skip
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ajustarea nu a fost găsită")
    if a.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Ajustarea este deja anulată")
    try:
        for doc_id in (a.document_id, a.reversal_document_id):
            if doc_id:
                unpost_document(db, organization_id=ctx.organization_id, document_id=doc_id, user_id=ctx.user.id)
                db.get(Document, doc_id).deletion_mark = True
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    a.status = "cancelled"
    _audit(db, ctx, "update", "period_adjustments", a.id, old={"status": "posted"}, new={"status": "cancelled"})
    db.commit()
    return _adjustment_out(db, a)


# ───────────── tipuri de calcul salarial ─────────────

STANDARD_CALC_TYPES = [
    ("SAL", "Salariu de bază", "accrual", True, True),
    ("PRM", "Prima", "accrual", True, True),
    ("CO", "Concediu de odihnă", "accrual", True, True),
    ("BOL", "Indemnizație de boală (angajator)", "accrual", True, True),
    ("IVS", "Impozit pe venit", "deduction", False, False),
    ("CNAS", "Contribuție de asigurări sociale", "deduction", False, False),
    ("AOAM", "Prima de asigurare medicală", "deduction", False, False),
    ("PAL", "Pensie alimentară", "deduction", False, False),
]


class CalcTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2)
    kind: str
    taxable: bool = True
    social_base: bool = True
    is_active: bool = True

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("accrual", "deduction"):
            raise ValueError("Tipul trebuie să fie „accrual” (câștig) sau „deduction” (rețineri)")
        return v

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return v.strip().upper()


class CalcTypeOut(CalcTypeIn):
    id: uuid.UUID
    model_config = {"from_attributes": True}


@router.get("/payroll-calc-types", response_model=list[CalcTypeOut])
def list_calc_types(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return list(db.scalars(select(PayrollCalcType).where(PayrollCalcType.organization_id == ctx.organization_id)
                           .order_by(PayrollCalcType.kind, PayrollCalcType.code)))  # fmt: skip


def _calc_dupe(db: Session, ctx: OrgContext, code: str, except_id: uuid.UUID | None = None) -> None:
    q = select(PayrollCalcType.id).where(PayrollCalcType.organization_id == ctx.organization_id, PayrollCalcType.code == code)
    if except_id:
        q = q.where(PayrollCalcType.id != except_id)
    if db.scalar(q):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Codul „{code}” există deja")


@router.post("/payroll-calc-types", response_model=CalcTypeOut, status_code=201)
def create_calc_type(body: CalcTypeIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    _calc_dupe(db, ctx, body.code)
    row = PayrollCalcType(organization_id=ctx.organization_id, **body.model_dump())
    db.add(row)
    db.flush()
    _audit(db, ctx, "create", "payroll_calc_types", row.id, new=body.model_dump())
    db.commit()
    return row


@router.post("/payroll-calc-types/standard", response_model=list[CalcTypeOut], status_code=201)
def add_standard_calc_types(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Adaugă tipurile uzuale care lipsesc (după cod); cele existente rămân neschimbate."""
    ctx.require(ADMIN_ROLES)
    have = set(db.scalars(select(PayrollCalcType.code).where(PayrollCalcType.organization_id == ctx.organization_id)))
    for code, name, kind, taxable, social in STANDARD_CALC_TYPES:
        if code not in have:
            db.add(PayrollCalcType(organization_id=ctx.organization_id, code=code, name=name, kind=kind,
                                   taxable=taxable, social_base=social))  # fmt: skip
    db.commit()
    return list_calc_types(ctx, db)


@router.put("/payroll-calc-types/{type_id}", response_model=CalcTypeOut)
def update_calc_type(type_id: uuid.UUID, body: CalcTypeIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    row = db.scalar(select(PayrollCalcType).where(PayrollCalcType.id == type_id, PayrollCalcType.organization_id == ctx.organization_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tipul de calcul nu a fost găsit")
    _calc_dupe(db, ctx, body.code, row.id)
    old = {k: getattr(row, k) for k in body.model_dump()}
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    _audit(db, ctx, "update", "payroll_calc_types", row.id, old=old, new=body.model_dump())
    db.commit()
    return row


@router.delete("/payroll-calc-types/{type_id}", status_code=204)
def delete_calc_type(type_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    row = db.scalar(select(PayrollCalcType).where(PayrollCalcType.id == type_id, PayrollCalcType.organization_id == ctx.organization_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tipul de calcul nu a fost găsit")
    db.delete(row)
    _audit(db, ctx, "delete", "payroll_calc_types", row.id, old={"code": row.code})
    db.commit()


# ───────────── surse de documente ─────────────

DRIVE_RE = re.compile(r"^https://drive\.google\.com/drive/(u/\d+/)?folders/[\w-]{10,}(\?.*)?$")


class SourceIn(BaseModel):
    kind: str
    name: str = Field(min_length=2)
    location: str = Field(min_length=1)
    note: str | None = None
    is_active: bool = True

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("google_drive", "local_agent", "server_folder"):
            raise ValueError("Tip de sursă necunoscut")
        return v

    @field_validator("location")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class SourceOut(SourceIn):
    id: uuid.UUID
    documents: int = 0


def _check_source(body: SourceIn) -> None:
    if body.kind == "google_drive" and not DRIVE_RE.match(body.location):
        raise _422("Linkul trebuie să fie al unui folder Google Drive (https://drive.google.com/drive/folders/…)")
    if body.kind in ("local_agent", "server_folder"):
        if ".." in body.location.replace("\\", "/").split("/"):
            raise _422("Calea nu poate conține „..”")
        if body.kind == "server_folder" and not body.location.startswith("/"):
            raise _422("Folderul de pe server se scrie cu cale absolută (începe cu „/”)")


def _source_out(db: Session, s: DocumentSource) -> SourceOut:
    from app.fix6.models import ScannedFile

    n = db.scalar(select(func.count()).select_from(ScannedFile).where(ScannedFile.source_id == s.id)) or 0
    return SourceOut(id=s.id, kind=s.kind, name=s.name, location=s.location, note=s.note, is_active=s.is_active, documents=n)


@router.get("/document-sources", response_model=list[SourceOut])
def list_sources(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentSource).where(DocumentSource.organization_id == ctx.organization_id).order_by(DocumentSource.name))
    return [_source_out(db, s) for s in rows]


@router.post("/document-sources", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    _check_source(body)
    s = DocumentSource(organization_id=ctx.organization_id, **body.model_dump())
    db.add(s)
    db.flush()
    _audit(db, ctx, "create", "document_sources", s.id, new={"kind": s.kind, "name": s.name})
    db.commit()
    return _source_out(db, s)


def _source(db: Session, ctx: OrgContext, source_id: uuid.UUID) -> DocumentSource:
    s = db.scalar(select(DocumentSource).where(DocumentSource.id == source_id, DocumentSource.organization_id == ctx.organization_id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sursa nu a fost găsită")
    return s


@router.put("/document-sources/{source_id}", response_model=SourceOut)
def update_source(source_id: uuid.UUID, body: SourceIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    _check_source(body)
    s = _source(db, ctx, source_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    _audit(db, ctx, "update", "document_sources", s.id, new=body.model_dump())
    db.commit()
    return _source_out(db, s)


@router.delete("/document-sources/{source_id}", status_code=204)
def delete_source(source_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    s = _source(db, ctx, source_id)
    if _source_out(db, s).documents:
        raise HTTPException(status.HTTP_409_CONFLICT, "Din această sursă există documente încărcate; dezactivați sursa în loc să o ștergeți")
    db.delete(s)
    _audit(db, ctx, "delete", "document_sources", s.id, old={"name": s.name})
    db.commit()


# ───────────── subdiviziuni ─────────────


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2)
    parent_id: uuid.UUID | None = None
    cuatm: str | None = Field(default=None, pattern=r"^\d{7}$")


class DepartmentOut(DepartmentIn):
    id: uuid.UUID
    model_config = {"from_attributes": True}


def _dept(db: Session, ctx: OrgContext, dept_id: uuid.UUID) -> Department:
    d = db.scalar(select(Department).where(Department.id == dept_id, Department.organization_id == ctx.organization_id))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subdiviziunea nu a fost găsită")
    return d


def _check_parent(db: Session, ctx: OrgContext, parent_id: uuid.UUID | None, self_id: uuid.UUID | None) -> None:
    if parent_id is None:
        return
    parent = _dept(db, ctx, parent_id) if db.scalar(select(Department.id).where(Department.id == parent_id, Department.organization_id == ctx.organization_id)) else None
    if parent is None:
        raise _422("Subdiviziunea superioară nu aparține organizației")
    node = parent
    while node is not None:  # fără cicluri
        if self_id is not None and node.id == self_id:
            raise _422("Subdiviziunea nu poate fi inclusă în propria ierarhie")
        node = db.get(Department, node.parent_id) if node.parent_id else None


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return list(db.scalars(select(Department).where(Department.organization_id == ctx.organization_id).order_by(Department.name)))


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    _check_parent(db, ctx, body.parent_id, None)
    if db.scalar(select(Department.id).where(Department.organization_id == ctx.organization_id, func.lower(Department.name) == body.name.strip().lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Există deja o subdiviziune cu această denumire")
    d = Department(organization_id=ctx.organization_id, **body.model_dump())
    d.name = d.name.strip()
    db.add(d)
    db.flush()
    _audit(db, ctx, "create", "departments", d.id, new=body.model_dump(mode="json"))
    db.commit()
    return d


@router.put("/departments/{dept_id}", response_model=DepartmentOut)
def update_department(dept_id: uuid.UUID, body: DepartmentIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    d = _dept(db, ctx, dept_id)
    _check_parent(db, ctx, body.parent_id, d.id)
    d.name, d.parent_id, d.cuatm = body.name.strip(), body.parent_id, body.cuatm
    _audit(db, ctx, "update", "departments", d.id, new=body.model_dump(mode="json"))
    db.commit()
    return d


@router.delete("/departments/{dept_id}", status_code=204)
def delete_department(dept_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    d = _dept(db, ctx, dept_id)
    used = (
        db.scalar(select(exists().where(Department.parent_id == d.id)))
        or db.scalar(select(exists().where(EntryLine.department_id == d.id)))
        or db.scalar(select(exists().where(FixedAsset.department_id == d.id)))
    )
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Subdiviziunea are subordonate sau înregistrări; nu se poate șterge")
    db.delete(d)
    _audit(db, ctx, "delete", "departments", d.id, old={"name": d.name})
    db.commit()


# ───────────── contrapartide: editare și ștergere ─────────────


class CounterpartyEdit(BaseModel):
    name: str = Field(min_length=1)
    idno: str | None = Field(default=None, pattern=r"^\d{13}$")
    vat_code: str | None = None
    bank_code: str | None = None
    address: str | None = None


def _cp(db: Session, ctx: OrgContext, cp_id: uuid.UUID) -> Counterparty:
    cp = db.scalar(select(Counterparty).where(Counterparty.id == cp_id, Counterparty.organization_id == ctx.organization_id))
    if cp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contrapartida nu a fost găsită")
    return cp


@router.put("/counterparties/{cp_id}", response_model=CounterpartyEdit)
def update_counterparty(cp_id: uuid.UUID, body: CounterpartyEdit, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    cp = _cp(db, ctx, cp_id)
    if body.idno and db.scalar(select(Counterparty.id).where(Counterparty.organization_id == ctx.organization_id,
                                                              Counterparty.idno == body.idno, Counterparty.id != cp.id)):  # fmt: skip
        raise HTTPException(status.HTTP_409_CONFLICT, "Contrapartida cu acest IDNO există deja")
    for k, v in body.model_dump().items():
        setattr(cp, k, v)
    _audit(db, ctx, "update", "counterparties", cp.id, new=body.model_dump())
    db.commit()
    return body


@router.delete("/counterparties/{cp_id}", status_code=204)
def delete_counterparty(cp_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    cp = _cp(db, ctx, cp_id)
    if db.scalar(select(exists().where(Document.counterparty_id == cp.id))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Contrapartida apare în documente; nu se poate șterge")
    db.delete(cp)
    _audit(db, ctx, "delete", "counterparties", cp.id, old={"name": cp.name})
    db.commit()


# ───────────── finanțare primită: toate tranșele ─────────────


class TrancheRowOut(BaseModel):
    id: uuid.UUID
    grant_id: uuid.UUID
    grant_code: str
    donor_id: uuid.UUID | None
    donor_name: str | None
    number: int
    planned_date: date | None
    amount: Decimal
    currency: str
    status: str
    received_document_id: uuid.UUID | None
    received_date: date | None


@router.get("/tranches", response_model=list[TrancheRowOut])
def list_all_tranches(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    rows = db.execute(
        select(GrantTranche, Grant.code, Donor.name, Document.doc_date)
        .join(Grant, Grant.id == GrantTranche.grant_id)
        .outerjoin(Donor, Donor.id == GrantTranche.donor_id)
        .outerjoin(Document, Document.id == GrantTranche.received_document_id)
        .where(Grant.organization_id == ctx.organization_id)
        .order_by(GrantTranche.planned_date.nulls_last(), Grant.code, GrantTranche.number)
    ).all()
    return [
        TrancheRowOut(id=t.id, grant_id=t.grant_id, grant_code=code, donor_id=t.donor_id, donor_name=donor,
                      number=t.number, planned_date=t.planned_date, amount=t.amount, currency=t.currency,
                      status=t.status or "planned", received_document_id=t.received_document_id, received_date=rdate)
        for t, code, donor, rdate in rows
    ]  # fmt: skip


# ───────────── achiziții pe granturi ─────────────


class GrantPurchaseOut(BaseModel):
    grant_id: uuid.UUID
    grant_code: str
    budget_line: str
    document_id: uuid.UUID
    doc_number: str | None
    doc_date: date | None
    counterparty: str | None
    description: str
    line_kind: str
    amount: Decimal


@router.get("/reports/grant-purchases", response_model=list[GrantPurchaseOut])
def grant_purchases(grant_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                    ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):  # fmt: skip
    """Rândurile facturilor înregistrate, pe grant și linie de buget."""
    if date_from and date_to and date_from > date_to:
        raise _422("Data de început depășește data de sfârșit")
    q = (
        select(InvoiceLine, Document, Counterparty.name, BudgetLine, Grant)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Document, Document.id == Invoice.document_id)
        .join(BudgetLine, BudgetLine.id == InvoiceLine.budget_line_id)
        .join(Grant, Grant.id == BudgetLine.grant_id)
        .outerjoin(Counterparty, Counterparty.id == Document.counterparty_id)
        .where(Document.organization_id == ctx.organization_id, Document.is_posted.is_(True),
               Document.deletion_mark.is_not(True))
        .order_by(Grant.code, BudgetLine.code, Document.doc_date, InvoiceLine.position)
    )  # fmt: skip
    if grant_id:
        q = q.where(Grant.id == grant_id)
    if date_from:
        q = q.where(Document.doc_date >= date_from)
    if date_to:
        q = q.where(Document.doc_date <= date_to)
    return [
        GrantPurchaseOut(grant_id=g.id, grant_code=g.code, budget_line=f"{bl.code} {bl.name}", document_id=doc.id,
                         doc_number=doc.doc_number, doc_date=doc.doc_date, counterparty=cp, description=line.description,
                         line_kind=line.line_kind.value, amount=line.amount)
        for line, doc, cp, bl, g in db.execute(q).all()
    ]  # fmt: skip
