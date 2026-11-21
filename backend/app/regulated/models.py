"""Rapoartele reglementate: formularele cu versiuni, rapoartele întocmite și calendarul.

- `report_forms` — formularul (ONG17, 5-CON, IPC21) cu versiune și perioadă de
  valabilitate; `structure` descrie celulele, formulele și verificările (ToR F6a.5);
- `tax_reports` — raportul întocmit: valorile calculate (`data`) și corecțiile
  manuale; după depunere (`submitted`) raportul e înghețat;
- `reporting_calendar` — termenele organizației; `tax_report_id` gol = neprezentat;
- `organization_stats` — membri și voluntari pe perioadă (5-CON rândurile 300, 320).
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import pg_enum


class ReportStatus(str, enum.Enum):
    draft = "draft"
    checked = "checked"
    submitted = "submitted"


report_status = pg_enum(ReportStatus, "report_status")


class ReportForm(Base):
    __tablename__ = "report_forms"
    __table_args__ = (UniqueConstraint("code", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    code: Mapped[str] = mapped_column(String)
    authority: Mapped[str] = mapped_column(String)
    periodicity: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    structure: Mapped[dict] = mapped_column(JSONB)
    due_day_rule: Mapped[str | None] = mapped_column(String)


class TaxReport(Base):
    __tablename__ = "tax_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_forms.id"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    status: Mapped[ReportStatus | None] = mapped_column(report_status, server_default=text("'draft'"))
    data: Mapped[dict | None] = mapped_column(JSONB)
    manual_overrides: Mapped[dict | None] = mapped_column(JSONB)
    export_file_id: Mapped[str | None] = mapped_column(String)
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class ReportingCalendar(Base):
    __tablename__ = "reporting_calendar"
    __table_args__ = (UniqueConstraint("organization_id", "form_id", "period_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_forms.id"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    tax_report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_reports.id"))


class OrganizationStats(Base):
    __tablename__ = "organization_stats"
    __table_args__ = (UniqueConstraint("organization_id", "period_end"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    period_end: Mapped[date] = mapped_column(Date)
    members_count: Mapped[int | None] = mapped_column(Integer)
    volunteers_count: Mapped[int | None] = mapped_column(Integer)
