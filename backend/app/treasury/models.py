import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TreasuryDoc(Base):
    """Antet specific documentelor de bancă/casă, decontului de avans și actelor de servicii;
    nr., data, suma, valuta, contrapartida sunt în `documents`."""

    __tablename__ = "treasury_docs"
    __table_args__ = (Index("ix_treasury_docs_org_kind", "organization_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    kind: Mapped[str] = mapped_column(String)
    operation: Mapped[str | None] = mapped_column(String)
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_accounts.id"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    purpose: Mapped[str | None] = mapped_column(String)
    basis: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    lines: Mapped[list["TreasuryDocLine"]] = relationship(
        back_populates="doc", order_by="TreasuryDocLine.position", cascade="all, delete-orphan"
    )


class TreasuryDocLine(Base):
    __tablename__ = "treasury_doc_lines"
    __table_args__ = (Index("ix_treasury_doc_lines_doc", "treasury_doc_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    treasury_doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("treasury_docs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[str] = mapped_column(String)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    line_kind: Mapped[str] = mapped_column(String, server_default=text("'service'"))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_items.id"))

    doc: Mapped[TreasuryDoc] = relationship(back_populates="lines")
