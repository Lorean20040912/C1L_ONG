import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.core.db import get_db
from app.grants.budget import BudgetWarning, execution

router = APIRouter(prefix="/organizations/{organization_id}", tags=["granturi"])


class BudgetLineExecutionOut(BaseModel):
    grant_id: uuid.UUID
    grant_code: str
    budget_line_id: uuid.UUID
    code: str
    name: str
    planned: Decimal
    spent: Decimal
    remaining: Decimal
    over: Decimal


class BudgetWarningOut(BaseModel):
    budget_line_id: uuid.UUID
    label: str
    planned: Decimal
    spent: Decimal
    over: Decimal
    message: str


def warnings_out(warnings: list[BudgetWarning]) -> list[BudgetWarningOut]:
    return [
        BudgetWarningOut(
            budget_line_id=w.budget_line_id,
            label=w.label,
            planned=w.planned,
            spent=w.spent,
            over=w.over,
            message=w.message,
        )
        for w in warnings
    ]


@router.get("/budget-execution", response_model=list[BudgetLineExecutionOut])
def budget_execution(
    grant_id: uuid.UUID | None = None,
    date_to: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[BudgetLineExecutionOut]:
    """Execuția bugetului: planificat / cheltuit / rest / depășire pe fiecare linie (ToR F6.2)."""
    return [
        BudgetLineExecutionOut(
            grant_id=r.grant_id,
            grant_code=r.grant_code,
            budget_line_id=r.budget_line_id,
            code=r.code,
            name=r.name,
            planned=r.planned,
            spent=r.spent,
            remaining=r.remaining,
            over=r.over,
        )
        for r in execution(db, ctx.organization_id, grant_id, date_to)
    ]
