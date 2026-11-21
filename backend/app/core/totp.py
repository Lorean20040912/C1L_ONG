"""TOTP (RFC 6238, SHA-1, 6 cifre, 30 s) fără dependențe externe."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return str(number).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(secret: str, code: str, *, last_step: int | None = None, now: float | None = None) -> int | None:
    """Pasul în care codul e valid (toleranță ±1 pas) sau None.

    `last_step` = ultimul pas folosit cu succes: un cod nu se poate refolosi.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in (step - 1, step, step + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, email: str, issuer: str = "ContaHub") -> str:
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"
