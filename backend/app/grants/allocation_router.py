"""Pasul „Repartizarea pe granturi”: previzualizare și executare cu parametri (contul, coeficienții).

Anularea și starea pasului folosesc rutele generice `/month-close/{an}/{luna}/steps/grant_allocation/...`."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.grants.allocation import AllocationParams
from app.month_close.router import MonthCloseOut, StepPreviewOut, StepRowOut, _month_close_out
from app.month_close.service import preview_step, run_step
from app.posting.engine import PostingError
from app.posting.router import http_error

router = APIRouter(prefix="/organizations/{organization_id}", tags=["închiderea lunii"])

STEP = "grant_allocation"


@router.post("/month-close/{year}/{month}/allocation/preview", response_model=StepPreviewOut)
def allocation_preview(
    year: int,
    month: int,
    body: AllocationParams,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> StepPreviewOut:
    try:
        r = preview_step(db, ctx.organization_id, year, month, STEP, body.model_dump(mode="json"))
    except PostingError as exc:
        raise http_error(exc) from None
    return StepPreviewOut(step=STEP, total=r.total, rows=[StepRowOut(**vars(x)) for x in r.rows], errors=r.errors)


@router.post("/month-close/{year}/{month}/allocation/run", response_model=MonthCloseOut)
def allocation_run(
    year: int,
    month: int,
    body: AllocationParams,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> MonthCloseOut:
    ctx.require(POSTING_ROLES)
    try:
        run_step(db, ctx.organization_id, year, month, STEP, ctx.user.id, body.model_dump(mode="json"))
    except PostingError as exc:
        db.rollback()
        raise http_error(exc) from None
    db.commit()
    return _month_close_out(db, ctx, year, month)
