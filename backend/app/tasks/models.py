"""Sarcini și șabloane recurente (schema.dbml, „Asistentul de procese”)."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    feature_code: Mapped[str | None] = mapped_column(ForeignKey("features.code"))
    title: Mapped[str] = mapped_column(String)
    recurrence: Mapped[str] = mapped_column(String)
    action_type: Mapped[str | None] = mapped_column(String)
    action_params: Mapped[dict | None] = mapped_column(JSONB)
    remind_days_before: Mapped[int | None] = mapped_column(Integer, server_default=text("2"))
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_by_ai: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner_status_due", "owner_user_id", "status", "due_date"),
        Index("ix_tasks_organization_period", "organization_id", "period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_templates.id"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_private: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    title: Mapped[str] = mapped_column(String)
    due_date: Mapped[date] = mapped_column(Date)
    period: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String, server_default=text("'open'"))
    done_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    linked_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    # termenul din calendarul raportărilor care a generat sarcina (extensie față de schema.dbml)
    calendar_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reporting_calendar.id", ondelete="SET NULL"))
