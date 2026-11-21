"""Importul din exportul XML al 1C: plan de conturi, contrapartide, solduri inițiale, reconcilierea balanței.

Format (prelucrarea de export XML, docs/01 F7.1) — vezi `parse_export`. Importul se poate repeta
fără dubluri: obiectele se regăsesc după GUID (`onec_id_map`), conturile după cod, contrapartidele
după GUID sau IDNO. Funcțiile nu fac commit (DEZVOLTARE.md, principiul 5)."""

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.catalogs.models import Account, Counterparty
from app.core.enums import AccountKind, DocumentType, ImportStatus, SubcontoType
from app.documents.models import Document
from app.onec_import.models import OnecIdMap, OnecImportRun, OpeningBalance
from app.posting.engine import AnalyticsInput, LineInput, PostingError, post_document
from app.posting.models import EntryLine

OFFSET_ACCOUNT_CODE = "000"  # cont tehnic de contrapartidă pentru soldurile inițiale (partidă simplă → dublă)
OPENING_DOC_NUMBER = "SOLD-INITIAL"
CATALOG_COUNTERPARTY = "Catalog.Контрагенты"
CENT = Decimal("0.01")


class ImportFormatError(ValueError):
    """Fișierul de export nu poate fi citit; mesajul e pentru utilizator."""


@dataclass
class AccountRow:
    code: str
    name: str
    kind: AccountKind
    is_currency: bool


@dataclass
class CounterpartyRow:
    guid: uuid.UUID
    name: str
    idno: str | None
    vat_code: str | None
    address: str | None


@dataclass
class BalanceRow:
    account_code: str
    debit: Decimal
    credit: Decimal
    counterparty_guid: uuid.UUID | None = None


@dataclass
class ParsedExport:
    accounts: list[AccountRow] = field(default_factory=list)
    counterparties: list[CounterpartyRow] = field(default_factory=list)
    balance_date: date | None = None
    balances: list[BalanceRow] = field(default_factory=list)
    control_date: date | None = None
    control: list[BalanceRow] = field(default_factory=list)


def _money(value: str | None, where: str) -> Decimal:
    try:
        amount = Decimal((value or "0").replace(",", ".").strip() or "0")
    except InvalidOperation:
        raise ImportFormatError(f"{where}: sumă invalidă „{value}”") from None
    if not amount.is_finite() or amount < 0:
        raise ImportFormatError(f"{where}: suma trebuie să fie ≥ 0")
    return amount.quantize(CENT)


def _date(value: str | None, where: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise ImportFormatError(f"{where}: data trebuie să fie AAAA-LL-ZZ") from None


def _guid(value: str | None, where: str) -> uuid.UUID:
    try:
        return uuid.UUID((value or "").strip())
    except ValueError:
        raise ImportFormatError(f"{where}: GUID invalid „{value}”") from None


def parse_xml(text: str) -> ET.Element:
    """Parsare sigură: DOCTYPE / entități sunt refuzate (XXE, „billion laughs”)."""
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ImportFormatError("DOCTYPE și entitățile XML nu sunt permise")
    try:
        return ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ImportFormatError(f"XML invalid: {exc}") from None


def _balances(node: ET.Element, label: str) -> list[BalanceRow]:
    rows = []
    for i, b in enumerate(node.findall("Balance"), start=1):
        where = f"{label}, rândul {i}"
        code = (b.get("account") or "").strip()
        if not code:
            raise ImportFormatError(f"{where}: lipsește contul")
        cp = b.get("counterparty_guid")
        rows.append(
            BalanceRow(code, _money(b.get("debit"), where), _money(b.get("credit"), where),
                       _guid(cp, where) if cp else None)  # fmt: skip
        )
    return rows


def parse_export(text: str) -> ParsedExport:
    """Structura exportului::

        <Export>
          <Accounts><Account code="221" name="Creanțe" kind="active" currency="false"/></Accounts>
          <Counterparties><Counterparty guid="…" name="…" idno="…" vat_code="…" address="…"/></Counterparties>
          <Balances date="2026-01-01"><Balance account="221" debit="100.00" credit="0" counterparty_guid="…"/></Balances>
          <ControlBalances date="2026-01-01"><Balance account="221" debit="100.00" credit="0"/></ControlBalances>
        </Export>

    `ControlBalances` = balanța din 1C la o dată, pentru reconciliere (F7.4)."""
    root = parse_xml(text)
    if root.tag != "Export":
        raise ImportFormatError("Rădăcina documentului trebuie să fie <Export>")
    out = ParsedExport()
    seen: set[str] = set()
    for a in root.findall("Accounts/Account"):
        code = (a.get("code") or "").strip()
        if not code or len(code) > 10:
            raise ImportFormatError(f"Cont cu cod invalid „{code}” (1–10 caractere)")
        if code in seen:
            raise ImportFormatError(f"Contul {code} apare de două ori")
        seen.add(code)
        try:
            kind = AccountKind(a.get("kind") or "active_passive")
        except ValueError:
            raise ImportFormatError(f"Contul {code}: tip necunoscut „{a.get('kind')}”") from None
        out.accounts.append(AccountRow(code, a.get("name") or code, kind, (a.get("currency") or "") == "true"))
    for i, c in enumerate(root.findall("Counterparties/Counterparty"), start=1):
        where = f"Contrapartida {i}"
        name = (c.get("name") or "").strip()
        if not name:
            raise ImportFormatError(f"{where}: lipsește denumirea")
        idno = (c.get("idno") or "").strip() or None
        if idno and len(idno) > 13:
            raise ImportFormatError(f"{where}: IDNO mai lung de 13 caractere")
        out.counterparties.append(
            CounterpartyRow(_guid(c.get("guid"), where), name, idno, c.get("vat_code") or None, c.get("address") or None)
        )
    if (node := root.find("Balances")) is not None:
        out.balance_date = _date(node.get("date"), "Balances")
        out.balances = _balances(node, "Balances")
    if (node := root.find("ControlBalances")) is not None:
        out.control_date = _date(node.get("date"), "ControlBalances")
        out.control = _balances(node, "ControlBalances")
    return out


def _mapped(db: Session, organization_id: uuid.UUID, onec_type: str, guid: uuid.UUID) -> OnecIdMap | None:
    return db.scalar(
        select(OnecIdMap).where(
            OnecIdMap.organization_id == organization_id, OnecIdMap.onec_type == onec_type, OnecIdMap.onec_guid == guid
        )
    )


def _import_accounts(db: Session, org_id: uuid.UUID, rows: list[AccountRow]) -> dict:
    existing = {a.code: a for a in db.scalars(select(Account).where(Account.organization_id == org_id))}
    created = 0
    for r in rows:
        if r.code not in existing:
            acc = Account(organization_id=org_id, code=r.code, name=r.name, account_kind=r.kind, is_currency=r.is_currency)
            db.add(acc)
            existing[r.code] = acc
            created += 1
    db.flush()
    return {"created": created, "existing": len(rows) - created}


def _import_counterparties(db: Session, org_id: uuid.UUID, run: OnecImportRun, rows: list[CounterpartyRow]) -> dict:
    created = updated = 0
    for r in rows:
        link = _mapped(db, org_id, CATALOG_COUNTERPARTY, r.guid)
        cp = db.get(Counterparty, link.local_id) if link else None
        if cp is not None and cp.organization_id != org_id:
            cp = None
        if cp is None and r.idno:
            cp = db.scalar(select(Counterparty).where(Counterparty.organization_id == org_id, Counterparty.idno == r.idno))
        if cp is None:
            cp = Counterparty(organization_id=org_id, name=r.name, idno=r.idno, vat_code=r.vat_code, address=r.address)
            db.add(cp)
            created += 1
        else:
            cp.name, cp.vat_code, cp.address = r.name, r.vat_code or cp.vat_code, r.address or cp.address
            updated += 1
        db.flush()
        if cp.onec_guid is None:
            cp.onec_guid = r.guid
        if link is None:
            db.add(OnecIdMap(organization_id=org_id, onec_type=CATALOG_COUNTERPARTY, onec_guid=r.guid,
                             local_table="counterparties", local_id=cp.id, import_run_id=run.id))  # fmt: skip
        else:
            link.local_id, link.import_run_id = cp.id, run.id
    db.flush()
    return {"created": created, "updated": updated}


def _accounts_by_code(db: Session, org_id: uuid.UUID) -> dict[str, Account]:
    return {a.code: a for a in db.scalars(select(Account).where(Account.organization_id == org_id))}


def _offset_account(db: Session, org_id: uuid.UUID, accounts: dict[str, Account]) -> Account:
    acc = accounts.get(OFFSET_ACCOUNT_CODE)
    if acc is None:
        acc = Account(organization_id=org_id, code=OFFSET_ACCOUNT_CODE, name="Solduri inițiale (cont tehnic)",
                      account_kind=AccountKind.active_passive)  # fmt: skip
        db.add(acc)
        db.flush()
        accounts[OFFSET_ACCOUNT_CODE] = acc
    return acc


def _import_balances(
    db: Session, org_id: uuid.UUID, run: OnecImportRun, user_id: uuid.UUID, parsed: ParsedExport
) -> dict:
    """Soldurile inițiale: păstrate în `opening_balances` și înregistrate prin motor ca un document
    „SOLD-INITIAL” (Dt cont / Kt 000 pentru sold debitor, invers pentru creditor). Repetarea înlocuiește."""
    on = parsed.balance_date
    assert on is not None
    accounts = _accounts_by_code(db, org_id)
    unknown = sorted({b.account_code for b in parsed.balances} - set(accounts))
    if unknown:
        raise ImportFormatError(f"Conturi necunoscute în solduri: {', '.join(unknown)} (adăugați-le în <Accounts>)")
    if OFFSET_ACCOUNT_CODE in {b.account_code for b in parsed.balances}:
        raise ImportFormatError(f"Contul {OFFSET_ACCOUNT_CODE} este rezervat soldurilor inițiale")
    offset = _offset_account(db, org_id, accounts)

    cp_ids: dict[uuid.UUID, uuid.UUID] = {}
    for b in parsed.balances:
        if b.counterparty_guid and b.counterparty_guid not in cp_ids:
            link = _mapped(db, org_id, CATALOG_COUNTERPARTY, b.counterparty_guid)
            if link is None:
                raise ImportFormatError(f"Contrapartida {b.counterparty_guid} din solduri nu e în <Counterparties>")
            cp_ids[b.counterparty_guid] = link.local_id

    db.execute(
        delete(OpeningBalance).where(
            OpeningBalance.organization_id == org_id, OpeningBalance.balance_date == on, OpeningBalance.imported_from_1c
        )
    )
    lines: list[LineInput] = []
    for b in parsed.balances:
        subconto = {"counterparty_id": str(cp_ids[b.counterparty_guid])} if b.counterparty_guid else None
        db.add(OpeningBalance(organization_id=org_id, account_id=accounts[b.account_code].id, balance_date=on,
                              debit=b.debit, credit=b.credit, subconto=subconto, imported_from_1c=True))  # fmt: skip
        net = b.debit - b.credit
        if net == 0:
            continue
        analytics = [AnalyticsInput("D" if net > 0 else "K", SubcontoType.counterparty, cp_ids[b.counterparty_guid])] \
            if b.counterparty_guid else []  # fmt: skip
        acc = accounts[b.account_code].id
        lines.append(
            LineInput(debit_account_id=acc if net > 0 else offset.id, credit_account_id=offset.id if net > 0 else acc,
                      amount=abs(net), entry_date=on, description="Sold inițial din 1C", analytics=analytics)  # fmt: skip
        )
    db.flush()

    doc = db.scalar(
        select(Document).where(
            Document.organization_id == org_id,
            Document.type == DocumentType.other,
            Document.doc_number == OPENING_DOC_NUMBER,
            Document.doc_date == on,
        )
    )
    if doc is None:
        doc = Document(organization_id=org_id, type=DocumentType.other, doc_number=OPENING_DOC_NUMBER, doc_date=on,
                       uploaded_by=user_id)  # fmt: skip
        db.add(doc)
        db.flush()
    doc.total_amount = sum((x.amount for x in lines), Decimal(0))
    if lines:
        post_document(db, organization_id=org_id, document_id=doc.id, lines=lines, user_id=user_id,
                      rule_refs=["import 1C: solduri inițiale"])  # fmt: skip
    return {"rows": len(parsed.balances), "posted_lines": len(lines), "document_id": str(doc.id)}


def app_balances(db: Session, org_id: uuid.UUID, as_of: date) -> dict[str, Decimal]:
    """Soldul net (Dt − Kt) pe cod de cont din înregistrări, până la `as_of` inclusiv; fără contul tehnic."""
    sign = {}
    out: dict[str, Decimal] = {}
    for side, column in (("D", EntryLine.debit_account_id), ("K", EntryLine.credit_account_id)):
        sign[side] = 1 if side == "D" else -1
        rows = db.execute(
            select(Account.code, func.sum(EntryLine.amount))
            .join(Account, Account.id == column)
            .where(EntryLine.organization_id == org_id, EntryLine.entry_date <= as_of)
            .group_by(Account.code)
        ).all()
        for code, total in rows:
            out[code] = out.get(code, Decimal(0)) + sign[side] * total
    out.pop(OFFSET_ACCOUNT_CODE, None)
    return out


def reconcile(db: Session, org_id: uuid.UUID, as_of: date, rows: list[BalanceRow]) -> dict:
    """Balanța din 1C (rânduri Dt/Kt pe cont) vs. balanța din aplicație la aceeași dată, pe fiecare cont (F7.4)."""
    expected: dict[str, Decimal] = {}
    for r in rows:
        expected[r.account_code] = expected.get(r.account_code, Decimal(0)) + r.debit - r.credit
    actual = app_balances(db, org_id, as_of)
    diffs, matched = [], 0
    for code in sorted(set(expected) | {c for c, v in actual.items() if v != 0}):
        e, a = expected.get(code, Decimal(0)), actual.get(code, Decimal(0))
        if e == a:
            matched += 1
        else:
            diffs.append({"account_code": code, "onec": str(e), "app": str(a), "difference": str(a - e)})
    return {"date": as_of.isoformat(), "accounts": matched + len(diffs), "matched": matched,
            "differences": diffs, "ok": not diffs}  # fmt: skip


def run_import(
    db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, text: str,
    period_from: date | None = None, period_to: date | None = None,
) -> OnecImportRun:  # fmt: skip
    """O rulare de import: totul sau nimic (la eroare ruta face rollback și notează rularea eșuată)."""
    parsed = parse_export(text)
    run = OnecImportRun(organization_id=organization_id, source="xml", period_from=period_from, period_to=period_to,
                        status=ImportStatus.running, started_by=user_id, started_at=datetime.now())  # fmt: skip
    db.add(run)
    db.flush()
    stats: dict = {"accounts": _import_accounts(db, organization_id, parsed.accounts)}
    stats["counterparties"] = _import_counterparties(db, organization_id, run, parsed.counterparties)
    if parsed.balance_date is not None:
        stats["opening_balances"] = _import_balances(db, organization_id, run, user_id, parsed)
    run.stats = stats
    if parsed.control_date is not None:
        run.reconciliation = reconcile(db, organization_id, parsed.control_date, parsed.control)
    run.status = ImportStatus.done
    run.finished_at = datetime.now()
    write_audit(db, action="import_1c", entity="onec_import_runs", entity_id=run.id, organization_id=organization_id,
                user_id=user_id, new_values=stats)  # fmt: skip
    db.flush()
    return run


__all__ = ["ImportFormatError", "PostingError", "parse_export", "reconcile", "run_import"]
