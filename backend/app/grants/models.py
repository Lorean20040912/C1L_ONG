"""Granturile și liniile de buget — doar câmpurile necesare nucleului.

Tabelele legate (donors, budget_versions, report_templates...) vin odată
cu modulul `grants`; până atunci coloanele lor de legătură nu au cheie străină.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, text
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
    budget_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: budget_versions (modulul grants)
    unit: Mapped[str | None] = mapped_column(String)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    donor_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cofinancing_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
