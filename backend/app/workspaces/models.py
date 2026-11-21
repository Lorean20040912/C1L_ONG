import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, Date, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import AccountingMethod, EntityType, accounting_method, entity_type


class Workspace(Base):
    """Baza (ca baza de date din 1C); poate avea una sau mai multe organizații."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))

    organizations: Mapped[list["Organization"]] = relationship(back_populates="workspace")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String)
    idno: Mapped[str] = mapped_column(String(13), unique=True)
    entity_type: Mapped[EntityType] = mapped_column(entity_type)
    accounting_method: Mapped[AccountingMethod] = mapped_column(
        accounting_method, server_default=text("'double_entry'")
    )
    vat_payer_from: Mapped[date | None] = mapped_column(Date)
    vat_code: Mapped[str | None] = mapped_column(String)
    legal_form: Mapped[str | None] = mapped_column(String)
    drive_root_folder_id: Mapped[str | None] = mapped_column(String)
    base_currency: Mapped[str | None] = mapped_column(CHAR(3), server_default=text("'MDL'"))
    ngo_category: Mapped[str | None] = mapped_column(CHAR(1))
    cuiio: Mapped[str | None] = mapped_column(String)
    cfoj: Mapped[str | None] = mapped_column(String)
    cfp: Mapped[str | None] = mapped_column(String)
    cuatm: Mapped[str | None] = mapped_column(String)
    caem: Mapped[str | None] = mapped_column(String)
    cnas_code: Mapped[str | None] = mapped_column(String)
    sfs_office: Mapped[str | None] = mapped_column(String)
    director_name: Mapped[str | None] = mapped_column(String)
    chief_accountant_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))

    workspace: Mapped[Workspace] = relationship(back_populates="organizations")
