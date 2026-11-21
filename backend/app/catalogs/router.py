import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import AccountKind

router = APIRouter(prefix="/organizations/{organization_id}", tags=["cataloage"])


class AccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    account_kind: AccountKind
    is_group: bool | None

    model_config = {"from_attributes": True}


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[Account]:
    """Planul de conturi al organizației curente."""
    return list(db.scalars(select(Account).where(Account.organization_id == ctx.organization_id).order_by(Account.code)))
