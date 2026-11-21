import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Feature(Base):
    """Funcționalitatea (profilul) care pornește module, secțiuni și ecrane (docs/13 §3)."""

    __tablename__ = "features"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    modules: Mapped[dict] = mapped_column(JSONB)
    default_for: Mapped[dict | None] = mapped_column(JSONB)


class OrganizationFeature(Base):
    __tablename__ = "organization_features"
    __table_args__ = (UniqueConstraint("organization_id", "feature_code", "enabled_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    feature_code: Mapped[str] = mapped_column(ForeignKey("features.code"))
    enabled_from: Mapped[date] = mapped_column(Date)
    enabled_to: Mapped[date | None] = mapped_column(Date)


class OrganizationTaxRegime(Base):
    __tablename__ = "organization_tax_regimes"
    __table_args__ = (UniqueConstraint("organization_id", "valid_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    regime_code: Mapped[str] = mapped_column(String)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str | None] = mapped_column(String)


class CoaTemplate(Base):
    """Șablonul planului de conturi, copiat în `accounts` la crearea bazei."""

    __tablename__ = "coa_templates"
    __table_args__ = (UniqueConstraint("code", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    code: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    accounts: Mapped[list] = mapped_column(JSONB)
