import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import AccountKind, SubcontoType, account_kind, subconto_type


class Account(Base):
    """Contul din planul de conturi al organizației."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    account_kind: Mapped[AccountKind] = mapped_column(account_kind)
    is_group: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    is_currency: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))


class AccountAnalytics(Base):
    """Subconto-urile contului (în locul coloanelor subconto1..3)."""

    __tablename__ = "account_analytics"
    __table_args__ = (UniqueConstraint("account_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    position: Mapped[int] = mapped_column(Integer)
    subconto_type: Mapped[SubcontoType] = mapped_column(subconto_type)
    is_required: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    cuatm: Mapped[str | None] = mapped_column(String)


class Counterparty(Base):
    __tablename__ = "counterparties"
    __table_args__ = (UniqueConstraint("organization_id", "idno"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String)
    idno: Mapped[str | None] = mapped_column(String(13))
    vat_code: Mapped[str | None] = mapped_column(String)
    iban_enc: Mapped[str | None] = mapped_column(String)
    bank_code: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    default_budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    onec_guid: Mapped[uuid.UUID | None] = mapped_column(UUID)
