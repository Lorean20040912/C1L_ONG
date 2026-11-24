"""Criptarea datelor sensibile (IBAN-ul conturilor bancare) cu cheia din .env (`ENCRYPTION_KEY`).

Fernet (AES-128-CBC + HMAC-SHA256); cheia Fernet se derivă din `ENCRYPTION_KEY` prin SHA-256,
deci în .env poate sta orice șir lung. Criptarea nu e deterministă (același IBAN dă texte
diferite), așa că IBAN-ul se caută decriptând conturile organizației (sunt puține).
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_PREFIX = "gAAAAA"  # începutul oricărui token Fernet


@lru_cache
def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def normalize_iban(value: str | None) -> str:
    return "".join((value or "").split()).upper()


def encrypt(value: str, secret: str | None = None) -> str:
    return _fernet(secret or get_settings().encryption_key).encrypt(value.encode()).decode()


def decrypt(value: str | None, secret: str | None = None) -> str | None:
    """Textul clar; valorile vechi necriptate (de dinaintea modulului bancar) se întorc neschimbate."""
    if not value or not value.startswith(_PREFIX):
        return value
    try:
        return _fernet(secret or get_settings().encryption_key).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("IBAN-ul nu se poate decripta: verificați ENCRYPTION_KEY") from exc


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_PREFIX)
