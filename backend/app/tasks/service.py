"""Sarcini: termenele calendarului raportărilor, șabloane recurente, stări."""

import calendar as cal
import re
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.regulated.models import ReportForm, ReportingCalendar, TaxReport
from app.regulated.service import calendar_status, sync_calendar
from app.tasks.models import Task, TaskTemplate
from app.workspaces.models import Organization

CALENDAR_WINDOW_PAST = 60
CALENDAR_WINDOW_FUTURE = 90

_MONTHLY = re.compile(r"^FREQ=MONTHLY;BYMONTHDAY=(\d{1,2})$")
_YEARLY = re.compile(r"^FREQ=YEARLY;BYMONTH=(\d{1,2});BYMONTHDAY=(\d{1,2})$")


class RecurrenceError(ValueError):
    pass


def parse_recurrence(rule: str) -> tuple[int | None, int]:
    """(luna sau None pentru lunar, ziua). Acceptă doar formele lunar / anual din ToR M14."""
    rule = rule.strip().upper()
    if m := _MONTHLY.match(rule):
        month, day = None, int(m.group(1))
    elif m := _YEARLY.match(rule):
        month, day = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise RecurrenceError("luna trebuie să fie între 1 și 12")
    else:
        raise RecurrenceError("regulă acceptată: FREQ=MONTHLY;BYMONTHDAY=<zi> sau FREQ=YEARLY;BYMONTH=<lună>;BYMONTHDAY=<zi>")
    if not 1 <= day <= 31:
        raise RecurrenceError("ziua trebuie să fie între 1 și 31")
    return month, day


def template_due_date(rule: str, period: date) -> date | None:
    """Termenul în luna `period` (prima zi a lunii) sau None dacă regula nu cade în această lună."""
    month, day = parse_recurrence(rule)
    if month is not None and month != period.month:
        return None
    return date(period.year, period.month, min(day, cal.monthrange(period.year, period.month)[1]))


def generate_from_templates(db: Session, organization_id: uuid.UUID, owner_id: uuid.UUID, period: date) -> list[Task]:
    """Sarcinile lunii din șabloanele active (ale organizației și cele standard); o dată pe șablon și lună."""
    period = period.replace(day=1)
    templates = db.scalars(
        select(TaskTemplate).where(
            TaskTemplate.is_active.is_(True),
            (TaskTemplate.organization_id == organization_id) | TaskTemplate.organization_id.is_(None),
        )
    ).all()
    existing = set(
        db.scalars(
            select(Task.template_id).where(
                Task.organization_id == organization_id, Task.period == period, Task.template_id.is_not(None)
            )
        )
    )
    created = []
    for t in templates:
        if t.id in existing:
            continue
        due = template_due_date(t.recurrence, period)
        if due is None:
            continue
        task = Task(
            organization_id=organization_id, template_id=t.id, owner_user_id=owner_id, title=t.title, due_date=due,
            period=period, status="open",
        )  # fmt: skip
        db.add(task)
        created.append(task)
    db.flush()
    return created


def sync_calendar_tasks(db: Session, org: Organization, owner_id: uuid.UUID, today: date) -> list[Task]:
    """Legătura cu calendarul raportărilor: câte o sarcină pentru fiecare termen nedepus
    din fereastra apropiată; sarcina se închide singură când raportul e depus."""
    sync_calendar(db, org, today)
    rows = db.execute(
        select(ReportingCalendar, ReportForm, TaxReport.status)
        .join(ReportForm, ReportForm.id == ReportingCalendar.form_id)
        .outerjoin(TaxReport, TaxReport.id == ReportingCalendar.tax_report_id)
        .where(ReportingCalendar.organization_id == org.id)
    ).all()
    linked = {t.calendar_id: t for t in db.scalars(select(Task).where(Task.organization_id == org.id, Task.calendar_id.is_not(None)))}
    created = []
    for row, form, report_status in rows:
        state = calendar_status(row, report_status, today)
        task = linked.get(row.id)
        if task is not None:
            if state == "submitted" and task.status in ("open", "overdue"):
                task.status, task.done_at = "done", datetime.now()
            continue
        in_window = today - timedelta(days=CALENDAR_WINDOW_PAST) <= row.due_date <= today + timedelta(days=CALENDAR_WINDOW_FUTURE)
        if state == "submitted" or not in_window:
            continue
        task = Task(
            organization_id=org.id, owner_user_id=owner_id, calendar_id=row.id, due_date=row.due_date,
            period=row.period_from.replace(day=1), status="open",
            title=f"Depune {form.code} pentru {row.period_from:%m.%Y}",
        )  # fmt: skip
        db.add(task)
        created.append(task)
    db.flush()
    return created


def mark_overdue(db: Session, organization_id: uuid.UUID, today: date) -> None:
    db.execute(
        update(Task)
        .where(Task.organization_id == organization_id, Task.status == "open", Task.due_date < today)
        .values(status="overdue")
    )


