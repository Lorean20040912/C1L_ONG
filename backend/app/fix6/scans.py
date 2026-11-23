"""Documente scanate: încărcare, recunoaștere AI a câmpurilor, verificare și validare de către contabil."""

import base64
import binascii
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.assistant.llm import LLMClient, LLMError, LLMNotConfigured, get_llm_client
from app.audit.service import write_audit
from app.auth.deps import POSTING_ROLES, OrgContext, get_org_context
from app.catalogs.models import Counterparty
from app.core.db import get_db
from app.core.enums import DocumentStatus, DocumentType
from app.documents.models import Document
from app.fix6.models import DocumentSource, ScannedFile

router = APIRouter(prefix="/organizations/{organization_id}/scanned-documents", tags=["documente scanate"])

MAX_BYTES = 10 * 1024 * 1024
MIME = {"application/pdf", "image/png", "image/jpeg"}

FIELDS_TOOL = {
    "name": "fill_fields",
    "description": "Câmpurile citite din documentul scanat; câmpurile necitibile se omit.",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {"type": "string", "enum": ["invoice", "receipt", "act", "contract", "other"]},
            "supplier_name": {"type": "string"},
            "supplier_idno": {"type": "string", "description": "IDNO / cod fiscal, 13 cifre"},
            "doc_number": {"type": "string"},
            "doc_date": {"type": "string", "description": "AAAA-LL-ZZ"},
            "total_amount": {"type": "number"},
            "currency": {"type": "string", "description": "cod ISO din 3 litere"},
            "confidence": {"type": "number", "description": "încrederea generală, 0–1"},
        },
    },
}


def llm_client() -> LLMClient:
    try:
        return get_llm_client()
    except LLMNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Recunoașterea AI nu este configurată (lipsește cheia API); completați câmpurile manual") from None  # fmt: skip


class ScanOut(BaseModel):
    id: uuid.UUID
    file_name: str | None
    mime_type: str | None
    status: DocumentStatus
    type: DocumentType | None
    counterparty_id: uuid.UUID | None
    counterparty: str | None
    doc_number: str | None
    doc_date: date | None
    total_amount: Decimal | None
    currency: str | None
    source_id: uuid.UUID | None
    ai_fields: dict | None
    ai_at: datetime | None
    is_posted: bool


class ScanIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=200)
    mime_type: str
    content_base64: str = Field(min_length=4)
    source_id: uuid.UUID | None = None


class ScanPatch(BaseModel):
    type: DocumentType | None = None
    counterparty_id: uuid.UUID | None = None
    doc_number: str | None = None
    doc_date: date | None = None
    total_amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


def _out(db: Session, doc: Document) -> ScanOut:
    sf = db.get(ScannedFile, doc.id)
    cp = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    return ScanOut(
        id=doc.id, file_name=doc.file_name, mime_type=doc.mime_type, status=doc.status, type=doc.type,
        counterparty_id=doc.counterparty_id, counterparty=cp.name if cp else None, doc_number=doc.doc_number,
        doc_date=doc.doc_date, total_amount=doc.total_amount, currency=doc.currency,
        source_id=sf.source_id if sf else None, ai_fields=sf.ai_fields if sf else None, ai_at=sf.ai_at if sf else None,
        is_posted=bool(doc.is_posted),
    )  # fmt: skip


def _doc(db: Session, ctx: OrgContext, doc_id: uuid.UUID, lock: bool = False) -> Document:
    q = select(Document).where(Document.id == doc_id, Document.organization_id == ctx.organization_id,
                               exists().where(ScannedFile.document_id == Document.id))  # fmt: skip
    doc = db.scalar(q.with_for_update() if lock else q)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documentul scanat nu a fost găsit")
    return doc


@router.get("", response_model=list[ScanOut])
def list_scans(status_filter: DocumentStatus | None = None, ctx: OrgContext = Depends(get_org_context),
               db: Session = Depends(get_db)):  # fmt: skip
    q = (select(Document)
         .where(Document.organization_id == ctx.organization_id, Document.deletion_mark.is_not(True),
                exists().where(ScannedFile.document_id == Document.id))
         .order_by(Document.created_at.desc()).limit(500))  # fmt: skip
    if status_filter:
        q = q.where(Document.status == status_filter)
    return [_out(db, d) for d in db.scalars(q)]


@router.post("", response_model=ScanOut, status_code=201)
def upload_scan(body: ScanIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    if body.mime_type not in MIME:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Se acceptă doar PDF, PNG sau JPEG")
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fișierul nu este codificat corect") from None
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fișierul trebuie să aibă între 1 octet și 10 MB")
    if body.source_id and db.scalar(select(DocumentSource.id).where(DocumentSource.id == body.source_id,
                                    DocumentSource.organization_id == ctx.organization_id)) is None:  # fmt: skip
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sursa nu aparține organizației")
    digest = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document.id).where(Document.organization_id == ctx.organization_id, Document.sha256 == digest)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Acest fișier a fost deja încărcat")
    doc = Document(organization_id=ctx.organization_id, type=DocumentType.other, status=DocumentStatus.new,
                   file_name=body.file_name, mime_type=body.mime_type, sha256=digest, uploaded_by=ctx.user.id)  # fmt: skip
    db.add(doc)
    db.flush()
    db.add(ScannedFile(document_id=doc.id, organization_id=ctx.organization_id, source_id=body.source_id, content=data))
    write_audit(db, action="create", entity="scanned_documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"file": body.file_name})  # fmt: skip
    db.commit()
    return _out(db, doc)


@router.get("/{doc_id}/file")
def scan_file(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    doc = _doc(db, ctx, doc_id)
    sf = db.get(ScannedFile, doc.id)
    return Response(sf.content, media_type=doc.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{doc.id}"'})  # fmt: skip


@router.post("/{doc_id}/extract", response_model=ScanOut)
def extract_fields(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db),
                   llm: LLMClient = Depends(llm_client)):  # fmt: skip
    """Recunoașterea AI: completează doar câmpurile goale; contabilul le verifică înainte de validare."""
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.status in (DocumentStatus.validated, DocumentStatus.rejected):
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul validat sau respins nu se mai recunoaște")
    sf = db.get(ScannedFile, doc.id)
    block_type = "document" if doc.mime_type == "application/pdf" else "image"
    content = [
        {"type": block_type, "source": {"type": "base64", "media_type": doc.mime_type,
                                        "data": base64.b64encode(sf.content).decode()}},
        {"type": "text", "text": "Citește documentul contabil și apelează fill_fields cu datele găsite."},
    ]  # fmt: skip
    try:
        reply = llm.complete("Ești un asistent contabil din Republica Moldova; extragi câmpurile documentelor scanate.",
                             [{"role": "user", "content": content}], [FIELDS_TOOL])  # fmt: skip
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    call = next((c for c in reply.tool_calls if c.name == "fill_fields"), None)
    if call is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "AI nu a putut citi documentul; completați manual")
    fields = {k: v for k, v in call.input.items() if v not in (None, "")}
    sf.ai_fields = fields
    sf.ai_at = datetime.now(timezone.utc)
    if not doc.doc_number and fields.get("doc_number"):
        doc.doc_number = str(fields["doc_number"])[:50]
    if not doc.doc_date and fields.get("doc_date"):
        try:
            doc.doc_date = date.fromisoformat(str(fields["doc_date"]))
        except ValueError:
            pass
    if doc.total_amount is None and isinstance(fields.get("total_amount"), (int, float)) and fields["total_amount"] > 0:
        doc.total_amount = Decimal(str(fields["total_amount"])).quantize(Decimal("0.01"))
    if not doc.currency and isinstance(fields.get("currency"), str) and len(fields["currency"]) == 3:
        doc.currency = fields["currency"].upper()
    if doc.type == DocumentType.other and fields.get("document_type") in {t.value for t in DocumentType}:
        doc.type = DocumentType(fields["document_type"])
    if not doc.counterparty_id and fields.get("supplier_idno"):
        doc.counterparty_id = db.scalar(select(Counterparty.id).where(
            Counterparty.organization_id == ctx.organization_id, Counterparty.idno == str(fields["supplier_idno"])))  # fmt: skip
    doc.status = DocumentStatus.to_review
    write_audit(db, action="update", entity="scanned_documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"ai_fields": sorted(fields)})  # fmt: skip
    db.commit()
    return _out(db, doc)


@router.patch("/{doc_id}", response_model=ScanOut)
def patch_scan(doc_id: uuid.UUID, body: ScanPatch, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.status == DocumentStatus.validated:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul validat nu se mai modifică; redeschideți-l")
    changes = body.model_dump(exclude_unset=True)
    cp_id = changes.get("counterparty_id")
    if cp_id and db.scalar(select(Counterparty.id).where(Counterparty.id == cp_id, Counterparty.organization_id == ctx.organization_id)) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Contrapartida nu aparține organizației")
    for k, v in changes.items():
        setattr(doc, k, v.upper() if k == "currency" and v else v)
    if doc.status in (DocumentStatus.new, DocumentStatus.rejected):
        doc.status = DocumentStatus.to_review
    db.commit()
    return _out(db, doc)


def _missing(doc: Document) -> list[str]:
    miss = []
    if doc.type in (None, DocumentType.other):
        miss.append("tipul documentului")
    if not doc.doc_date:
        miss.append("data")
    if not doc.total_amount:
        miss.append("suma")
    if doc.type in (DocumentType.invoice, DocumentType.e_invoice, DocumentType.act) and not doc.counterparty_id:
        miss.append("furnizorul")
    return miss


@router.post("/{doc_id}/validate", response_model=ScanOut)
def validate_scan(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.status == DocumentStatus.validated:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este deja validat")
    miss = _missing(doc)
    if miss:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Completați înainte de validare: " + ", ".join(miss))
    doc.status = DocumentStatus.validated
    doc.validated_by = ctx.user.id
    doc.validated_at = datetime.now()
    write_audit(db, action="update", entity="scanned_documents", entity_id=doc.id, organization_id=ctx.organization_id,
                user_id=ctx.user.id, new_values={"status": "validated"})  # fmt: skip
    db.commit()
    return _out(db, doc)


@router.post("/{doc_id}/reject", response_model=ScanOut)
def reject_scan(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este înregistrat contabil; anulați întâi înregistrarea")
    doc.status = DocumentStatus.rejected
    db.commit()
    return _out(db, doc)


@router.post("/{doc_id}/reopen", response_model=ScanOut)
def reopen_scan(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul este înregistrat contabil; anulați întâi înregistrarea")
    doc.status = DocumentStatus.to_review
    doc.validated_by = None
    doc.validated_at = None
    db.commit()
    return _out(db, doc)


@router.delete("/{doc_id}", status_code=204)
def delete_scan(doc_id: uuid.UUID, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    ctx.require(POSTING_ROLES)
    doc = _doc(db, ctx, doc_id, lock=True)
    if doc.is_posted or doc.status == DocumentStatus.validated:
        raise HTTPException(status.HTTP_409_CONFLICT, "Documentul validat sau înregistrat nu se șterge")
    doc.deletion_mark = True
    db.commit()
