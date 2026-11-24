import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class SalesInvoice(Base):
    """Factura emisă (sau nota de stornare); nr., data, clientul și totalul sunt în `documents`."""

    __tablename__ = "sales_invoices"
    __table_args__ = (
        UniqueConstraint("organization_id", "series", "number", name="uq_sales_invoices_number"),
        Index("ix_sales_invoices_org", "organization_id"),
        Index("ix_sales_invoices_storno", "storno_of_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    kind: Mapped[str] = mapped_column(String, server_default=text("'invoice'"))  # invoice | credit_note
    series: Mapped[str] = mapped_column(String, server_default=text("''"))
    number: Mapped[str] = mapped_column(String)
    due_date: Mapped[date | None] = mapped_column(Date)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    status: Mapped[str] = mapped_column(String, server_default=text("'active'"))  # active | cancelled
    storno_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_invoices.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    lines: Mapped[list["SalesInvoiceLine"]] = relationship(
        back_populates="invoice", order_by="SalesInvoiceLine.position", cascade="all, delete-orphan"
    )


class SalesInvoiceLine(Base):
    __tablename__ = "sales_invoice_lines"
    __table_args__ = (Index("ix_sales_invoice_lines_invoice", "sales_invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_invoices.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))  # fără TVA, în valuta facturii
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), server_default=text("0"))
    revenue_type: Mapped[str] = mapped_column(String, server_default=text("'economic'"))  # economic | organization
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class SalesSettlement(Base):
    """Stingerea facturii emise printr-o încasare (document de trezorerie) — total sau parțial."""

    __tablename__ = "sales_settlements"
    __table_args__ = (
        UniqueConstraint("receipt_document_id", "sales_invoice_id", name="uq_sales_settlements_pair"),
        Index("ix_sales_settlements_invoice", "sales_invoice_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    receipt_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_invoices.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))  # în valuta facturii
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
