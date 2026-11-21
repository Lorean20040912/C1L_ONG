"""Personal și salarizare (database/schema.dbml, secțiunea „Personal și salarizare”).

Persoana aparține organizației; contractele, scutirile și finanțarea țin de
persoană / contract, deci izolarea pe organizație se face prin `persons`.
Calculul se face PE CONTRACT (ToR F3.2): rezultatele lunii stau înghețate în
`payroll_entries`, cu cotele folosite în `calc_details`.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import ContractType, contract_type


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    full_name: Mapped[str] = mapped_column(String)
    idnp_enc: Mapped[str] = mapped_column(String)
    birth_date: Mapped[date | None] = mapped_column(Date)
    cpas: Mapped[str | None] = mapped_column(String)


class Contract(Base):
    """CIM sau contract civil; `gross_amount` = salariul lunar / onorariul lunar."""

    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))
    type: Mapped[ContractType] = mapped_column(contract_type)
    is_main_job: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    special_function_code: Mapped[str | None] = mapped_column(String)
    number: Mapped[str | None] = mapped_column(String)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))

    person: Mapped[Person] = relationship()
    funding: Mapped[list["ContractFunding"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ContractFunding.valid_from"
    )
    exemptions: Mapped[list["ExemptionClaim"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ExemptionClaim.valid_from"
    )


class ExemptionClaim(Base):
    """Cererea de scutire (personală / majoră / persoane întreținute) — doar la CIM de bază."""

    __tablename__ = "exemption_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    dependents_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))

    contract: Mapped[Contract] = relationship(back_populates="exemptions")


class ContractFunding(Base):
    """Repartizarea contractului pe granturi / linii de buget (suma cotelor ≤ 100%)."""

    __tablename__ = "contract_funding"
    __table_args__ = (CheckConstraint("share_percent > 0 AND share_percent <= 100", name="ck_contract_funding_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"))
    grant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grants.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    share_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    contract: Mapped[Contract] = relationship(back_populates="funding")


class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"
    __table_args__ = (UniqueConstraint("organization_id", "year", "month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))


class PayrollEntry(Base):
    """Rezultatul înghețat al calculului pe un contract într-o lună."""

    __tablename__ = "payroll_entries"
    __table_args__ = (UniqueConstraint("period_id", "contract_id", name="uq_payroll_entries_period_contract"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_periods.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id"))
    income_code: Mapped[str] = mapped_column(String)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    insured_category: Mapped[str | None] = mapped_column(String)
    cnas_tariff: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cnas_base: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    sick_benefit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    gross: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    personal_exemption: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    dependents_exemption: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    taxable_income: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    income_tax: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cnam_employee: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cnas_employer: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    net: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
    calc_details: Mapped[dict | None] = mapped_column(JSONB)


class IndividualPayment(Base):
    """„Plată către persoană fizică” (chirie FOL, arendă PLs, servicii PL, donație DON pf...)."""

    __tablename__ = "individual_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persons.id"))
    payment_kind: Mapped[str] = mapped_column(String)
    income_code: Mapped[str] = mapped_column(String)
    accrual_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    gross: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_rates.id"))
    income_tax: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), server_default=text("0"))
    net: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    cost_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_items.id"))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grants.id"))
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("budget_lines.id"))
