"""API-ul sarcinilor și termenelor (ToR M14): listă, creare, stări, șabloane recurente,
legătura cu calendarul raportărilor."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import ADMIN_ROLES, POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.tasks.models import Task, TaskTemplate
from app.tasks.service import (
    RecurrenceError,
    generate_from_templates,
    mark_overdue,
    parse_recurrence,
    sync_calendar_tasks,
)
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}", tags=["sarcini"])

STATUSES = ("open", "done", "skipped", "overdue")


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    due_date: date
    period: date | None
    status: str
    done_at: datetime | None
    is_private: bool
    owner_user_id: uuid.UUID
    template_id: uuid.UUID | None
    calendar_id: uuid.UUID | None
    days_left: int


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: date
    period: date | None = None
    is_private: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_date: date | None = None


class TemplateOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    title: str
    recurrence: str
    remind_days_before: int | None
    is_active: bool | None
    standard: bool


class TemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    recurrence: str
    remind_days_before: int = Field(default=2, ge=0, le=60)
    is_active: bool = True


class GenerateIn(BaseModel):
    period: date | None = None


def _out(t: Task, today: date) -> TaskOut:
    return TaskOut(
        id=t.id, title=t.title, due_date=t.due_date, period=t.period, status=t.status or "open", done_at=t.done_at,
        is_private=bool(t.is_private), owner_user_id=t.owner_user_id, template_id=t.template_id,
        calendar_id=t.calendar_id, days_left=(t.due_date - today).days,
    )  # fmt: skip


def _visible(ctx: OrgContext):
    """Sarcinile organizației; cele private doar pentru proprietar (și prin RLS)."""
    return (Task.organization_id == ctx.organization_id) & or_(Task.is_private.is_not(True), Task.owner_user_id == ctx.user.id)


def _get_task(db: Session, ctx: OrgContext, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, _visible(ctx)).with_for_update())
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sarcina nu a fost găsită")
    return task


def _can_change(ctx: OrgContext, task: Task) -> None:
    if ctx.role not in POSTING_ROLES and task.owner_user_id != ctx.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rolul nu permite această acțiune")


def _audit(db: Session, ctx: OrgContext, action: str, task: Task, old: dict | None = None) -> None:
    write_audit(
        db, action=action, entity="tasks_private" if task.is_private else "tasks", entity_id=task.id,
        organization_id=ctx.organization_id, user_id=ctx.user.id, old_values=old,
        new_values={"title": task.title, "due_date": str(task.due_date), "status": task.status},
    )  # fmt: skip


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    status_filter: str | None = None,
    period: date | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    today = date.today()
    mark_overdue(db, ctx.organization_id, today)
    db.commit()
    stmt = select(Task).where(_visible(ctx))
    if status_filter:
        if status_filter not in STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Stare necunoscută")
        stmt = stmt.where(Task.status == status_filter)
    if period:
        stmt = stmt.where(Task.period == period.replace(day=1))
    return [_out(t, today) for t in db.scalars(stmt.order_by(Task.due_date, Task.title))]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> TaskOut:
    ctx.require(POSTING_ROLES)
    task = Task(
        organization_id=ctx.organization_id, owner_user_id=ctx.user.id, title=body.title.strip(), due_date=body.due_date,
        period=body.period.replace(day=1) if body.period else None, is_private=body.is_private, status="open",
    )  # fmt: skip
    db.add(task)
    db.flush()
    _audit(db, ctx, "create", task)
    db.commit()
    return _out(task, date.today())


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID, body: TaskUpdate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TaskOut:
    task = _get_task(db, ctx, task_id)
    _can_change(ctx, task)
    old = {"title": task.title, "due_date": str(task.due_date)}
    if body.title is not None:
        task.title = body.title.strip()
    if body.due_date is not None:
        task.due_date = body.due_date
        if task.status in ("open", "overdue"):
            task.status = "overdue" if body.due_date < date.today() else "open"
    _audit(db, ctx, "update", task, old)
    db.commit()
    return _out(task, date.today())


def _set_status(db: Session, ctx: OrgContext, task_id: uuid.UUID, new: str) -> TaskOut:
    task = _get_task(db, ctx, task_id)
    _can_change(ctx, task)
    today = date.today()
    old = {"status": task.status}
    if new == "open":
        task.status = "overdue" if task.due_date < today else "open"
        task.done_at = None
    else:
        task.status = new
        task.done_at = datetime.now() if new == "done" else None
    _audit(db, ctx, "update", task, old)
    db.commit()
    return _out(task, today)


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
def task_done(task_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> TaskOut:
    return _set_status(db, ctx, task_id, "done")


@router.post("/tasks/{task_id}/skip", response_model=TaskOut)
def task_skip(task_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> TaskOut:
    return _set_status(db, ctx, task_id, "skipped")


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
def task_reopen(task_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> TaskOut:
    return _set_status(db, ctx, task_id, "open")


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    task = _get_task(db, ctx, task_id)
    _can_change(ctx, task)
    _audit(db, ctx, "delete", task)
    db.delete(task)
    db.commit()


@router.post("/tasks/sync-calendar", response_model=list[TaskOut])
def sync_calendar_endpoint(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[TaskOut]:
    """Creează sarcini pentru termenele de raportare nedepuse și le închide pe cele depuse."""
    ctx.require(POSTING_ROLES)
    today = date.today()
    org = db.get(Organization, ctx.organization_id)
    created = sync_calendar_tasks(db, org, ctx.user.id, today)
    mark_overdue(db, ctx.organization_id, today)
    for t in created:
        _audit(db, ctx, "create", t)
    db.commit()
    return [_out(t, today) for t in created]


# ───────────────────── șabloane recurente ─────────────────────


def _template_out(t: TaskTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id, organization_id=t.organization_id, title=t.title, recurrence=t.recurrence,
        remind_days_before=t.remind_days_before, is_active=t.is_active, standard=t.organization_id is None,
    )  # fmt: skip


def _validate_recurrence(rule: str) -> None:
    try:
        parse_recurrence(rule)
    except RecurrenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


def _own_template(db: Session, ctx: OrgContext, template_id: uuid.UUID) -> TaskTemplate:
    t = db.scalar(
        select(TaskTemplate).where(TaskTemplate.id == template_id, TaskTemplate.organization_id == ctx.organization_id)
    )
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Șablonul nu a fost găsit")
    return t


@router.get("/task-templates", response_model=list[TemplateOut])
def list_templates(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[TemplateOut]:
    rows = db.scalars(
        select(TaskTemplate)
        .where(or_(TaskTemplate.organization_id == ctx.organization_id, TaskTemplate.organization_id.is_(None)))
        .order_by(TaskTemplate.title)
    )
    return [_template_out(t) for t in rows]


@router.post("/task-templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(body: TemplateIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> TemplateOut:
    ctx.require(ADMIN_ROLES)
    _validate_recurrence(body.recurrence)
    t = TaskTemplate(
        organization_id=ctx.organization_id, title=body.title.strip(), recurrence=body.recurrence.strip().upper(),
        remind_days_before=body.remind_days_before, is_active=body.is_active,
    )  # fmt: skip
    db.add(t)
    db.flush()
    write_audit(db, action="create", entity="task_templates", entity_id=t.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"title": t.title, "recurrence": t.recurrence})  # fmt: skip
    db.commit()
    return _template_out(t)


@router.put("/task-templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: uuid.UUID, body: TemplateIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> TemplateOut:
    ctx.require(ADMIN_ROLES)
    t = _own_template(db, ctx, template_id)
    _validate_recurrence(body.recurrence)
    old = {"title": t.title, "recurrence": t.recurrence, "is_active": t.is_active}
    t.title, t.recurrence = body.title.strip(), body.recurrence.strip().upper()
    t.remind_days_before, t.is_active = body.remind_days_before, body.is_active
    write_audit(db, action="update", entity="task_templates", entity_id=t.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, old_values=old, new_values={"title": t.title, "recurrence": t.recurrence, "is_active": t.is_active})  # fmt: skip
    db.commit()
    return _template_out(t)


@router.delete("/task-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> None:
    ctx.require(ADMIN_ROLES)
    t = _own_template(db, ctx, template_id)
    # sarcinile deja generate rămân, fără legătura cu șablonul
    for task in db.scalars(select(Task).where(Task.template_id == t.id, Task.organization_id == ctx.organization_id)):
        task.template_id = None
    write_audit(db, action="delete", entity="task_templates", entity_id=t.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, old_values={"title": t.title})  # fmt: skip
    db.delete(t)
    db.commit()


@router.post("/tasks/generate", response_model=list[TaskOut])
def generate_tasks(body: GenerateIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[TaskOut]:
    """Sarcinile lunii din șabloanele active (o singură dată pe șablon și lună)."""
    ctx.require(POSTING_ROLES)
    today = date.today()
    created = generate_from_templates(db, ctx.organization_id, ctx.user.id, body.period or today)
    mark_overdue(db, ctx.organization_id, today)
    for t in created:
        _audit(db, ctx, "create", t)
    db.commit()
    return [_out(t, today) for t in created]
