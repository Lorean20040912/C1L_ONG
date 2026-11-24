"""Înregistrările contabile, rulajele, perioadele, regulile și politica contabilă."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import SubcontoType, subconto_type


class AccountingPeriod(Base):
    __tablename__ = "accounting_periods"
    __table_args__ = (UniqueConstraint("organization_id", "year", "month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class EntryLine(Base):
    """Înregistrarea Dt/Kt. Tabelă partiționată pe ani după `entry_date`,
    de aceea cheia primară este (id, entry_date). Se scrie doar prin `posting.engine`."""

    __tablename__ = "entry_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["budget_line_id", "grant_id"],
            ["budget_lines.id", "budget_lines.grant_id"],
            name="fk_entry_lines_budget_line_grant",
        ),
        Index("ix_entry_lines_organization_id_entry_date", "organization_id", "entry_date"),
        Index("ix_entry_lines_debit_account_id_entry_date", "debit_account_id", "entry_date"),
        Index("ix_entry_lines_credit_account_id_entry_date", "credit_account_id", "entry_date"),
        Index("ix_entry_lines_grant_budget_line_entry_date", "grant_id", "budget_line_id", "entry_date"),
        Index("ix_entry_lines_document_id", "document_id"),
        {"postgresql_partition_by": "RANGE (entry_date)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    debit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    credit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    currency_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(15, 3))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_items.id"))
    activity_type: Mapped[str | None] = mapped_column(String)
    is_non_statutory: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    description: Mapped[str | None] = mapped_column(String)


class EntryLineAnalytics(Base):
    """Analitica (subconto) rândului de înregistrare, pe partea D sau K."""

    __tablename__ = "entry_line_analytics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_line_id", "entry_date"],
            ["entry_lines.id", "entry_lines.entry_date"],
            ondelete="CASCADE",
            name="fk_entry_line_analytics_entry_line",
        ),
        Index("ix_entry_line_analytics_subconto_type_ref_id", "subconto_type", "ref_id"),
    )

    entry_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    side: Mapped[str] = mapped_column(CHAR(1), primary_key=True)
    subconto_type: Mapped[SubcontoType] = mapped_column(subconto_type, primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID)


class AccountTurnover(Base):
    """Tabelul de totaluri (ca „итоги” din 1C), actualizat în tranzacția înregistrării."""

    __tablename__ = "account_turnovers"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "account_id",
            "period",
            "grant_id",
            "currency",
            name="uq_account_turnovers_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    period: Mapped[date] = mapped_column(Date)
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'MDL'"))
    debit: Mapped[Decimal] = mapped_column(Numeric(17, 2), server_default=text("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(17, 2), server_default=text("0"))
    debit_currency: Mapped[Decimal | None] = mapped_column(Numeric(17, 2), server_default=text("0"))
    credit_currency: Mapped[Decimal | None] = mapped_column(Numeric(17, 2), server_default=text("0"))


class PostingRule(Base):
    """Formula contabilă ca date (nu cod); citată obligatoriu din `source_ref`."""

    __tablename__ = "posting_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    document_type: Mapped[str] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String)
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    debit_account: Mapped[str] = mapped_column(String)
    credit_account: Mapped[str] = mapped_column(String)
    analytics: Mapped[dict | None] = mapped_column(JSONB)
    source_ref: Mapped[str] = mapped_column(String)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    change_reason: Mapped[str | None] = mapped_column(Text)
    release_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: releases (modulul releases)


class AccountingPolicy(Base):
    __tablename__ = "accounting_policies"
    __table_args__ = (UniqueConstraint("organization_id", "valid_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    valid_from: Mapped[date] = mapped_column(Date)
    grant_receivable_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    grant_recognition: Mapped[str | None] = mapped_column(String, server_default=text("'on_signing'"))
    stock_to_deferred_income: Mapped[str | None] = mapped_column(String, server_default=text("'unused_only'"))
    fa_valuation_method: Mapped[str | None] = mapped_column(String)
    settings: Mapped[dict | None] = mapped_column(JSONB)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
