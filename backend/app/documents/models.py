import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import DocumentStatus, DocumentType, document_status, document_type


class Document(Base):
    """Antetul comun al oricărui document (registratorul înregistrărilor, ca în 1C)."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256"),
        Index("ix_documents_organization_id_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    type: Mapped[DocumentType | None] = mapped_column(document_type)
    status: Mapped[DocumentStatus] = mapped_column(document_status, server_default=text("'new'"))
    is_posted: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    deletion_mark: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    version: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    storage_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: storage_connections (modulul storage)
    file_id: Mapped[str | None] = mapped_column(String)
    file_name: Mapped[str | None] = mapped_column(String)
    mime_type: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id"))
    doc_number: Mapped[str | None] = mapped_column(String)
    doc_date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    validated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))
