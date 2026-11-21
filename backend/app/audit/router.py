"""Jurnalul de audit vizibil: ce s-a schimbat, cine și când (ToR NF1)."""

import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.auth.deps import OrgContext, get_org_context
from app.auth.models import OrganizationMember, User
from app.core.db import get_db
from app.core.enums import UserRole

router = APIRouter(prefix="/organizations/{organization_id}/audit", tags=["audit"])

AUDIT_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant, UserRole.auditor})
# date private ale utilizatorilor: nu apar în jurnalul altora (arhitectura §9c)
PRIVATE_ENTITIES = ("personal_checks", "user_person_links", "tasks_private")


class AuditOut(BaseModel):
    id: int
    created_at: datetime | None
    user_id: uuid.UUID | None
    user_email: str | None
    action: str
    entity: str
    entity_id: uuid.UUID | None
    old_values: dict | None
    new_values: dict | None


class AuditPage(BaseModel):
    total_shown: int
    has_more: bool
    items: list[AuditOut]


@router.get("", response_model=AuditPage)
def list_audit(
    entity: str | None = None,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AuditPage:
    ctx.require(AUDIT_ROLES)
    member_ids = select(OrganizationMember.user_id).where(OrganizationMember.organization_id == ctx.organization_id)
    # înregistrările organizației + evenimentele de cont (autentificare, parolă, 2FA) ale membrilor ei
    scope = or_(
        AuditLog.organization_id == ctx.organization_id,
        and_(AuditLog.organization_id.is_(None), AuditLog.entity == "users", AuditLog.user_id.in_(member_ids)),
    )
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(scope, AuditLog.entity.not_in(PRIVATE_ENTITIES))
    )
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit + 1).offset(offset)).all()
    items = [
        AuditOut(
            id=a.id, created_at=a.created_at, user_id=a.user_id, user_email=email, action=a.action, entity=a.entity,
            entity_id=a.entity_id, old_values=a.old_values, new_values=a.new_values,
        )  # fmt: skip
        for a, email in rows[:limit]
    ]
    return AuditPage(total_shown=len(items), has_more=len(rows) > limit, items=items)


@router.get("/entities", response_model=list[str])
def audit_entities(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[str]:
    ctx.require(AUDIT_ROLES)
    rows = db.scalars(
        select(AuditLog.entity).where(AuditLog.organization_id == ctx.organization_id).distinct().order_by(AuditLog.entity)
    )
    return [e for e in rows if e not in PRIVATE_ENTITIES]
