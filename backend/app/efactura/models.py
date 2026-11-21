"""Mesajele e-Factura (SFS) legate de facturi."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EfacturaMessage(Base):
    __tablename__ = "efactura_messages"
    __table_args__ = (UniqueConstraint("organization_id", "efactura_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    direction: Mapped[str] = mapped_column(String)  # received / sent
    efactura_id: Mapped[str] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)  # draft / sent / signed / accepted / rejected
    payload_xml: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
