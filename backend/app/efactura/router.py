"""e-Factura: import XML → factură primită, export XML al facturii, statutul mesajelor."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.efactura.models import EfacturaMessage
from app.efactura.service import STATUSES, EfacturaError, export_invoice, import_invoice
from app.workspaces.models import Organization

router = APIRouter(prefix="/organizations/{organization_id}/efactura", tags=["e-Factura"])


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    efactura_id: str
    status: str | None
    document_id: uuid.UUID | None
    synced_at: datetime | None

    model_config = {"from_attributes": True}


class ImportIn(BaseModel):
    xml: str = Field(min_length=1, max_length=5_000_000)


class StatusIn(BaseModel):
    status: str


def _message(db: Session, ctx: OrgContext, message_id: uuid.UUID) -> EfacturaMessage:
    msg = db.scalar(
        select(EfacturaMessage).where(EfacturaMessage.id == message_id,
                                      EfacturaMessage.organization_id == ctx.organization_id)  # fmt: skip
    )
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesajul nu a fost găsit")
    return msg


def _fail(db: Session, exc: EfacturaError) -> HTTPException:
    db.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/messages", response_model=list[MessageOut])
def list_messages(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[EfacturaMessage]:
    return list(
        db.scalars(
            select(EfacturaMessage)
            .where(EfacturaMessage.organization_id == ctx.organization_id)
            .order_by(EfacturaMessage.synced_at.desc().nulls_last(), EfacturaMessage.efactura_id)
            .limit(500)
        )
    )


@router.post("/import", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def import_xml(body: ImportIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> EfacturaMessage:
    ctx.require(POSTING_ROLES)
    try:
        _, msg = import_invoice(db, organization_id=ctx.organization_id, user_id=ctx.user.id, text=body.xml)
    except EfacturaError as exc:
        raise _fail(db, exc) from None
    db.commit()
    return msg


@router.post("/invoices/{document_id}/export", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def export_xml(document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> EfacturaMessage:
    ctx.require(POSTING_ROLES)
    org = db.get(Organization, ctx.organization_id)
    assert org is not None
    try:
        msg = export_invoice(db, organization_id=ctx.organization_id, user_id=ctx.user.id, document_id=document_id,
                             supplier_name=org.name, supplier_idno=org.idno)  # fmt: skip
    except EfacturaError as exc:
        raise _fail(db, exc) from None
    db.commit()
    return msg


@router.get("/messages/{message_id}/xml")
def message_xml(message_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> Response:
    msg = _message(db, ctx, message_id)
    return Response(msg.payload_xml or "", media_type="application/xml")


@router.put("/messages/{message_id}/status", response_model=MessageOut)
def set_status(message_id: uuid.UUID, body: StatusIn, ctx: OrgContext = Depends(get_org_context),
               db: Session = Depends(get_db)) -> EfacturaMessage:  # fmt: skip
    """Statutul trimiterii (sent → signed → accepted / rejected), până la adaptorul SFS automat."""
    ctx.require(POSTING_ROLES)
    msg = _message(db, ctx, message_id)
    if msg.direction != "sent":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Statutul se schimbă doar pentru mesajele trimise")
    if body.status not in STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Statut necunoscut; valori: {', '.join(STATUSES)}")
    msg.status, msg.synced_at = body.status, datetime.now()
    db.commit()
    return msg
