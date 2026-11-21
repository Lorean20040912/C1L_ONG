import uuid

from pydantic import BaseModel

from app.core.enums import UserRole


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str

    model_config = {"from_attributes": True}


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    role: UserRole


class LoginResponse(BaseModel):
    """Fie perechea de jetoane, fie cererea celui de-al doilea factor (2FA)."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    requires_2fa: bool = False
    challenge_token: str | None = None


class Login2FARequest(BaseModel):
    challenge_token: str
    code: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    code: str | None = None  # obligatoriu când 2FA este activ


class TwoFASetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFAStatusOut(BaseModel):
    enabled: bool
    backup_codes_left: int


class TwoFACodeRequest(BaseModel):
    code: str


class TwoFAConfirmRequest(BaseModel):
    password: str
    code: str


class BackupCodesOut(BaseModel):
    backup_codes: list[str]
