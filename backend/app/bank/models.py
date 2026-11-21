import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Integer, LargeBinary, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto_bank import decrypt, encrypt, normalize_iban
from app.core.db import Base
from app.core.enums import PaymentDirection, payment_direction

BANK_FILE_TYPES = ("txt", "dbf", "dbo", "xml", "csv")
bank_file_type = ENUM(*BANK_FILE_TYPES, name="bank_file_type", create_type=False)


class BankAccount(Base):
    """Contul bancar al organizației, legat de contul contabil (242 / 243). IBAN-ul e criptat."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    iban_enc: Mapped[str] = mapped_column(String)  # criptat cu ENCRYPTION_KEY (app/core/crypto.py)
    bank_name: Mapped[str | None] = mapped_column(String)
    bank_code: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str] = mapped_column(CHAR(3))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))

    @property
    def iban(self) -> str:
        return decrypt(self.iban_enc) or ""

    @iban.setter
    def iban(self, value: str) -> None:
        self.iban_enc = encrypt(normalize_iban(value))


class BankFormat(Base):
    """Profilul unei bănci: tipul fișierului, codificarea și `layout` (parserul / exportatorul și maparea câmpurilor).

    `organization_id` gol = profil standard (din migrare); organizația își poate adăuga profiluri proprii.
    """

    __tablename__ = "bank_formats"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    bank_name: Mapped[str] = mapped_column(String)
    file_type: Mapped[str] = mapped_column(bank_file_type)
    direction: Mapped[str] = mapped_column(String)  # import_statement / export_payments
    encoding: Mapped[str | None] = mapped_column(String, server_default=text("'cp1251'"))
    layout: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))


class BankImport(Base):
    __tablename__ = "bank_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id"))
    format_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_formats.id"))
    file_name: Mapped[str | None] = mapped_column(String)
    file_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_created: Mapped[int | None] = mapped_column(Integer)
    rows_skipped: Mapped[int | None] = mapped_column(Integer)
    rows_failed: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[list | None] = mapped_column(JSONB)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))


class BankTransaction(Base):
    """Rândul extrasului; `dedup_key` împiedică importul de două ori al aceluiași rând."""

    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_imports.id"))
    dedup_key: Mapped[str] = mapped_column(String, unique=True)
    tx_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[PaymentDirection] = mapped_column(payment_direction)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    counterparty_iban: Mapped[str | None] = mapped_column(String)
    counterparty_idno: Mapped[str | None] = mapped_column(String)
    purpose: Mapped[str | None] = mapped_column(String)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    # în plus față de schema.dbml: ce trebuie arătat în expert fără a reciti fișierul
    doc_number: Mapped[str | None] = mapped_column(String)
    counterparty_name: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    match: Mapped[str | None] = mapped_column(String)  # new_draft / exported_order / existing_order


class PaymentBatch(Base):
    """Lotul de export al ordinelor de plată în formatul băncii."""

    __tablename__ = "payment_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    bank_format_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_formats.id"))
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id"))
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))
    folder_path: Mapped[str | None] = mapped_column(String)
    file_id: Mapped[str | None] = mapped_column(String)  # numele fișierului generat
    orders_count: Mapped[int | None] = mapped_column(Integer)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # în plus față de schema.dbml: conținutul fișierului, până vine modulul storage
    content: Mapped[bytes | None] = mapped_column(LargeBinary)


class ExchangeRate(Base):
    """Cursul oficial BNM pe zile (lipsește din schema.dbml): MDL pentru o unitate de valută."""

    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("organization_id", "currency", "rate_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    currency: Mapped[str] = mapped_column(CHAR(3))
    rate_date: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    source: Mapped[str | None] = mapped_column(String, server_default=text("'manual'"))  # bnm / manual
