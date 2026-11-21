import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.fixed_assets.models import FixedAsset
from app.month_close.depreciation import DepreciationPlan, accumulated
from app.month_close.service import (
    get_run,
    preview_depreciation,
    preview_step,
    revert_step,
    run_step,
    revert_depreciation,
    run_depreciation,
    steps_view,
)
from app.posting.engine import PostingError
from app.posting.router import http_error

router = APIRouter(prefix="/organizations/{organization_id}", tags=["închiderea lunii"])


class StepOut(BaseModel):
    step: str
    title: str
    implemented: bool
    status: str
    entries: int | None = None
    total: Decimal | None = None
    issues: list[str] = []


class MonthCloseOut(BaseModel):
    year: int
    month: int
    status: str
    document_id: uuid.UUID | None
    steps: list[StepOut]


class DepreciationRowOut(BaseModel):
    fixed_asset_id: uuid.UUID
    inventory_no: str
    name: str
    initial_cost: Decimal
    accumulated_before: Decimal
    amount: Decimal
    debit_account: str | None
    credit_account: str | None
    grant_id: uuid.UUID | None
    source_ref: str | None
    error: str | None


class DepreciationOut(BaseModel):
    year: int
    month: int
    entry_date: date
    total: Decimal
    rows: list[DepreciationRowOut]
    errors: list[str]


def _depreciation_out(db: Session, result: DepreciationPlan) -> DepreciationOut:
    ids = {g.line.debit_account_id for g in result.lines} | {g.line.credit_account_id for g in result.lines}
    code = dict(db.execute(select(Account.id, Account.code).where(Account.id.in_(ids))).all()) if ids else {}
    return DepreciationOut(
        year=result.year,
        month=result.month,
        entry_date=result.entry_date,
        total=result.total,
        errors=result.errors,
        rows=[
            DepreciationRowOut(
                fixed_asset_id=r.asset.id,
                inventory_no=r.asset.inventory_no,
                name=r.asset.name,
                initial_cost=r.asset.initial_cost,
                accumulated_before=r.accumulated_before,
                amount=r.amount,
                debit_account=code.get(r.generated.line.debit_account_id) if r.generated else None,
                credit_account=code.get(r.generated.line.credit_account_id) if r.generated else None,
                grant_id=r.asset.grant_id,
                source_ref=r.generated.rule.source_ref if r.generated else None,
                error=r.error,
            )
            for r in result.rows
        ],
    )


def _month_close_out(db: Session, ctx: OrgContext, year: int, month: int) -> MonthCloseOut:
    run = get_run(db, ctx.organization_id, year, month)
    return MonthCloseOut(
        year=year,
        month=month,
        status=run.status if run and run.status else "draft",
        document_id=run.document_id if run else None,
        steps=[StepOut(**s) for s in steps_view(run)],
    )


@router.get("/month-close/{year}/{month}", response_model=MonthCloseOut)
def month_close(year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return _month_close_out(db, ctx, year, month)


@router.post("/month-close/{year}/{month}/depreciation/preview", response_model=DepreciationOut)
def depreciation_preview(
    year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    try:
        return _depreciation_out(db, preview_depreciation(db, ctx.organization_id, year, month))
    except PostingError as exc:
        raise http_error(exc) from None


@router.post("/month-close/{year}/{month}/depreciation/run", response_model=MonthCloseOut)
def depreciation_run(year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    try:
        run_depreciation(db, ctx.organization_id, year, month, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _month_close_out(db, ctx, year, month)


@router.post("/month-close/{year}/{month}/depreciation/revert", response_model=MonthCloseOut)
def depreciation_revert(
    year: int, month: int, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    ctx.require(POSTING_ROLES)
    try:
        revert_depreciation(db, ctx.organization_id, year, month, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _month_close_out(db, ctx, year, month)


# ───────────── fișele mijloacelor fixe ─────────────


class FixedAssetOut(BaseModel):
    id: uuid.UUID
    inventory_no: str
    name: str
    initial_cost: Decimal
    residual_value: Decimal | None
    useful_life_months: int | None
    asset_group: str | None
    status: str | None
    commissioning_date: date | None
    depreciation_start: date | None
    grant_id: uuid.UUID | None
    budget_line_id: uuid.UUID | None
    expense_account_id: uuid.UUID | None
    document_id: uuid.UUID | None
    accumulated: Decimal
    book_value: Decimal


class FixedAssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    inventory_no: str | None = Field(default=None, min_length=1)
    useful_life_months: int | None = Field(default=None, gt=0, le=1200)
    residual_value: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    asset_group: str | None = None
    expense_account_id: uuid.UUID | None = None
    commissioning_date: date | None = None


def _asset_out(asset: FixedAsset, acc: Decimal) -> FixedAssetOut:
    return FixedAssetOut(
        **{k: getattr(asset, k) for k in FixedAssetOut.model_fields if k not in ("accumulated", "book_value")},
        accumulated=acc,
        book_value=asset.initial_cost - acc,
    )


@router.get("/fixed-assets", response_model=list[FixedAssetOut])
def list_fixed_assets(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[FixedAssetOut]:
    """Fișele MF cu amortizarea acumulată și valoarea de bilanț (din înregistrări)."""
    assets = db.scalars(
        select(FixedAsset).where(FixedAsset.organization_id == ctx.organization_id).order_by(FixedAsset.inventory_no)
    ).all()
    acc = accumulated(db, ctx.organization_id, [a.id for a in assets])
    return [_asset_out(a, acc.get(a.id, Decimal(0))) for a in assets]


@router.patch("/fixed-assets/{asset_id}", response_model=FixedAssetOut)
def update_fixed_asset(
    asset_id: uuid.UUID,
    body: FixedAssetPatch,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> FixedAssetOut:
    """Completarea fișei: durata, valoarea reziduală, grupa, contul de cheltuieli, data punerii în funcțiune."""
    ctx.require(POSTING_ROLES)
    asset = db.scalar(
        select(FixedAsset)
        .where(FixedAsset.id == asset_id, FixedAsset.organization_id == ctx.organization_id)
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fișa nu a fost găsită")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("expense_account_id") and (
        db.scalar(
            select(Account.id).where(
                Account.id == changes["expense_account_id"], Account.organization_id == ctx.organization_id
            )
        )
        is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contul nu aparține organizației")
    if (
        "residual_value" in changes
        and changes["residual_value"] is not None
        and changes["residual_value"] >= asset.initial_cost
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Valoarea reziduală trebuie să fie mai mică decât valoarea inițială"
        )
    old = {k: str(getattr(asset, k)) for k in changes}
    for key, value in changes.items():
        setattr(asset, key, value)
    if "commissioning_date" in changes and asset.commissioning_date:
        # amortizarea începe din luna următoare punerii în funcțiune
        nxt = asset.commissioning_date.replace(day=1)
        asset.depreciation_start = date(nxt.year + nxt.month // 12, nxt.month % 12 + 1, 1)
        asset.status = "in_use"
    db.flush()
    write_audit(
        db,
        action="update",
        entity="fixed_assets",
        entity_id=asset.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values=old,
        new_values={k: str(v) for k, v in changes.items()},
    )
    db.commit()
    return _asset_out(asset, accumulated(db, ctx.organization_id, [asset.id]).get(asset.id, Decimal(0)))


# ───────────── ceilalți pași (venituri, verificări) ─────────────

GENERIC_STEPS = ("fx_difference", "special_purpose_income", "checks")


class StepRowOut(BaseModel):
    label: str
    amount: Decimal
    debit_account: str | None
    credit_account: str | None
    note: str | None


class StepPreviewOut(BaseModel):
    step: str
    total: Decimal
    rows: list[StepRowOut]
    errors: list[str]


def _check_step(step: str) -> None:
    if step not in GENERIC_STEPS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas necunoscut sau neimplementat")


@router.post("/month-close/{year}/{month}/steps/{step}/preview", response_model=StepPreviewOut)
def step_preview(
    year: int, month: int, step: str, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    _check_step(step)
    try:
        r = preview_step(db, ctx.organization_id, year, month, step)
    except PostingError as exc:
        raise http_error(exc) from None
    return StepPreviewOut(step=step, total=r.total, rows=[StepRowOut(**vars(x)) for x in r.rows], errors=r.errors)


@router.post("/month-close/{year}/{month}/steps/{step}/run", response_model=MonthCloseOut)
def step_run(
    year: int, month: int, step: str, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    _check_step(step)
    ctx.require(POSTING_ROLES)
    try:
        run_step(db, ctx.organization_id, year, month, step, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _month_close_out(db, ctx, year, month)


@router.post("/month-close/{year}/{month}/steps/{step}/revert", response_model=MonthCloseOut)
def step_revert(
    year: int, month: int, step: str, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
):
    _check_step(step)
    ctx.require(POSTING_ROLES)
    try:
        revert_step(db, ctx.organization_id, year, month, step, ctx.user.id)
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _month_close_out(db, ctx, year, month)
