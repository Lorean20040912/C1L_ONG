"""Facturile primite: același număr (și serie) de la același furnizor în același an nu se admite de două ori."""

import uuid
from datetime import date

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.catalogs.models import Counterparty
from app.core.enums import DocumentStatus, DocumentType
from app.documents.models import Document, Invoice

PURCHASE_TYPES = (DocumentType.invoice, DocumentType.e_invoice)


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def duplicate_invoice(db: Session, *, organization_id: uuid.UUID, counterparty_id: uuid.UUID | None, doc_number: str | None,
                      doc_date: date | None, series: str | None = None, exclude_id: uuid.UUID | None = None) -> Document | None:
    """Documentul existent cu același furnizor, număr (fără deosebire de litere/spații), serie și an, dacă există."""
    if not counterparty_id or not _norm(doc_number) or doc_date is None:
        return None
    q = (select(Document, Invoice.series).outerjoin(Invoice, Invoice.document_id == Document.id)
         .where(Document.organization_id == organization_id, Document.counterparty_id == counterparty_id,
                Document.type.in_(PURCHASE_TYPES), Document.deletion_mark.is_not(True),
                Document.status != DocumentStatus.rejected,
                func.lower(func.trim(Document.doc_number)) == _norm(doc_number),
                extract("year", Document.doc_date) == doc_date.year))  # fmt: skip
    if exclude_id:
        q = q.where(Document.id != exclude_id)
    for doc, other_series in db.execute(q):
        if _norm(other_series) == _norm(series):
            return doc
    return None


def duplicate_message(db: Session, doc: Document, doc_number: str, doc_date: date) -> str:
    cp = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    when = doc.doc_date.strftime("%d.%m.%Y") if doc.doc_date else str(doc_date.year)
    return (f"Factura nr. {doc_number.strip()} de la furnizorul „{cp.name if cp else 'necunoscut'}” este deja introdusă în anul "
            f"{doc_date.year} (din {when}); același număr de la același furnizor nu se admite de două ori")  # fmt: skip
