import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import (
    DocumentStatus,
    DocumentType,
    LineKind,
    PaymentDirection,
    document_status,
    document_type,
    line_kind,
    payment_direction,
)


class Document(Base):
    """Antetul comun al oricărui document (registratorul înregistrărilor, ca în 1C)."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256"),
        Index("ix_documents_organization_id_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    type: Mapped[DocumentType | None] = mapped_column(document_type)
    status: Mapped[DocumentStatus] = mapped_column(document_status, server_default=text("'new'"))
    is_posted: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    deletion_mark: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    version: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    storage_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: storage_connections (modulul storage)
    file_id: Mapped[str | None] = mapped_column(String)
    file_name: Mapped[str | None] = mapped_column(String)
    mime_type: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("counterparties.id"))
    doc_number: Mapped[str | None] = mapped_column(String)
    doc_date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    validated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))


class Invoice(Base):
    """Factura (primită); antetul — nr., data, contrapartida, totalul — e în `documents`."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    series: Mapped[str | None] = mapped_column(String)
    e_invoice_id: Mapped[str | None] = mapped_column(String)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", order_by="InvoiceLine.position", cascade="all, delete-orphan"
    )


class InvoiceLine(Base):
    """Rândul facturii; o factură poate avea MF + OMVSD + materiale + servicii."""

    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(String)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: items (modulul inventory)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: warehouses (modulul inventory)
    line_kind: Mapped[LineKind] = mapped_column(line_kind, server_default=text("'service'"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_items.id"))
    fixed_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fixed_assets.id"))
    put_into_use: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    # ordinea rândurilor în formular (nu e în schema.dbml; fără ea rândurile nu au ordine stabilă)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class PaymentOrder(Base):
    """Ordinul de plată; nr., data, suma, valuta — în `documents`."""

    __tablename__ = "payment_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    direction: Mapped[PaymentDirection] = mapped_column(payment_direction)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    purpose: Mapped[str | None] = mapped_column(String)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_accounts.id"))
    beneficiary_iban: Mapped[str | None] = mapped_column(String)
    beneficiary_name: Mapped[str | None] = mapped_column(String)
    beneficiary_idno: Mapped[str | None] = mapped_column(String)
    is_urgent: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    kind: Mapped[str | None] = mapped_column(String, server_default=text("'regular'"))
    tax_kind: Mapped[str | None] = mapped_column(String)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID)  # FK: payment_batches (modulul bank)
    bank_status: Mapped[str | None] = mapped_column(String, server_default=text("'draft'"))

    lines: Mapped[list["PaymentOrderLine"]] = relationship(back_populates="payment_order", cascade="all, delete-orphan")


class PaymentOrderLine(Base):
    """Rândurile pe persoane ale unei plăți cumulate (modulul payroll)."""

    __tablename__ = "payment_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    payment_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_orders.id", ondelete="CASCADE"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons.id"))
    payroll_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payroll_entries.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))

    payment_order: Mapped[PaymentOrder] = relationship(back_populates="lines")
