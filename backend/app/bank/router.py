"""Rutele modulului bancă: profilurile băncilor, importul extraselor, exportul ordinelor, cursul BNM."""

import base64
import binascii
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.bank.models import BANK_FILE_TYPES, BankFormat, BankImport, BankTransaction, ExchangeRate, PaymentBatch
from app.bank.rates import RateError, download_bnm, rate_on, save_rate
from app.bank.service import (
    EXPORT,
    IMPORT,
    BankError,
    PostItem,
    create_batches,
    import_statement,
    import_transactions,
    post_transactions,
)
from app.core.db import get_db
from app.core.enums import PaymentDirection
from app.documents.models import Document, PaymentOrder, PaymentOrderLine

router = APIRouter(prefix="/organizations/{organization_id}", tags=["bancă"])

MAX_FILE_BYTES = 10 * 1024 * 1024


def _error(exc: BankError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


# ───────────────────────── profilurile băncilor ─────────────────────────


class BankFormatIn(BaseModel):
    bank_name: str = Field(min_length=1)
    file_type: str = Field(pattern="^(" + "|".join(BANK_FILE_TYPES) + ")$")
    direction: str = Field(pattern=f"^({IMPORT}|{EXPORT})$")
    encoding: str = "cp1251"
    layout: dict


class BankFormatOut(BankFormatIn):
    id: uuid.UUID
    is_standard: bool
    version: int | None


def _format_out(f: BankFormat) -> BankFormatOut:
    return BankFormatOut(
        id=f.id, bank_name=f.bank_name, file_type=f.file_type, direction=f.direction, encoding=f.encoding or "cp1251",
        layout=f.layout, is_standard=f.organization_id is None, version=f.version,
    )  # fmt: skip


def _check_layout(body: BankFormatIn) -> None:
    try:
        "".encode(body.encoding)
    except LookupError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Codificare necunoscută: {body.encoding}") from None
    key = "parser" if body.direction == IMPORT else "exporter"
    if body.direction == IMPORT and not isinstance(body.layout.get("fields", {}), dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "layout.fields trebuie să fie un obiect")
    if body.direction == EXPORT and body.layout.get(key) != "client_bank_exchange" and not body.layout.get("fields"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Profilul de export nu are câmpuri (layout.fields)")


@router.get("/bank-formats", response_model=list[BankFormatOut])
def list_formats(
    direction: str | None = None, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[BankFormatOut]:
    query = select(BankFormat).where(
        or_(BankFormat.organization_id.is_(None), BankFormat.organization_id == ctx.organization_id)
    )
    if direction:
        query = query.where(BankFormat.direction == direction)
    return [_format_out(f) for f in db.scalars(query.order_by(BankFormat.direction, BankFormat.bank_name))]


@router.post("/bank-formats", response_model=BankFormatOut, status_code=status.HTTP_201_CREATED)
def create_format(
    body: BankFormatIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> BankFormatOut:
    ctx.require(ADMIN_ROLES)
    _check_layout(body)
    fmt = BankFormat(organization_id=ctx.organization_id, **body.model_dump())
    db.add(fmt)
    db.flush()
    write_audit(db, action="create", entity="bank_formats", entity_id=fmt.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values=body.model_dump())  # fmt: skip
    db.commit()
    return _format_out(fmt)


def _own_format(db: Session, ctx: OrgContext, format_id: uuid.UUID) -> BankFormat:
    fmt = db.get(BankFormat, format_id)
    if fmt is None or fmt.organization_id not in (None, ctx.organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profilul nu a fost găsit")
    if fmt.organization_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Profilul standard nu se modifică; creați o copie proprie")
    return fmt


@router.put("/bank-formats/{format_id}", response_model=BankFormatOut)
def update_format(
    format_id: uuid.UUID, body: BankFormatIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> BankFormatOut:
    ctx.require(ADMIN_ROLES)
    fmt = _own_format(db, ctx, format_id)
    _check_layout(body)
    old = _format_out(fmt).model_dump(mode="json")
    for key, value in body.model_dump().items():
        setattr(fmt, key, value)
    fmt.version = (fmt.version or 1) + 1
    write_audit(db, action="update", entity="bank_formats", entity_id=fmt.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, old_values=old, new_values=body.model_dump())  # fmt: skip
    db.commit()
    return _format_out(fmt)


@router.delete("/bank-formats/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_format(format_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(ADMIN_ROLES)
    fmt = _own_format(db, ctx, format_id)
    used = db.scalar(select(BankImport.id).where(BankImport.format_id == fmt.id).limit(1)) or db.scalar(
        select(PaymentBatch.id).where(PaymentBatch.bank_format_id == fmt.id).limit(1)
    )
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Profilul a fost folosit; nu se mai poate șterge")
    db.delete(fmt)
    write_audit(db, action="delete", entity="bank_formats", entity_id=format_id, organization_id=ctx.organization_id,
                user_id=ctx.user.id)  # fmt: skip
    db.commit()


# ───────────────────────── importul extraselor ─────────────────────────


class ImportIn(BaseModel):
    bank_account_id: uuid.UUID
    format_id: uuid.UUID
    file_name: str | None = None
    content_base64: str
    dry_run: bool = Field(default=False, description="doar citește fișierul și arată ce s-ar crea")


class TransactionOut(BaseModel):
    id: uuid.UUID
    tx_date: date
    direction: PaymentDirection
    amount: Decimal
    currency: str | None
    doc_number: str | None
    counterparty_name: str | None
    counterparty_iban: str | None
    counterparty_idno: str | None
    counterparty_id: uuid.UUID | None
    purpose: str | None
    match: str | None
    document_id: uuid.UUID | None
    grant_id: uuid.UUID | None
    is_posted: bool


class ImportOut(BaseModel):
    id: uuid.UUID
    bank_account_id: uuid.UUID
    format_id: uuid.UUID
    file_name: str | None
    rows_total: int | None
    rows_created: int | None
    rows_skipped: int | None
    rows_failed: int | None
    errors: list
    imported_at: datetime | None
    dry_run: bool = False
    transactions: list[TransactionOut] = []


def _transactions_out(db: Session, rows: list[BankTransaction]) -> list[TransactionOut]:
    doc_ids = [tx.document_id for tx in rows if tx.document_id]
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))} if doc_ids else {}
    grants = dict(
        db.execute(
            select(PaymentOrder.document_id, PaymentOrderLine.grant_id)
            .join(PaymentOrderLine, PaymentOrderLine.payment_order_id == PaymentOrder.id)
            .where(PaymentOrder.document_id.in_(doc_ids))
        ).all()
    ) if doc_ids else {}  # fmt: skip
    out = []
    for tx in rows:
        doc = docs.get(tx.document_id)
        out.append(
            TransactionOut(
                id=tx.id, tx_date=tx.tx_date, direction=tx.direction, amount=tx.amount, currency=tx.currency,
                doc_number=tx.doc_number, counterparty_name=tx.counterparty_name,
                counterparty_iban=tx.counterparty_iban, counterparty_idno=tx.counterparty_idno,
                counterparty_id=doc.counterparty_id if doc else None, purpose=tx.purpose, match=tx.match,
                document_id=tx.document_id, grant_id=grants.get(tx.document_id), is_posted=bool(doc and doc.is_posted),
            )  # fmt: skip
        )
    return out


def _import_out(db: Session, record: BankImport, rows: list[BankTransaction], dry_run: bool = False) -> ImportOut:
    return ImportOut(
        id=record.id, bank_account_id=record.bank_account_id, format_id=record.format_id, file_name=record.file_name,
        rows_total=record.rows_total, rows_created=record.rows_created, rows_skipped=record.rows_skipped,
        rows_failed=record.rows_failed, errors=record.errors or [], imported_at=record.imported_at, dry_run=dry_run,
        transactions=_transactions_out(db, rows),
    )  # fmt: skip


@router.post("/bank-imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
def create_import(body: ImportIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> ImportOut:
    ctx.require(POSTING_ROLES)
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Conținutul fișierului nu este base64") from None
    if not data or len(data) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fișierul este gol sau prea mare (max. 10 MB)")
    try:
        outcome = import_statement(
            db, organization_id=ctx.organization_id, bank_account_id=body.bank_account_id, format_id=body.format_id,
            file_name=body.file_name, data=data, user_id=ctx.user.id,
        )  # fmt: skip
        result = _import_out(db, outcome.bank_import, outcome.transactions, dry_run=body.dry_run)
    except BankError as exc:
        db.rollback()
        raise _error(exc) from None
    if body.dry_run:
        db.rollback()
        return result
    write_audit(db, action="create", entity="bank_imports", entity_id=outcome.bank_import.id,
                organization_id=ctx.organization_id, user_id=ctx.user.id,
                new_values={"file_name": body.file_name, "rows_created": outcome.bank_import.rows_created,
                            "rows_skipped": outcome.bank_import.rows_skipped})  # fmt: skip
    db.commit()
    return result


@router.get("/bank-imports", response_model=list[ImportOut])
def list_imports(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[ImportOut]:
    rows = db.scalars(
        select(BankImport)
        .where(BankImport.organization_id == ctx.organization_id)
        .order_by(BankImport.imported_at.desc())
        .limit(200)
    )
    return [_import_out(db, r, []) for r in rows]


@router.get("/bank-imports/{import_id}", response_model=ImportOut)
def get_import(import_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    try:
        record, rows = import_transactions(db, ctx.organization_id, import_id)
    except BankError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return _import_out(db, record, rows)


class PostItemIn(BaseModel):
    transaction_id: uuid.UUID
    grant_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None


class PostIn(BaseModel):
    items: list[PostItemIn] = Field(min_length=1)


class PostResultOut(BaseModel):
    transaction_id: uuid.UUID
    ok: bool
    error: str | None


@router.post("/bank-imports/{import_id}/post", response_model=list[PostResultOut])
def post_import(
    import_id: uuid.UUID, body: PostIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> list[PostResultOut]:
    ctx.require(POSTING_ROLES)
    try:
        results = post_transactions(
            db, ctx.organization_id, import_id, [PostItem(**i.model_dump()) for i in body.items], ctx.user.id
        )
    except BankError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    db.commit()
    return [PostResultOut(transaction_id=k, ok=v is None, error=v) for k, v in results.items()]


# ───────────────────────── exportul ordinelor ─────────────────────────


class BatchIn(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)
    format_id: uuid.UUID
    force: bool = Field(default=False, description="exportă din nou ordinele exportate deja")


class BatchOut(BaseModel):
    id: uuid.UUID
    bank_format_id: uuid.UUID
    bank_account_id: uuid.UUID
    created_at: datetime | None
    folder_path: str | None
    file_name: str | None
    orders_count: int | None
    total_amount: Decimal | None


def _batch_out(b: PaymentBatch) -> BatchOut:
    return BatchOut(
        id=b.id, bank_format_id=b.bank_format_id, bank_account_id=b.bank_account_id, created_at=b.created_at,
        folder_path=b.folder_path, file_name=b.file_id, orders_count=b.orders_count, total_amount=b.total_amount,
    )  # fmt: skip


@router.post("/payment-batches", response_model=list[BatchOut], status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    try:
        batches = create_batches(
            db, organization_id=ctx.organization_id, document_ids=body.document_ids, format_id=body.format_id,
            force=body.force, user_id=ctx.user.id,
        )  # fmt: skip
    except BankError as exc:
        db.rollback()
        raise _error(exc) from None
    for b in batches:
        write_audit(db, action="create", entity="payment_batches", entity_id=b.id, organization_id=ctx.organization_id,
                    user_id=ctx.user.id, new_values={"orders": b.orders_count, "total": str(b.total_amount)})  # fmt: skip
    db.commit()
    return [_batch_out(b) for b in batches]


@router.get("/payment-batches", response_model=list[BatchOut])
def list_batches(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[BatchOut]:
    rows = db.scalars(
        select(PaymentBatch)
        .where(PaymentBatch.organization_id == ctx.organization_id)
        .order_by(PaymentBatch.created_at.desc())
        .limit(200)
    )
    return [_batch_out(b) for b in rows]


@router.get("/payment-batches/{batch_id}/file")
def batch_file(batch_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    batch = db.get(PaymentBatch, batch_id)
    if batch is None or batch.organization_id != ctx.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lotul nu a fost găsit")
    return Response(
        content=batch.content or b"",
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{batch.file_id}"'},
    )


# ───────────────────────── cursul BNM ─────────────────────────


class RateIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate_date: date
    rate: Decimal = Field(gt=0, max_digits=12, decimal_places=4)


class RateOut(RateIn):
    source: str | None


class BnmIn(BaseModel):
    rate_date: date
    currencies: list[str] = Field(default_factory=lambda: ["EUR", "USD"])


@router.get("/exchange-rates", response_model=list[RateOut])
def list_rates(
    currency: str | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[RateOut]:
    query = select(ExchangeRate).where(ExchangeRate.organization_id == ctx.organization_id)
    if currency:
        query = query.where(ExchangeRate.currency == currency.upper())
    if date_from:
        query = query.where(ExchangeRate.rate_date >= date_from)
    if date_to:
        query = query.where(ExchangeRate.rate_date <= date_to)
    rows = db.scalars(query.order_by(ExchangeRate.rate_date.desc(), ExchangeRate.currency).limit(1000))
    return [RateOut(currency=r.currency, rate_date=r.rate_date, rate=r.rate, source=r.source) for r in rows]


@router.get("/exchange-rates/on", response_model=RateOut)
def get_rate(
    currency: str, on: date, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> RateOut:
    r = rate_on(db, ctx.organization_id, currency, on)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nu există curs {currency.upper()} la {on:%d.%m.%Y}")
    return RateOut(currency=r.currency, rate_date=r.rate_date, rate=r.rate, source=r.source)


@router.put("/exchange-rates", response_model=RateOut)
def put_rate(body: RateIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> RateOut:
    ctx.require(POSTING_ROLES)
    save_rate(db, ctx.organization_id, body.currency, body.rate_date, body.rate, "manual")
    write_audit(db, action="update", entity="exchange_rates", organization_id=ctx.organization_id, user_id=ctx.user.id,
                new_values=body.model_dump(mode="json"))  # fmt: skip
    db.commit()
    return RateOut(**{**body.model_dump(), "currency": body.currency.upper()}, source="manual")


@router.post("/exchange-rates/bnm", response_model=list[RateOut])
def fetch_bnm(body: BnmIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[RateOut]:
    ctx.require(POSTING_ROLES)
    try:
        rates = download_bnm(body.rate_date)
    except RateError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    wanted = [c.upper() for c in body.currencies] or sorted(rates)
    out = []
    for code in wanted:
        if code in rates:
            save_rate(db, ctx.organization_id, code, body.rate_date, rates[code], "bnm")
            out.append(RateOut(currency=code, rate_date=body.rate_date, rate=rates[code], source="bnm"))
    write_audit(db, action="update", entity="exchange_rates", organization_id=ctx.organization_id, user_id=ctx.user.id,
                new_values={"bnm": body.rate_date.isoformat(), "currencies": [r.currency for r in out]})  # fmt: skip
    db.commit()
    return out
