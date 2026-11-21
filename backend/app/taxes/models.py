import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import ContractType, contract_type


class TaxRate(Base):
    """Cota de impozit cu perioadă de valabilitate."""

    __tablename__ = "tax_rates"
    __table_args__ = (
        # applies_to = NULL înseamnă „ambele tipuri de contract”; două NULL trebuie să fie egale
        UniqueConstraint(
            "code", "applies_to", "valid_from", name="uq_tax_rates_code_applies_valid", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    code: Mapped[str] = mapped_column(String)
    applies_to: Mapped[ContractType | None] = mapped_column(contract_type)
    value: Mapped[Decimal] = mapped_column(Numeric(15, 4))
    is_percent: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    legal_basis: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    legal_update_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: legal_updates (modulul taxes, etapa E11)
