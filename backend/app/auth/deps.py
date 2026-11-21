"""Dependențele FastAPI: utilizatorul curent și contextul organizației.

Orice endpoint care lucrează cu date contabile primește `OrgContext`:
organizația vine din cale (`/organizations/{organization_id}/...`), iar
accesul se verifică în `organization_members`. Interogările se filtrează
apoi obligatoriu după `ctx.organization_id`.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import OrganizationMember, User
from app.core.db import get_db
from app.core.enums import UserRole
from app.core.security import InvalidToken, decode_token

_bearer = HTTPBearer(auto_error=False)

# cine poate înregistra și anula documente
POSTING_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant, UserRole.accountant})


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentificare necesară",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        user_id = decode_token(credentials.credentials, "access")
    except InvalidToken:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or user.is_active is False:
        raise unauthorized
    return user


@dataclass(frozen=True)
class OrgContext:
    organization_id: uuid.UUID
    user: User
    role: UserRole

    def require(self, roles: frozenset[UserRole]) -> None:
        if self.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Rolul nu permite această acțiune")


def get_org_context(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    role = db.scalar(
        select(OrganizationMember.role).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if role is None:
        # 404, nu 403: nu confirmăm că organizația altcuiva există
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizația nu a fost găsită")
    return OrgContext(organization_id=organization_id, user=user, role=role)
