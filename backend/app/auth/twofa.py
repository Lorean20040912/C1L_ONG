"""2FA TOTP: verificarea codurilor (TOTP sau de rezervă), blocarea după încercări greșite."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth.models import User, UserBackupCode
from app.core import totp
from app.core.config import get_settings
from app.core.crypto import decrypt

MAX_FAILURES = 5
LOCK_MINUTES = 5
BACKUP_CODES = 8


class TwoFALocked(Exception):
    pass


def _hash_code(code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, code.strip().lower().replace("-", "").encode(), hashlib.sha256).hexdigest()


def clear_backup_codes(db: Session, user: User) -> None:
    db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user.id))


def generate_backup_codes(db: Session, user: User) -> list[str]:
    """Înlocuiește codurile de rezervă; întoarce textul lor o singură dată."""
    clear_backup_codes(db, user)
    codes = []
    for _ in range(BACKUP_CODES):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(UserBackupCode(user_id=user.id, code_hash=_hash_code(raw)))
    db.flush()
    return codes


def backup_codes_left(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count()).select_from(UserBackupCode).where(UserBackupCode.user_id == user.id, UserBackupCode.used_at.is_(None))
    ) or 0


def verify_second_factor(db: Session, user: User, code: str) -> bool:
    """Cod TOTP sau cod de rezervă. Ridică TwoFALocked după prea multe încercări greșite.

    Eșecul se numără pe utilizator; apelantul face commit ca să se păstreze contorul.
    """
    now = datetime.now()
    if user.totp_locked_until and user.totp_locked_until > now:
        raise TwoFALocked
    ok = False
    if user.totp_secret_enc:
        secret = decrypt(user.totp_secret_enc)
        step = totp.verify(secret, code, last_step=user.totp_last_step) if secret else None
        if step is not None:
            user.totp_last_step = step
            ok = True
    if not ok:
        stripped = code.strip()
        if len(stripped.replace("-", "")) == 10:
            digest = _hash_code(stripped)
            backup = db.scalar(
                select(UserBackupCode)
                .where(UserBackupCode.user_id == user.id, UserBackupCode.code_hash == digest, UserBackupCode.used_at.is_(None))
                .with_for_update()
            )
            if backup is not None:
                backup.used_at = now
                ok = True
    if ok:
        user.totp_failures = 0
        user.totp_locked_until = None
        return True
    user.totp_failures = (user.totp_failures or 0) + 1
    if user.totp_failures >= MAX_FAILURES:
        user.totp_locked_until = now + timedelta(minutes=LOCK_MINUTES)
        user.totp_failures = 0
    return False
