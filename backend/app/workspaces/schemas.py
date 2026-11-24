import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import AccountingMethod, EntityType, UserRole


class OrganizationBrief(BaseModel):
    id: uuid.UUID
    name: str
    idno: str
    entity_type: EntityType
    accounting_method: AccountingMethod
    role: UserRole


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    source: str | None
    created_at: datetime | None
    organizations: list[OrganizationBrief]


class WorkspaceCreate(BaseModel):
    """Varianta minimă a expertului „Bază nouă”: baza + prima organizație."""

    name: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)
    idno: str = Field(pattern=r"^\d{13}$")
    entity_type: EntityType
