"""Blocarea temporară după parole greșite (login și schimbarea parolei), același regim ca la 2FA."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.models import User
from app.auth.twofa import LOCK_MINUTES, MAX_FAILURES
from app.core.security import verify_password


class PasswordLocked(Exception):
    pass


def check_password(db: Session, user: User, password: str) -> bool:
    """Verifică parola; după MAX_FAILURES greșeli contul se blochează LOCK_MINUTES minute.

    Ridică PasswordLocked cât timp blocarea e activă (chiar și pentru parola corectă).
    Contorul se resetează la succes; apelantul face commit ca să-l păstreze.
    """
    now = datetime.now()
    if user.password_locked_until and user.password_locked_until > now:
        raise PasswordLocked
    if verify_password(user.password_hash, password):
        user.password_failures = 0
        user.password_locked_until = None
        return True
    user.password_failures = (user.password_failures or 0) + 1
    if user.password_failures >= MAX_FAILURES:
        user.password_locked_until = now + timedelta(minutes=LOCK_MINUTES)
        user.password_failures = 0
        write_audit(db, action="lockout", entity="users", entity_id=user.id, user_id=user.id, new_values={"field": "password"})
    return False
