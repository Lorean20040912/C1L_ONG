from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.schemas import LoginRequest, RefreshRequest, TokenPair, UserOut
from app.core.db import get_db
from app.core.security import InvalidToken, create_token, decode_token, verify_password

router = APIRouter(prefix="/auth", tags=["autentificare"])


def _token_pair(user: User) -> TokenPair:
    return TokenPair(access_token=create_token(user.id, "access"), refresh_token=create_token(user.id, "refresh"))


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or user.is_active is False or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail sau parolă greșită")
    user.last_login_at = datetime.now()
    write_audit(db, action="login", entity="users", entity_id=user.id, user_id=user.id)
    db.commit()
    return _token_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        user_id = decode_token(body.refresh_token, "refresh")
    except InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesiunea a expirat") from None
    user = db.get(User, user_id)
    if user is None or user.is_active is False:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesiunea a expirat")
    return _token_pair(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
