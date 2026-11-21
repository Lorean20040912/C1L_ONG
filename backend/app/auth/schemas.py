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
