import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MonthCloseRun(Base):
    """Închiderea lunii: pașii cu statut și documentul care înregistrează rezultatele lor."""

    __tablename__ = "month_close_runs"
    __table_args__ = (UniqueConstraint("organization_id", "year", "month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    steps: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(String)
    run_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
