from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import get_current_user
from app.auth.models import OrganizationMember, User
from app.core.db import get_db
from app.core.enums import AccountingMethod, EntityType, UserRole
from app.features.service import enable_defaults
from app.workspaces.models import Organization, Workspace
from app.workspaces.schemas import OrganizationBrief, WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["baze"])

SINGLE_ENTRY_TYPES = {EntityType.ii, EntityType.gt}


@router.get("", response_model=list[WorkspaceOut])
def my_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[WorkspaceOut]:
    """„Bazele mele”: bazele în care utilizatorul are cel puțin o organizație."""
    rows = db.execute(
        select(Workspace, Organization, OrganizationMember.role)
        .join(Organization, Organization.workspace_id == Workspace.id)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(Workspace.name, Organization.name)
    ).all()
    workspaces: dict = {}
    orgs: dict = defaultdict(list)
    for ws, org, role in rows:
        workspaces[ws.id] = ws
        orgs[ws.id].append(
            OrganizationBrief(
                id=org.id,
                name=org.name,
                idno=org.idno,
                entity_type=org.entity_type,
                accounting_method=org.accounting_method,
                role=role,
            )
        )
    return [
        WorkspaceOut(id=ws.id, name=ws.name, source=ws.source, created_at=ws.created_at, organizations=orgs[ws.id])
        for ws in workspaces.values()
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> WorkspaceOut:
    if db.scalar(select(Organization.id).where(Organization.idno == body.idno)):
        raise HTTPException(status.HTTP_409_CONFLICT, "O organizație cu acest IDNO există deja")
    ws = Workspace(name=body.name, created_by=user.id, source="empty")
    db.add(ws)
    db.flush()
    method = AccountingMethod.single_entry if body.entity_type in SINGLE_ENTRY_TYPES else AccountingMethod.double_entry
    org = Organization(
        workspace_id=ws.id,
        name=body.organization_name,
        idno=body.idno,
        entity_type=body.entity_type,
        accounting_method=method,
    )
    db.add(org)
    db.flush()
    enable_defaults(db, org, date.today())
    # cine creează baza o administrează
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=UserRole.admin))
    write_audit(
        db,
        action="create",
        entity="workspaces",
        entity_id=ws.id,
        organization_id=org.id,
        user_id=user.id,
        new_values={"name": ws.name, "organization": org.name, "idno": org.idno},
    )
    db.commit()
    db.refresh(ws)
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        source=ws.source,
        created_at=ws.created_at,
        organizations=[
            OrganizationBrief(
                id=org.id,
                name=org.name,
                idno=org.idno,
                entity_type=org.entity_type,
                accounting_method=org.accounting_method,
                role=UserRole.admin,
            )
        ],
    )
