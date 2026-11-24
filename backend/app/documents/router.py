import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.core.db import get_db
from app.core.enums import DocumentStatus, DocumentType
from app.documents.models import Document

router = APIRouter(prefix="/organizations/{organization_id}/documents", tags=["documente"])


class DocumentCreate(BaseModel):
    type: DocumentType
    doc_number: str | None = None
    doc_date: date
    total_amount: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    counterparty_id: uuid.UUID | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    type: DocumentType | None
    status: DocumentStatus
    is_posted: bool | None
    deletion_mark: bool | None
    version: int | None
    doc_number: str | None
    doc_date: date | None
    total_amount: Decimal | None
    currency: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[DocumentOut])
def list_documents(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.organization_id == ctx.organization_id)
            .order_by(Document.doc_date.desc(), Document.created_at.desc())
            .limit(500)
        )
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> Document:
    ctx.require(POSTING_ROLES)
    doc = Document(organization_id=ctx.organization_id, uploaded_by=ctx.user.id, **body.model_dump())
    db.add(doc)
    db.flush()
    write_audit(
        db,
        action="create",
        entity="documents",
        entity_id=doc.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
    )
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)
) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.organization_id == ctx.organization_id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul nu a fost găsit")
    return doc
