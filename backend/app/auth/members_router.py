"""Utilizatorii organizației și rolurile lor (ToR §3; doar administratorul).

Un utilizator existent (același e-mail) primește doar rolul în organizație; unul
nou se creează cu parola inițială dată de administrator. Organizația trebuie să
rămână mereu cu cel puțin un administrator.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import USER_ADMIN_ROLES, OrgContext, get_org_context
from app.auth.models import OrganizationMember, User
from app.core.db import get_db
from app.core.enums import UserRole
from app.core.security import hash_password

router = APIRouter(prefix="/organizations/{organization_id}/members", tags=["utilizatori"])


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool | None
    last_login_at: datetime | None


class MemberCreate(BaseModel):
    email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str | None = Field(default=None, min_length=1)
    role: UserRole
    password: str | None = Field(default=None, min_length=8, description="doar pentru un utilizator nou")


class MemberUpdate(BaseModel):
    role: UserRole


def _out(member: OrganizationMember, user: User) -> MemberOut:
    return MemberOut(
        id=member.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


def _member(db: Session, ctx: OrgContext, member_id: uuid.UUID) -> OrganizationMember:
    member = db.scalar(
        select(OrganizationMember)
        .where(OrganizationMember.id == member_id, OrganizationMember.organization_id == ctx.organization_id)
        .with_for_update()
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilizatorul nu face parte din organizație")
    return member


def _admins(db: Session, organization_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.role == UserRole.admin
        )
    )


@router.get("", response_model=list[MemberOut])
def list_members(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[MemberOut]:
    ctx.require(USER_ADMIN_ROLES)
    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == ctx.organization_id)
        .order_by(User.full_name)
    ).all()
    return [_out(m, u) for m, u in rows]


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    body: MemberCreate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> MemberOut:
    ctx.require(USER_ADMIN_ROLES)
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    created = user is None
    if created:
        if not body.full_name or not body.password:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Pentru un utilizator nou completați numele și parola inițială"
            )
        user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
    elif db.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == ctx.organization_id, OrganizationMember.user_id == user.id
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Utilizatorul face deja parte din organizație")
    member = OrganizationMember(organization_id=ctx.organization_id, user_id=user.id, role=body.role)
    db.add(member)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="organization_members",
        entity_id=member.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        new_values={"email": email, "role": body.role.value, "new_user": created},
    )
    db.commit()
    return _out(member, user)


@router.patch("/{member_id}", response_model=MemberOut)
def change_role(
    member_id: uuid.UUID, body: MemberUpdate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> MemberOut:
    ctx.require(USER_ADMIN_ROLES)
    member = _member(db, ctx, member_id)
    if member.role == UserRole.admin and body.role != UserRole.admin and _admins(db, ctx.organization_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Organizația trebuie să aibă cel puțin un administrator")
    old = member.role
    member.role = body.role
    db.flush()
    write_audit(
        db,
        action="update",
        entity="organization_members",
        entity_id=member.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values={"role": old.value},
        new_values={"role": body.role.value},
    )
    db.commit()
    return _out(member, db.get(User, member.user_id))


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> None:
    """Retrage accesul la organizație (contul utilizatorului rămâne, pentru alte organizații și audit)."""
    ctx.require(USER_ADMIN_ROLES)
    member = _member(db, ctx, member_id)
    if member.role == UserRole.admin and _admins(db, ctx.organization_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Organizația trebuie să aibă cel puțin un administrator")
    write_audit(
        db,
        action="delete",
        entity="organization_members",
        entity_id=member.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        old_values={"user_id": str(member.user_id), "role": member.role.value},
    )
    db.delete(member)
    db.commit()
