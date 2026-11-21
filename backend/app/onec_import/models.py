"""Migrarea din 1C: rulările de import, corespondența GUID → obiect local, soldurile inițiale."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import ImportStatus, import_status


class OnecImportRun(Base):
    __tablename__ = "onec_import_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    source: Mapped[str | None] = mapped_column(String)  # odata / xml
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ImportStatus | None] = mapped_column(import_status, server_default=text("'pending'"))
    stats: Mapped[dict | None] = mapped_column(JSONB)
    reconciliation: Mapped[dict | None] = mapped_column(JSONB)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class OnecIdMap(Base):
    __tablename__ = "onec_id_map"
    __table_args__ = (UniqueConstraint("organization_id", "onec_type", "onec_guid"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    onec_type: Mapped[str] = mapped_column(String)
    onec_guid: Mapped[uuid.UUID] = mapped_column(UUID)
    local_table: Mapped[str] = mapped_column(String)
    local_id: Mapped[uuid.UUID] = mapped_column(UUID)
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("onec_import_runs.id"))


class OpeningBalance(Base):
    __tablename__ = "opening_balances"
    __table_args__ = (Index("ix_opening_balances_organization_id_balance_date", "organization_id", "balance_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    balance_date: Mapped[date] = mapped_column(Date)
    debit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    credit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    subconto: Mapped[dict | None] = mapped_column(JSONB)
    imported_from_1c: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
