import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import UserRole, user_role


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    totp_secret_enc: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # 2FA: secretul din `totp_secret_enc` devine activ doar după confirmarea cu un cod
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    totp_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    totp_locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # încercări greșite de parolă (login și schimbarea parolei) și blocarea temporară
    password_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    password_locked_until: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # parola inițială dată de administrator trebuie schimbată la prima intrare
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, server_default=text("now()"))

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="user")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[UserRole] = mapped_column(user_role)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship()  # noqa: F821


class UserBackupCode(Base):
    """Coduri de rezervă 2FA: se păstrează doar amprenta, fiecare se folosește o singură dată."""

    __tablename__ = "user_backup_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
