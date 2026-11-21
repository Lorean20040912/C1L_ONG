"""Vizualizarea și corectarea regulilor de înregistrare (docs/11 §6 p.3).

Contabilul-șef poate corecta o formulă pentru organizația sa: corecția e o
regulă nouă cu versiune, autor, motiv și sursă; versiunea anterioară a
aceleiași corecții se închide în ziua dinaintea noii valabilități. Regulile
standard nu se modifică din API.
"""

import re
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import OrgContext, get_org_context
from app.catalogs.models import Account
from app.core.db import get_db
from app.core.enums import UserRole
from app.posting.models import PostingRule
from app.posting.rules import DIMENSIONS, POLICY_ACCOUNTS

router = APIRouter(prefix="/organizations/{organization_id}/posting-rules", tags=["reguli de înregistrare"])

RULE_EDIT_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant})
_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


class RuleOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    document_type: str
    operation: str
    conditions: dict | None
    debit_account: str
    credit_account: str
    analytics: dict | None
    source_ref: str
    valid_from: date
    valid_to: date | None
    version: int | None
    change_reason: str | None

    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    document_type: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    conditions: dict[str, str | int | bool | list[str]] = {}
    debit_account: str = Field(min_length=1)
    credit_account: str = Field(min_length=1)
    analytics: dict = {}
    source_ref: str = Field(min_length=1, description="sursa obligatorie, ex. IM188; ART sit.3; SEM")
    valid_from: date
    change_reason: str = Field(min_length=3)


@router.get("", response_model=list[RuleOut])
def list_rules(
    on_date: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[PostingRule]:
    """Regulile standard și corecțiile organizației (fără variantele beta).
    Cu `on_date`, doar cele valabile la acea dată."""
    query = select(PostingRule).where(
        or_(PostingRule.organization_id.is_(None), PostingRule.organization_id == ctx.organization_id),
        PostingRule.release_id.is_(None),
    )
    if on_date is not None:
        query = query.where(
            PostingRule.valid_from <= on_date,
            or_(PostingRule.valid_to.is_(None), PostingRule.valid_to >= on_date),
        )
    return list(
        db.scalars(
            query.order_by(
                PostingRule.document_type,
                PostingRule.operation,
                PostingRule.organization_id.is_not(None),
                PostingRule.valid_from,
            )
        )
    )


def _check_account(db: Session, organization_id: uuid.UUID, formula: str) -> None:
    placeholder = _PLACEHOLDER.match(formula.strip())
    if placeholder:
        if placeholder.group(1) not in POLICY_ACCOUNTS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Trimitere necunoscută: {formula}")
        return
    exists = db.scalar(select(Account.id).where(Account.organization_id == organization_id, Account.code == formula))
    if exists is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Contul {formula} lipsește din planul de conturi")


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleCreate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> PostingRule:
    ctx.require(RULE_EDIT_ROLES)
    _check_account(db, ctx.organization_id, body.debit_account)
    _check_account(db, ctx.organization_id, body.credit_account)
    unknown = set(body.analytics.get("required", [])) - DIMENSIONS.keys()
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Dimensiuni necunoscute: {', '.join(sorted(unknown))}"
        )

    conditions = body.conditions or None
    # versiunile anterioare ale aceleiași corecții (aceeași operațiune și condiții)
    same_operation = db.scalars(
        select(PostingRule)
        .where(
            PostingRule.organization_id == ctx.organization_id,
            PostingRule.document_type == body.document_type,
            PostingRule.operation == body.operation,
            PostingRule.release_id.is_(None),
        )
        .with_for_update()
    ).all()
    previous = [r for r in same_operation if (r.conditions or {}) == body.conditions]
    if any(old.valid_from >= body.valid_from for old in previous):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Există deja o versiune a corecției valabilă de la această dată sau mai târziu"
        )
    for old in previous:
        if old.valid_to is None or old.valid_to >= body.valid_from:
            old.valid_to = body.valid_from - timedelta(days=1)

    rule = PostingRule(
        organization_id=ctx.organization_id,
        document_type=body.document_type,
        operation=body.operation,
        conditions=conditions,
        debit_account=body.debit_account.strip(),
        credit_account=body.credit_account.strip(),
        analytics=body.analytics or None,
        source_ref=body.source_ref,
        valid_from=body.valid_from,
        version=max((r.version or 1 for r in previous), default=0) + 1,
        changed_by=ctx.user.id,
        change_reason=body.change_reason,
    )
    db.add(rule)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="posting_rules",
        entity_id=rule.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values={"closed_versions": [str(r.id) for r in previous]} if previous else None,
        new_values=body.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(rule)
    return rule
