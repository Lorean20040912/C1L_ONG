import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DateTime

from app.core.db import Base

_ID = dict(primary_key=True, server_default=text("gen_random_uuid()"))
_NOW = dict(server_default=text("now()"))


class FixedAssetEvent(Base):
    """Punerea în funcțiune sau casarea unui mijloc fix (status: posted / cancelled)."""

    __tablename__ = "fixed_asset_events"
    __table_args__ = (Index("ix_fixed_asset_events_asset", "fixed_asset_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, **_ID)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    fixed_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fixed_assets.id"))
    kind: Mapped[str] = mapped_column(String)  # commissioning / writeoff
    event_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, server_default=text("'posted'"))
    reason: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    loss_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))  # valoarea de bilanț la casare
    previous_status: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), **_NOW)


class PeriodAdjustment(Base):
    """Ajustarea perioadei: o înregistrare Dt/Kt la o dată, cu stornare automată în luna următoare (opțional)."""

    __tablename__ = "period_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(UUID, **_ID)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    reversal_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    adjustment_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    debit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    credit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    status: Mapped[str] = mapped_column(String, server_default=text("'posted'"))  # posted / cancelled
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), **_NOW)


class PayrollCalcType(Base):
    """Tipul de calcul salarial (în 1C: planurile „Начисления” și „Удержания”)."""

    __tablename__ = "payroll_calc_types"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, **_ID)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # accrual / deduction
    taxable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))  # intră în baza impozitului
    social_base: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))  # intră în baza contribuțiilor
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DocumentSource(Base):
    """De unde se iau documentele scanate: Google Drive, folder local prin agent sau folder pe server."""

    __tablename__ = "document_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID, **_ID)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String)  # google_drive / local_agent / server_folder
    name: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), **_NOW)
    # sincronizarea automată (fixb_0001): 0 = doar manual
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String)  # ok / error / running / skipped
    last_error: Mapped[str | None] = mapped_column(Text)
    last_found: Mapped[int | None] = mapped_column(Integer)
    last_added: Mapped[int | None] = mapped_column(Integer)
    last_duplicates: Mapped[int | None] = mapped_column(Integer)
    last_failed: Mapped[int | None] = mapped_column(Integer)


class ScannedFile(Base):
    """Conținutul scanului și câmpurile propuse de AI pentru un document."""

    __tablename__ = "scanned_files"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_sources.id"))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    ai_fields: Mapped[dict | None] = mapped_column(JSONB)
    ai_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
