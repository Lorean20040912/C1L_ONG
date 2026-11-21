"""Importul extraselor și exportul ordinelor de plată (docs/09, docs/02 §6).

Import: fișier → rânduri normalizate (parsers) → cheia anti-dublură → contrapartida (IDNO, apoi IBAN)
→ propunerea de grant după istoric → ordin de plată-ciornă (sau legătura cu ordinul exportat deja)
→ contabilul confirmă și înregistrează (`post_transactions`).

Funcțiile nu fac commit (le face ruta).
"""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.bank.exporters import ExportError, ExportOrder, clean_doc_number, export_orders
from app.bank.models import BankAccount, BankFormat, BankImport, BankTransaction, PaymentBatch
from app.bank.parsers import ParseError, StatementRow, parse_statement
from app.bank.rates import RateError, fresh_rate
from app.catalogs.models import Counterparty
from app.core.crypto_bank import normalize_iban
from app.core.enums import DocumentType, PaymentDirection
from app.documents.models import Document, PaymentOrder, PaymentOrderLine
from app.documents.posting import BASE_CURRENCY, post_payment
from app.grants.models import Grant
from app.posting.engine import PostingError
from app.workspaces.models import Organization

IMPORT, EXPORT = "import_statement", "export_payments"
FILE_EXTENSIONS = {"dbf": "dbf", "xml": "xml", "csv": "csv", "txt": "txt", "dbo": "txt"}


class BankError(PostingError):
    """Eroare de date (→ 422)."""


def format_for(db: Session, organization_id: uuid.UUID, format_id: uuid.UUID, direction: str) -> BankFormat:
    fmt = db.get(BankFormat, format_id)
    if fmt is None or fmt.organization_id not in (None, organization_id):
        raise BankError("Profilul băncii nu a fost găsit")
    if fmt.direction != direction:
        raise BankError("Profilul ales nu este pentru " + ("importul extraselor" if direction == IMPORT else "export"))
    return fmt


def bank_account_for(db: Session, organization_id: uuid.UUID, bank_account_id: uuid.UUID) -> BankAccount:
    bank = db.get(BankAccount, bank_account_id)
    if bank is None or bank.organization_id != organization_id:
        raise BankError("Contul bancar nu aparține organizației")
    return bank


# ───────────────────────── import ─────────────────────────


def dedup_key(bank: BankAccount, row: StatementRow, occurrence: int = 1) -> str:
    """Cont bancar + dată + nr. document + sumă + D/C (+ IBAN contrapartidă); rândurile identice din același
    fișier se deosebesc prin numărul apariției, deci reimportul aceluiași fișier dă aceleași chei."""
    dc = "D" if row.direction == PaymentDirection.outgoing else "C"
    parts = [str(bank.id), row.tx_date.isoformat(), clean_doc_number(row.doc_number) or (row.doc_number or ""),
             f"{row.amount:.2f}", dc, row.counterparty_iban or "", str(occurrence)]  # fmt: skip
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def find_counterparty(
    db: Session, organization_id: uuid.UUID, idno: str | None, iban: str | None
) -> Counterparty | None:
    if idno:
        found = db.scalar(
            select(Counterparty).where(Counterparty.organization_id == organization_id, Counterparty.idno == idno)
        )
        if found:
            return found
    if iban:
        for cp in db.scalars(
            select(Counterparty).where(Counterparty.organization_id == organization_id, Counterparty.iban_enc.is_not(None))
        ):
            if normalize_iban(cp.iban_enc) == iban:
                return cp
    return None


def suggest_grant(db: Session, organization_id: uuid.UUID, bank: BankAccount, counterparty_id: uuid.UUID | None):
    """Contul dedicat grantului, altfel grantul ultimei plăți către / de la aceeași contrapartidă."""
    if bank.grant_id:
        return bank.grant_id
    if counterparty_id is None:
        return None
    return db.scalar(
        select(PaymentOrderLine.grant_id)
        .join(PaymentOrder, PaymentOrder.id == PaymentOrderLine.payment_order_id)
        .join(Document, Document.id == PaymentOrder.document_id)
        .where(
            Document.organization_id == organization_id,
            Document.counterparty_id == counterparty_id,
            PaymentOrderLine.grant_id.is_not(None),
        )
        .order_by(Document.is_posted.desc(), Document.doc_date.desc(), Document.created_at.desc())
        .limit(1)
    )


def _exported_order(db: Session, organization_id: uuid.UUID, bank: BankAccount, row: StatementRow):
    """Ordinul nostru (exportat sau ciornă) pe care îl confirmă rândul: nr. document + sumă + IBAN."""
    if row.direction != PaymentDirection.outgoing or not row.doc_number:
        return None
    candidates = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(
            Document.organization_id == organization_id,
            PaymentOrder.bank_account_id == bank.id,
            PaymentOrder.direction == PaymentDirection.outgoing,
            Document.total_amount == row.amount,
            or_(PaymentOrder.bank_status.is_(None), PaymentOrder.bank_status != "executed"),
        )
    ).all()
    number = clean_doc_number(row.doc_number)
    for doc, order in candidates:
        if clean_doc_number(doc.doc_number) != number:
            continue
        if row.counterparty_iban and order.beneficiary_iban and normalize_iban(order.beneficiary_iban) != row.counterparty_iban:
            continue
        return doc, order
    return None


def _draft(db: Session, organization_id: uuid.UUID, bank: BankAccount, row: StatementRow, user_id, cp, grant_id):
    doc = Document(
        organization_id=organization_id,
        type=DocumentType.payment_order,
        doc_number=row.doc_number or f"EXT-{row.tx_date:%Y%m%d}-{row.line_no}",
        doc_date=row.tx_date,
        total_amount=row.amount,
        currency=bank.currency,
        counterparty_id=cp.id if cp else None,
        uploaded_by=user_id,
    )
    db.add(doc)
    db.flush()
    rate = None
    if bank.currency != BASE_CURRENCY:
        try:
            rate = fresh_rate(db, organization_id, bank.currency, row.tx_date).rate
        except RateError:
            rate = None  # la înregistrare contabilul vede motivul (curs lipsă / depășit) și îl poate introduce
    order = PaymentOrder(
        document_id=doc.id,
        direction=row.direction,
        exchange_rate=rate,
        purpose=row.purpose,
        bank_account_id=bank.id,
        beneficiary_iban=row.counterparty_iban,
        beneficiary_name=row.counterparty_name or (cp.name if cp else None),
        beneficiary_idno=row.counterparty_idno or (cp.idno if cp else None),
        bank_status="executed",
        lines=[PaymentOrderLine(grant_id=grant_id, amount=row.amount)] if grant_id else [],
    )
    db.add(order)
    db.flush()
    return doc


@dataclass
class ImportOutcome:
    bank_import: BankImport
    transactions: list[BankTransaction] = field(default_factory=list)


def import_statement(
    db: Session,
    *,
    organization_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    format_id: uuid.UUID,
    file_name: str | None,
    data: bytes,
    user_id: uuid.UUID | None,
) -> ImportOutcome:
    bank = bank_account_for(db, organization_id, bank_account_id)
    fmt = format_for(db, organization_id, format_id, IMPORT)
    our_iban = bank.iban
    try:
        parsed = parse_statement(data, fmt.file_type, fmt.encoding, fmt.layout, our_iban)
    except ParseError as exc:
        raise BankError(f"Fișierul nu se poate citi cu profilul {fmt.bank_name} ({fmt.file_type}): {exc}") from None

    record = BankImport(
        organization_id=organization_id,
        bank_account_id=bank.id,
        format_id=fmt.id,
        file_name=file_name,
        file_sha256=hashlib.sha256(data).hexdigest(),
        imported_by=user_id,
    )
    db.add(record)
    db.flush()
    errors = list(parsed.errors)
    outcome = ImportOutcome(record)
    seen: dict[str, int] = defaultdict(int)
    skipped = 0
    for row in parsed.rows:
        if row.account and normalize_iban(our_iban) and row.account != normalize_iban(our_iban):
            errors.append({"line": row.line_no, "error": f"rândul este al contului {row.account}, nu al celui ales"})
            continue
        if row.currency and row.currency.isalpha() and row.currency != bank.currency:
            errors.append({"line": row.line_no, "error": f"valuta {row.currency} diferă de valuta contului"})
            continue
        base = dedup_key(bank, row, 0)
        seen[base] += 1
        key = dedup_key(bank, row, seen[base])
        if db.scalar(select(BankTransaction.id).where(BankTransaction.dedup_key == key)):
            skipped += 1
            continue
        cp = find_counterparty(db, organization_id, row.counterparty_idno, row.counterparty_iban)
        tx = BankTransaction(
            import_id=record.id,
            dedup_key=key,
            tx_date=row.tx_date,
            direction=row.direction,
            amount=row.amount,
            counterparty_iban=row.counterparty_iban,
            counterparty_idno=row.counterparty_idno,
            counterparty_name=row.counterparty_name or (cp.name if cp else None),
            purpose=row.purpose,
            doc_number=row.doc_number,
            currency=bank.currency,
        )
        existing = _exported_order(db, organization_id, bank, row)
        if existing:
            doc, order = existing
            order.bank_status = "executed"
            tx.document_id, tx.match = doc.id, "exported_order"
        else:
            grant_id = suggest_grant(db, organization_id, bank, cp.id if cp else None)
            tx.document_id = _draft(db, organization_id, bank, row, user_id, cp, grant_id).id
            tx.match = "new_draft"
        db.add(tx)
        db.flush()
        outcome.transactions.append(tx)
    record.rows_total = len(parsed.rows) + len(parsed.errors)
    record.rows_created = len(outcome.transactions)
    record.rows_skipped = skipped
    record.rows_failed = len(errors)
    record.errors = errors
    db.flush()
    return outcome


def import_transactions(db: Session, organization_id: uuid.UUID, import_id: uuid.UUID) -> tuple[BankImport, list]:
    record = db.get(BankImport, import_id)
    if record is None or record.organization_id != organization_id:
        raise BankError("Importul nu a fost găsit")
    rows = db.scalars(
        select(BankTransaction).where(BankTransaction.import_id == record.id).order_by(BankTransaction.tx_date)
    ).all()
    return record, list(rows)


@dataclass
class PostItem:
    transaction_id: uuid.UUID
    grant_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    exchange_rate: Decimal | None = None  # cursul introdus de contabil (plăți în valută fără curs proaspăt)


def post_transactions(
    db: Session, organization_id: uuid.UUID, import_id: uuid.UUID, items: list[PostItem], user_id: uuid.UUID | None
) -> dict[uuid.UUID, str | None]:
    """Confirmă rândurile: grantul / contrapartida aleasă de contabil, apoi înregistrarea ordinului.
    Fiecare rând în savepoint propriu: o eroare nu oprește celelalte. Rezultat: id → eroare (None = reușit)."""
    _, rows = import_transactions(db, organization_id, import_id)
    by_id = {tx.id: tx for tx in rows}
    results: dict[uuid.UUID, str | None] = {}
    for item in items:
        tx = by_id.get(item.transaction_id)
        if tx is None:
            results[item.transaction_id] = "Rândul nu aparține importului"
            continue
        if tx.document_id is None:
            results[tx.id] = "Rândul nu are document"
            continue
        savepoint = db.begin_nested()
        try:
            doc = db.get(Document, tx.document_id)
            order = db.scalar(select(PaymentOrder).where(PaymentOrder.document_id == doc.id))
            if doc.is_posted:
                results[tx.id] = None
                savepoint.commit()
                continue
            if item.counterparty_id:
                cp = db.get(Counterparty, item.counterparty_id)
                if cp is None or cp.organization_id != organization_id:
                    raise BankError("Contrapartida nu aparține organizației")
                doc.counterparty_id = cp.id
            if item.grant_id:
                if db.scalar(select(Grant.id).where(Grant.id == item.grant_id, Grant.organization_id == organization_id)) is None:
                    raise BankError("Grantul nu aparține organizației")
                order.lines = [PaymentOrderLine(grant_id=item.grant_id, amount=doc.total_amount)]
            if doc.currency and doc.currency != BASE_CURRENCY:
                if item.exchange_rate is not None:
                    if item.exchange_rate <= 0:
                        raise BankError("Cursul trebuie să fie pozitiv")
                    order.exchange_rate = item.exchange_rate
                else:  # cursul curent din tabel, verificat pe limita de vechime
                    try:
                        order.exchange_rate = fresh_rate(db, organization_id, doc.currency, doc.doc_date).rate
                    except RateError as exc:
                        raise BankError(str(exc)) from None
            db.flush()
            post_payment(db, organization_id, doc.id, user_id)
            savepoint.commit()
            results[tx.id] = None
        except PostingError as exc:
            savepoint.rollback()
            results[tx.id] = str(exc)
        except Exception:  # noqa: BLE001 - o eroare neprevăzută nu strică celelalte rânduri
            savepoint.rollback()
            results[tx.id] = "Rândul nu a putut fi înregistrat"
    return results


def unpost_transactions(
    db: Session, organization_id: uuid.UUID, import_id: uuid.UUID, transaction_ids: list[uuid.UUID], user_id
) -> dict[uuid.UUID, str | None]:
    """Anulează înregistrarea rândurilor (documentul revine la ciornă); id → eroare (None = reușit)."""
    from app.posting.engine import unpost_document

    _, rows = import_transactions(db, organization_id, import_id)
    by_id = {tx.id: tx for tx in rows}
    results: dict[uuid.UUID, str | None] = {}
    for tid in transaction_ids:
        tx = by_id.get(tid)
        if tx is None:
            results[tid] = "Rândul nu aparține importului"
            continue
        if tx.document_id is None:
            results[tid] = "Rândul nu are document"
            continue
        savepoint = db.begin_nested()
        try:
            doc = db.get(Document, tx.document_id)
            if doc is not None and doc.is_posted:
                unpost_document(db, organization_id=organization_id, document_id=doc.id, user_id=user_id)
            savepoint.commit()
            results[tid] = None
        except PostingError as exc:
            savepoint.rollback()
            results[tid] = str(exc)
        except Exception:  # noqa: BLE001 - o eroare neprevăzută nu strică celelalte rânduri
            savepoint.rollback()
            results[tid] = "Anularea rândului nu a reușit"
    return results


# ───────────────────────── export ─────────────────────────


def create_batches(
    db: Session,
    *,
    organization_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    format_id: uuid.UUID,
    force: bool,
    user_id: uuid.UUID | None,
) -> list[PaymentBatch]:
    """Ordinele selectate → câte un lot (fișier) pe cont plătitor; ordinele se marchează „exportat”."""
    if not document_ids:
        raise BankError("Alegeți ordinele de plată")
    fmt = format_for(db, organization_id, format_id, EXPORT)
    org = db.get(Organization, organization_id)
    rows = db.execute(
        select(Document, PaymentOrder)
        .join(PaymentOrder, PaymentOrder.document_id == Document.id)
        .where(Document.organization_id == organization_id, Document.id.in_(set(document_ids)))
        .order_by(Document.doc_date, Document.doc_number)
        .with_for_update(of=PaymentOrder)
    ).all()
    if len(rows) != len(set(document_ids)):
        raise BankError("Unele ordine nu aparțin organizației")
    groups: dict[uuid.UUID, list] = defaultdict(list)
    for doc, order in rows:
        label = f"Ordinul nr. {doc.doc_number}"
        if order.direction != PaymentDirection.outgoing:
            raise BankError(f"{label} nu este o plată (încasările nu se exportă)")
        if order.bank_account_id is None:
            raise BankError(f"{label} nu are cont bancar plătitor")
        if not order.beneficiary_iban:
            raise BankError(f"{label} nu are IBAN-ul beneficiarului")
        if order.bank_status in ("exported", "executed") and not force:
            raise BankError(f"{label} a fost deja exportat; confirmați exportul repetat")
        groups[order.bank_account_id].append((doc, order))

    stamp = datetime.now()
    batches = []
    for bank_id, items in groups.items():
        bank = db.get(BankAccount, bank_id)
        iban = bank.iban
        orders = [
            ExportOrder(
                date=doc.doc_date,
                doc_number=doc.doc_number or "",
                amount=doc.total_amount or Decimal(0),
                currency=doc.currency or bank.currency,
                purpose=order.purpose or "",
                payer_iban=iban,
                payer_idno=org.idno,
                payer_name=org.name,
                beneficiary_iban=normalize_iban(order.beneficiary_iban),
                beneficiary_name=order.beneficiary_name or "",
                beneficiary_idno=order.beneficiary_idno or "",
                is_urgent=bool(order.is_urgent),
                bank_code=bank.bank_code or "",
                transaction_code="101" if order.kind == "grouped_tax" else "001",
            )
            for doc, order in items
        ]
        try:
            content = export_orders(orders, fmt.layout, fmt.encoding)
        except (ExportError, KeyError, ValueError) as exc:
            raise BankError(f"Exportul în formatul {fmt.bank_name} a eșuat: {exc}") from None
        bank_label = (bank.bank_name or fmt.bank_name).replace("/", "-")
        batch = PaymentBatch(
            organization_id=organization_id,
            bank_format_id=fmt.id,
            bank_account_id=bank.id,
            folder_path=f"Bancă/Export/{bank_label}/{stamp:%Y-%m-%d_%H%M}/",
            file_id=f"plati_{iban}.{FILE_EXTENSIONS.get(fmt.file_type, 'txt')}",
            orders_count=len(orders),
            total_amount=sum((o.amount for o in orders), Decimal(0)),
            created_by=user_id,
            content=content,
        )
        db.add(batch)
        db.flush()
        for _, order in items:
            order.batch_id = batch.id
            if order.bank_status != "executed":
                order.bank_status = "exported"
        batches.append(batch)
    db.flush()
    return batches
