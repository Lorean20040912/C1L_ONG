"""Parole (Argon2) și jetoane JWT: acces scurt + refresh."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

TokenType = Literal["access", "refresh", "challenge"]

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_minutes)
    elif token_type == "challenge":  # pasul 2 al autentificării (2FA): valabil doar câteva minute
        expires = now + timedelta(minutes=5)
    else:
        expires = now + timedelta(days=settings.refresh_token_days)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": expires,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class InvalidToken(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    """Întoarce id-ul utilizatorului sau ridică InvalidToken."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidToken("tip de jeton greșit")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidToken("jeton fără utilizator") from exc
