import uuid

from sqlalchemy import CHAR, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BankAccount(Base):
    """Contul bancar al organizației, legat de contul contabil (242 / 243)."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    iban_enc: Mapped[str] = mapped_column(String)  # criptarea vine odată cu modulul bank; deocamdată IBAN-ul simplu
    bank_name: Mapped[str | None] = mapped_column(String)
    bank_code: Mapped[str | None] = mapped_column(String)
    currency: Mapped[str] = mapped_column(CHAR(3))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
