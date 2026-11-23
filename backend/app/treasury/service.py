"""Transformarea documentelor de trezorerie în rânduri Dt/Kt.

Operațiunile standard folosesc regulile din `posting_rules` (cele existente sau cele din fix7_0001);
operațiunile „alt cont” scriu direct contul ales de contabil. Partea de bancă / casă se fixează
explicit (contul contabil al contului bancar, respectiv 241)."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bank.models import BankAccount
from app.catalogs.models import Account
from app.core.enums import LineKind, SubcontoType
from app.documents.models import Document, Invoice, InvoiceLine
from app.documents.posting import _mdl, invoice_operations
from app.posting.engine import AnalyticsInput, LineInput, PostingError, post_document, unpost_document
from app.posting.models import EntryLine
from app.posting.rules import OperationInput, build_lines
from app.treasury.models import TreasuryDoc

KINDS = {
    "bank_receipt": "Încasare pe cont",
    "bank_payment": "Plată din cont",
    "cash_receipt": "Încasare în numerar",
    "cash_payment": "Plată în numerar",
    "advance_report": "Decont de avans",
    "service_act": "Act de servicii primite",
}
PREFIX = {"bank_receipt": "ÎC", "bank_payment": "PC", "cash_receipt": "ÎN", "cash_payment": "PN",
          "advance_report": "DA", "service_act": "AS"}
LINE_KINDS = {"service", "material", "goods", "low_value_item"}
CASH_CODE = "241"


@dataclass(frozen=True)
class OpDef:
    label: str
    rule: tuple[str, str] | None = None  # (document_type, operation) din posting_rules
    bank: str | None = None  # "D"/"K": partea pe care stă contul bancar al organizației
    cash: str | None = None  # "D"/"K": partea pe care stă casa (241)
    needs: tuple[str, ...] = ()  # câmpuri obligatorii: bank, counterparty, person, grant, account
    analytics: tuple[str, str] | None = None  # (partea, counterparty|person)
    explicit: str | None = None  # "D"/"K": partea pe care o ocupă contul ales (operațiuni fără regulă)
    optional: tuple[str, ...] = ()  # câmpuri opționale afișate


OPS: dict[str, dict[str, OpDef]] = {
    "bank_receipt": {
        "tranche": OpDef("Tranșă de grant", ("grant_income", "tranche_received"), "D", needs=("bank", "grant")),
        "membership": OpDef("Cotizații de membru", ("membership_fee", "receipt"), "D", needs=("bank",)),
        "supplier_refund": OpDef("Restituire de la furnizor", ("bank_receipt", "supplier_refund"), "D",
                                 needs=("bank", "counterparty"), analytics=("K", "counterparty")),
        "cash_deposit": OpDef("Depunere numerar în cont", ("bank_receipt", "cash_deposit"), "D", needs=("bank",)),
        "other": OpDef("Alt cont (se alege contul creditor)", None, "D", needs=("bank", "account"), explicit="K",
                       optional=("counterparty", "grant")),
    },
    "bank_payment": {
        "supplier": OpDef("Plată către furnizor", ("payment_order", "supplier_payment"), "K",
                          needs=("bank", "counterparty"), analytics=("D", "counterparty")),
        "cash_withdrawal": OpDef("Ridicare numerar din cont", ("bank_payment", "cash_withdrawal"), "K", needs=("bank",)),
        "salary": OpDef("Salarii", ("bank_payment", "salary"), "K", needs=("bank",), analytics=("D", "person"),
                        optional=("person", "grant")),
        "social": OpDef("Contribuții sociale / medicale", ("bank_payment", "social"), "K", needs=("bank",),
                        optional=("grant",)),
        "budget": OpDef("Plăți către buget", ("bank_payment", "budget"), "K", needs=("bank",), optional=("grant",)),
        "grant_refund": OpDef("Restituire grant către donator", ("payment_order", "grant_refund"), "K",
                              needs=("bank", "grant")),
        "other": OpDef("Alt cont (se alege contul debitor)", None, "K", needs=("bank", "account"), explicit="D",
                       optional=("counterparty", "grant")),
    },
    "cash_receipt": {
        "from_bank": OpDef("Ridicare numerar din cont", ("bank_payment", "cash_withdrawal"), "K", needs=("bank",)),
        "membership": OpDef("Cotizații de membru", ("membership_fee", "receipt"), cash="D"),
        "advance_return": OpDef("Restituire avans de la persoană", None, cash="D", needs=("person", "account"),
                                analytics=("K", "person"), explicit="K"),
        "other": OpDef("Alt cont (se alege contul creditor)", None, cash="D", needs=("account",), explicit="K",
                       optional=("counterparty", "grant")),
    },
    "cash_payment": {
        "supplier": OpDef("Plată către furnizor", ("payment_order", "supplier_payment"), cash="K",
                          needs=("counterparty",), analytics=("D", "counterparty")),
        "salary": OpDef("Salarii", ("bank_payment", "salary"), cash="K", analytics=("D", "person"),
                        optional=("person", "grant")),
        "to_bank": OpDef("Depunere numerar în cont", ("bank_receipt", "cash_deposit"), "D", needs=("bank",)),
        "advance_issue": OpDef("Avans către persoană", None, cash="K", needs=("person", "account"),
                               analytics=("D", "person"), explicit="D"),
        "other": OpDef("Alt cont (se alege contul debitor)", None, cash="K", needs=("account",), explicit="D",
                       optional=("counterparty", "grant")),
    },
}
CASH_KINDS = {"cash_receipt", "cash_payment"}
LINE_DOCS = {"advance_report", "service_act"}
DOC_TYPE = {"advance_report": "receipt", "service_act": "act"}

NEED_LABELS = {"bank": "contul bancar", "counterparty": "contrapartida", "person": "persoana", "grant": "grantul",
               "account": "contul contabil"}


@dataclass
class Row:
    line: LineInput
    ref: str
    source_ref: str


@dataclass
class _Ctx:
    db: Session
    org: uuid.UUID
    doc: Document
    td: TreasuryDoc
    _cash: uuid.UUID | None = field(default=None, repr=False)

    def account_by_code(self, code: str) -> uuid.UUID:
        acc = self.db.scalar(select(Account.id).where(Account.organization_id == self.org, Account.code == code))
        if acc is None:
            raise PostingError(f"Contul {code} lipsește din planul de conturi al organizației")
        return acc


def cash_balance(db: Session, org: uuid.UUID, on_date, exclude_document: uuid.UUID | None = None) -> Decimal:
    code_id = db.scalar(select(Account.id).where(Account.organization_id == org, Account.code == CASH_CODE))
    if code_id is None:
        return Decimal(0)
    q = select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
        EntryLine.organization_id == org, EntryLine.entry_date <= on_date
    )
    if exclude_document:
        q = q.where(EntryLine.document_id != exclude_document)
    debit = db.scalar(q.where(EntryLine.debit_account_id == code_id))
    credit = db.scalar(q.where(EntryLine.credit_account_id == code_id))
    return Decimal(debit) - Decimal(credit)


def person_balance(db: Session, org: uuid.UUID, person_id: uuid.UUID, account_id: uuid.UUID, on_date) -> Decimal:
    """Soldul debitor al persoanei pe contul de avans (cât a primit și nu a justificat)."""
    from app.posting.models import EntryLineAnalytics

    def total(account_col, side):
        return Decimal(
            db.scalar(
                select(func.coalesce(func.sum(EntryLine.amount), 0))
                .join(EntryLineAnalytics, (EntryLineAnalytics.entry_line_id == EntryLine.id)
                      & (EntryLineAnalytics.entry_date == EntryLine.entry_date))
                .where(EntryLine.organization_id == org, EntryLine.entry_date <= on_date, account_col == account_id,
                       EntryLineAnalytics.side == side, EntryLineAnalytics.subconto_type == SubcontoType.person,
                       EntryLineAnalytics.ref_id == person_id)
            )
        )

    return total(EntryLine.debit_account_id, "D") - total(EntryLine.credit_account_id, "K")


def _analytics(opdef: OpDef, doc: Document, td: TreasuryDoc) -> list[AnalyticsInput]:
    if opdef.analytics is None:
        return []
    side, what = opdef.analytics
    if what == "counterparty" and doc.counterparty_id:
        return [AnalyticsInput(side=side, subconto_type=SubcontoType.counterparty, ref_id=doc.counterparty_id)]
    if what == "person" and td.person_id:
        return [AnalyticsInput(side=side, subconto_type=SubcontoType.person, ref_id=td.person_id)]
    return []


def _money_rows(c: _Ctx) -> list[Row]:
    doc, td = c.doc, c.td
    opdef = OPS[td.kind].get(td.operation or "")
    if opdef is None:
        raise PostingError("Alegeți operațiunea documentului")
    if doc.total_amount is None or doc.total_amount <= 0:
        raise PostingError("Suma documentului trebuie să fie pozitivă")
    if doc.doc_date is None:
        raise PostingError("Documentul nu are dată")
    bank = None
    if td.bank_account_id:
        bank = c.db.get(BankAccount, td.bank_account_id)
        if bank is None or bank.organization_id != c.org:
            raise PostingError("Contul bancar nu aparține organizației")
    if "bank" in opdef.needs and (bank is None or bank.account_id is None):
        raise PostingError("Alegeți contul bancar (legat de un cont contabil)")
    currency = doc.currency if bank is not None and opdef.bank else None
    if td.kind in CASH_KINDS and doc.currency not in (None, "MDL") and "bank" not in opdef.needs:
        raise PostingError("Casa se ține în MDL")
    amount, currency_amount = _mdl(doc.total_amount, currency, td.exchange_rate)
    grant_id = td.grant_id or (bank.grant_id if bank else None)
    debit_id = credit_id = None
    if opdef.bank and bank is not None:
        if opdef.bank == "D":
            debit_id = bank.account_id
        else:
            credit_id = bank.account_id
    if opdef.cash:
        cash = c.account_by_code(CASH_CODE)
        if opdef.cash == "D":
            debit_id = cash
        else:
            credit_id = cash
    analytics = _analytics(opdef, doc, td)
    description = td.purpose
    fx = dict(currency=currency if currency_amount is not None else None, currency_amount=currency_amount)
    if opdef.rule:
        op = OperationInput(operation=opdef.rule[1], amount=amount, grant_id=grant_id, description=description,
                            analytics=analytics, debit_account_id=debit_id, credit_account_id=credit_id, **fx)
        generated = build_lines(c.db, organization_id=c.org, document_type=opdef.rule[0], doc_date=doc.doc_date,
                                operations=[op])
        return [Row(g.line, f"{g.rule.id} ({g.rule.source_ref})", g.rule.source_ref) for g in generated]
    if td.account_id is None:
        raise PostingError("Alegeți contul contabil al contrapartidei")
    other = c.db.get(Account, td.account_id)
    if other is None or other.organization_id != c.org:
        raise PostingError("Contul contabil nu aparține organizației")
    if opdef.explicit == "D":
        debit_id = td.account_id
    else:
        credit_id = td.account_id
    if not analytics and doc.counterparty_id and "counterparty" in opdef.optional:
        analytics = [AnalyticsInput(side=opdef.explicit or "D", subconto_type=SubcontoType.counterparty,
                                    ref_id=doc.counterparty_id)]
    line = LineInput(debit_account_id=debit_id, credit_account_id=credit_id, amount=amount, entry_date=doc.doc_date,
                     grant_id=grant_id, description=description, analytics=analytics, **fx)
    return [Row(line, "operațiune cu cont ales de contabil", "Cont ales de contabil")]


def _line_doc_rows(c: _Ctx) -> list[Row]:
    doc, td = c.doc, c.td
    if not td.lines:
        raise PostingError("Documentul nu are rânduri")
    if doc.doc_date is None:
        raise PostingError("Documentul nu are dată")
    invoice = Invoice(
        lines=[
            InvoiceLine(description=ln.description, amount=ln.amount, quantity=ln.quantity,
                        line_kind=LineKind(ln.line_kind), account_id=ln.account_id,
                        budget_line_id=ln.budget_line_id, cost_item_id=ln.cost_item_id, put_into_use=True)
            for ln in td.lines
        ]
    )
    ops = invoice_operations(c.db, c.org, doc, invoice)
    if td.kind == "advance_report":
        if td.account_id is None or td.person_id is None:
            raise PostingError("Decontul cere persoana și contul de avans")
        for op in ops:
            if op.operation in ("expense", "stock_receipt"):
                op.credit_account_id = td.account_id
                op.analytics = [AnalyticsInput(side="K", subconto_type=SubcontoType.person, ref_id=td.person_id)]
    generated = build_lines(c.db, organization_id=c.org, document_type="invoice", doc_date=doc.doc_date, operations=ops)
    return [Row(g.line, f"{g.rule.id} ({g.rule.source_ref})", g.rule.source_ref) for g in generated]


def build_rows(db: Session, org: uuid.UUID, doc: Document, td: TreasuryDoc) -> list[Row]:
    c = _Ctx(db, org, doc, td)
    rows = _line_doc_rows(c) if td.kind in LINE_DOCS else _money_rows(c)
    if td.kind in CASH_KINDS:
        cash_id = c.account_by_code(CASH_CODE)
        spent = sum((r.line.amount for r in rows if r.line.credit_account_id == cash_id), Decimal(0))
        if spent and cash_balance(db, org, doc.doc_date, exclude_document=doc.id) < spent:
            raise PostingError("Soldul casei este insuficient pentru această plată")
    return rows


def post_treasury(db: Session, org: uuid.UUID, doc: Document, td: TreasuryDoc, user_id: uuid.UUID | None):
    rows = build_rows(db, org, doc, td)
    return post_document(db, organization_id=org, document_id=doc.id, lines=[r.line for r in rows], user_id=user_id,
                         rule_refs=[r.ref for r in rows])


__all__ = ["KINDS", "OPS", "build_rows", "post_treasury", "unpost_document", "person_balance", "cash_balance"]
