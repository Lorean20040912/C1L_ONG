import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FixedAsset(Base):
    """Fișa mijlocului fix; se creează automat din rândul facturii (line_kind = fixed_asset)."""

    __tablename__ = "fixed_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    inventory_no: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    initial_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    residual_value: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    useful_life_months: Mapped[int | None] = mapped_column(Integer)
    depreciation_method: Mapped[str | None] = mapped_column(String, server_default=text("'linear'"))
    asset_group: Mapped[str | None] = mapped_column(String)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    depreciation_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    expense_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    commissioning_date: Mapped[date | None] = mapped_column(Date)
    depreciation_start: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String, server_default=text("'in_use'"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
