"""Criptarea datelor personale (IDNP) în baza de date.

Cheia: `PERSONAL_DATA_KEY` (cheie Fernet) din .env; dacă lipsește, se derivă din
`JWT_SECRET` — suficient pentru dezvoltare, în producție se setează separat
(schimbarea ulterioară a cheii cere recriptarea datelor).
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.personal_data_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(("idnp:" + settings.jwt_secret).encode()).digest()).decode()
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""  # cheie schimbată / date corupte: nu dăm eroare la listare


def mask(value: str) -> str:
    return value[:3] + "•" * max(len(value) - 6, 0) + value[-3:] if len(value) > 6 else value
