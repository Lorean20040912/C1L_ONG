"""Migrarea din 1C: încărcarea exportului XML, rulările, soldurile inițiale, reconcilierea balanței."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import ADMIN_ROLES, OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import ImportStatus
from app.onec_import.models import OnecImportRun, OpeningBalance
from app.onec_import.service import BalanceRow, ImportFormatError, reconcile, run_import
from app.posting.engine import PostingError

router = APIRouter(prefix="/organizations/{organization_id}/onec-import", tags=["import 1C"])

MAX_XML_CHARS = 20_000_000


class ImportIn(BaseModel):
    xml: str = Field(min_length=1, max_length=MAX_XML_CHARS)
    period_from: date | None = None
    period_to: date | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    source: str | None
    period_from: date | None
    period_to: date | None
    status: ImportStatus | None
    stats: dict | None
    reconciliation: dict | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class BalanceIn(BaseModel):
    account_code: str = Field(min_length=1, max_length=10)
    debit: Decimal = Field(default=Decimal(0), ge=0, max_digits=15, decimal_places=2)
    credit: Decimal = Field(default=Decimal(0), ge=0, max_digits=15, decimal_places=2)


class ReconcileIn(BaseModel):
    date: date
    rows: list[BalanceIn]


class OpeningBalanceOut(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    balance_date: date
    debit: Decimal
    credit: Decimal


def _run(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> OnecImportRun:
    run = db.scalar(
        select(OnecImportRun).where(OnecImportRun.id == run_id, OnecImportRun.organization_id == ctx.organization_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rularea nu a fost găsită")
    return run


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def start_import(body: ImportIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> OnecImportRun:
    ctx.require(ADMIN_ROLES)
    try:
        run = run_import(db, organization_id=ctx.organization_id, user_id=ctx.user.id, text=body.xml,
                         period_from=body.period_from, period_to=body.period_to)  # fmt: skip
    except (ImportFormatError, PostingError) as exc:
        db.rollback()
        now = datetime.now()
        db.add(OnecImportRun(organization_id=ctx.organization_id, source="xml", status=ImportStatus.failed,
                             stats={"error": str(exc)}, started_by=ctx.user.id, started_at=now, finished_at=now))  # fmt: skip
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    db.commit()
    return run


@router.get("/runs", response_model=list[RunOut])
def list_runs(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[OnecImportRun]:
    return list(
        db.scalars(
            select(OnecImportRun)
            .where(OnecImportRun.organization_id == ctx.organization_id)
            .order_by(OnecImportRun.started_at.desc())
            .limit(100)
        )
    )


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> OnecImportRun:
    return _run(db, ctx, run_id)


@router.post("/runs/{run_id}/reconcile", response_model=RunOut)
def reconcile_run(
    run_id: uuid.UUID, body: ReconcileIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> OnecImportRun:
    """Compară balanța dată (din 1C) cu cea din aplicație la `date`; rezultatul se păstrează în rulare."""
    ctx.require(ADMIN_ROLES)
    run = _run(db, ctx, run_id)
    rows = [BalanceRow(r.account_code, r.debit, r.credit) for r in body.rows]
    run.reconciliation = reconcile(db, ctx.organization_id, body.date, rows)
    db.commit()
    return run


@router.get("/opening-balances", response_model=list[OpeningBalanceOut])
def opening_balances(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[OpeningBalanceOut]:
    rows = db.execute(
        select(OpeningBalance, Account.code, Account.name)
        .join(Account, Account.id == OpeningBalance.account_id)
        .where(OpeningBalance.organization_id == ctx.organization_id)
        .order_by(OpeningBalance.balance_date, Account.code)
    ).all()
    return [
        OpeningBalanceOut(account_id=b.account_id, account_code=code, account_name=name, balance_date=b.balance_date,
                          debit=b.debit or Decimal(0), credit=b.credit or Decimal(0))  # fmt: skip
        for b, code, name in rows
    ]
