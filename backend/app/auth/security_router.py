"""Securitatea contului: schimbarea parolei și 2FA TOTP (activare, dezactivare, coduri de rezervă)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import get_current_user, get_current_user_pending
from app.auth.lockout import PasswordLocked, check_password
from app.auth.models import User
from app.auth.schemas import (
    BackupCodesOut,
    PasswordChangeRequest,
    TwoFAConfirmRequest,
    TwoFACodeRequest,
    TwoFASetupOut,
    TwoFAStatusOut,
)
from app.auth.twofa import LOCK_MINUTES, MAX_FAILURES, TwoFALocked, backup_codes_left, clear_backup_codes, generate_backup_codes, verify_second_factor
from app.core import totp
from app.core.crypto import decrypt, encrypt
from app.core.db import get_db
from app.core.security import hash_password

router = APIRouter(prefix="/auth", tags=["securitate"])

MIN_PASSWORD_LENGTH = 8


def _locked_user(db: Session, user: User) -> User:
    # blocăm rândul: două cereri simultane nu pot citi același pas TOTP sau cod de rezervă
    return db.scalar(select(User).where(User.id == user.id).with_for_update())


def _check_second_factor(db: Session, user: User, code: str) -> None:
    try:
        ok = verify_second_factor(db, user, code)
    except TwoFALocked:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Prea multe încercări; încearcă peste câteva minute") from None
    if not ok:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cod greșit")


def _check_password(db: Session, user: User, password: str) -> None:
    try:
        ok = check_password(db, user, password)
    except PasswordLocked:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Prea multe încercări; încearcă peste câteva minute") from None
    if not ok:
        db.commit()  # păstrează contorul de încercări greșite
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parola curentă este greșită")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest, user: User = Depends(get_current_user_pending), db: Session = Depends(get_db)
) -> None:
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Parola nouă trebuie să aibă cel puțin {MIN_PASSWORD_LENGTH} caractere")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Parola nouă trebuie să difere de cea curentă")
    user = _locked_user(db, user)
    _check_password(db, user, body.current_password)
    if user.totp_enabled:
        _check_second_factor(db, user, body.code or "")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    write_audit(db, action="update", entity="users", entity_id=user.id, user_id=user.id, new_values={"field": "password"})
    db.commit()


@router.get("/2fa", response_model=TwoFAStatusOut)
def two_fa_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TwoFAStatusOut:
    return TwoFAStatusOut(enabled=bool(user.totp_enabled), backup_codes_left=backup_codes_left(db, user) if user.totp_enabled else 0)


@router.post("/2fa/setup", response_model=TwoFASetupOut)
def two_fa_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TwoFASetupOut:
    """Generează un secret nou (încă inactiv) și întoarce URI-ul pentru aplicația de autentificare."""
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA este deja activ; dezactivează-l mai întâi")
    secret = totp.new_secret()
    user.totp_secret_enc = encrypt(secret)
    user.totp_last_step = None
    db.commit()
    return TwoFASetupOut(secret=secret, otpauth_uri=totp.provisioning_uri(secret, user.email))


@router.post("/2fa/enable", response_model=BackupCodesOut)
def two_fa_enable(body: TwoFACodeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BackupCodesOut:
    """Confirmă secretul cu un cod din aplicație, activează 2FA și dă codurile de rezervă (o singură dată)."""
    user = _locked_user(db, user)
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA este deja activ")
    secret = decrypt(user.totp_secret_enc) if user.totp_secret_enc else ""
    if not secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pornește mai întâi configurarea 2FA")
    now = datetime.now()
    if user.totp_locked_until and user.totp_locked_until > now:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Prea multe încercări; încearcă peste câteva minute")
    step = totp.verify(secret, body.code)
    if step is None:
        user.totp_failures = (user.totp_failures or 0) + 1
        if user.totp_failures >= MAX_FAILURES:
            user.totp_locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.totp_failures = 0
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cod greșit")
    user.totp_enabled = True
    user.totp_last_step = step
    user.totp_failures = 0
    user.totp_locked_until = None
    codes = generate_backup_codes(db, user)
    write_audit(db, action="update", entity="users", entity_id=user.id, user_id=user.id, new_values={"field": "2fa", "enabled": True})
    db.commit()
    return BackupCodesOut(backup_codes=codes)


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
def two_fa_disable(body: TwoFAConfirmRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    user = _locked_user(db, user)
    _check_password(db, user, body.password)
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA nu este activ")
    _check_second_factor(db, user, body.code)
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = None
    clear_backup_codes(db, user)
    write_audit(db, action="update", entity="users", entity_id=user.id, user_id=user.id, new_values={"field": "2fa", "enabled": False})
    db.commit()


@router.post("/2fa/backup-codes", response_model=BackupCodesOut)
def regenerate_backup_codes(
    body: TwoFAConfirmRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BackupCodesOut:
    user = _locked_user(db, user)
    _check_password(db, user, body.password)
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA nu este activ")
    _check_second_factor(db, user, body.code)
    codes = generate_backup_codes(db, user)
    write_audit(db, action="update", entity="users", entity_id=user.id, user_id=user.id, new_values={"field": "2fa_backup_codes"})
    db.commit()
    return BackupCodesOut(backup_codes=codes)
