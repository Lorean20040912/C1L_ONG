import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SimpleLedgerEntry(Base):
    """Registrul-jurnal de venituri și cheltuieli (partida simplă): venit = încasare, cheltuială = plată."""

    __tablename__ = "simple_ledger_entries"
    __table_args__ = (Index("ix_simple_ledger_entries_organization_id_entry_date", "organization_id", "entry_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    is_deductible: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    description: Mapped[str | None] = mapped_column(String)
