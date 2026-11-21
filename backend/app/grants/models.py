"""Granturile, donatorii, versiunile de buget, liniile de buget, tranșele și repartizările.

`report_template_id` rămâne fără cheie străină până vine modulul `donor_reports`.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CostItem(Base):
    __tablename__ = "cost_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String)
    con5_article: Mapped[str | None] = mapped_column(String)
    designation_category: Mapped[str | None] = mapped_column(String)


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    funding_type: Mapped[str | None] = mapped_column(String)
    designation_year: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(CHAR(3))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    accrue_funding_debt: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    is_closed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    drive_folder_id: Mapped[str | None] = mapped_column(String)
    report_template_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: report_templates (modulul donor_reports)


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    __table_args__ = (
        UniqueConstraint("grant_id", "budget_version_id", "code"),
        UniqueConstraint("id", "grant_id", name="uq_budget_lines_id_grant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grants.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    code: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_items.id"))
    budget_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_versions.id"))
    unit: Mapped[str | None] = mapped_column(String)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    donor_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cofinancing_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)


class GrantDonor(Base):
    __tablename__ = "grant_donors"
    __table_args__ = (UniqueConstraint("grant_id", "donor_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grants.id"))
    donor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("donors.id"))
    share_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))


class BudgetVersion(Base):
    __tablename__ = "budget_versions"
    __table_args__ = (UniqueConstraint("grant_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grants.id"))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    approved_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: budget_imports (modulul budget_import)
    is_current: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))


class GrantTranche(Base):
    __tablename__ = "grant_tranches"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grants.id"))
    donor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("donors.id"))
    number: Mapped[int] = mapped_column(Integer)
    planned_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(CHAR(3))
    condition: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String, server_default=text("'planned'"))
    received_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))


class Allocation(Base):
    """Repartizarea unei cheltuieli comune pe liniile de buget (`НКО_РаспределениеЗатрат`)."""

    __tablename__ = "allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    budget_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget_lines.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    amount_mdl: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    note: Mapped[str | None] = mapped_column(String)
    suggested_by_ai: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
