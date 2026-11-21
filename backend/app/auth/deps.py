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
from app.core.rls import set_rls_context
from app.core.security import InvalidToken, decode_token

_bearer = HTTPBearer(auto_error=False)

# cine poate înregistra și anula documente
POSTING_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant, UserRole.accountant})
# setările contabile ale organizației: politica, regulile, perioadele, conturile bancare
ADMIN_ROLES = frozenset({UserRole.admin, UserRole.chief_accountant})
# utilizatorii și drepturile (ToR §3: Administrator)
USER_ADMIN_ROLES = frozenset({UserRole.admin})


def get_current_user_pending(
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


def get_current_user(user: User = Depends(get_current_user_pending)) -> User:
    """Utilizatorul curent; cu parola inițială încă neschimbată accesul e refuzat (doar /auth/me și /auth/password rămân)."""
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Schimbați parola inițială înainte de a continua")
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
    # Row-Level Security: de aici încolo tranzacțiile cererii văd doar această organizație
    set_rls_context(db, organization_id, user.id)
    return OrgContext(organization_id=organization_id, user=user, role=role)
