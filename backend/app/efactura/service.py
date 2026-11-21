"""e-Factura: import / export XML (UBL 2.1, subset) legat de modulul facturi.

Importul creează o *Factură primită* nerezolvată (nu se înregistrează automat) și mesajul e-Factura
asociat; exportul generează XML-ul facturii și mesajul „draft”. Transportul către SFS
(descărcare / trimitere automată, semnare) e un adaptor separat, încă neimplementat."""

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.catalogs.models import Counterparty
from app.core.enums import DocumentType
from app.documents.models import Document, Invoice, InvoiceLine
from app.efactura.models import EfacturaMessage
from app.onec_import.service import ImportFormatError, parse_xml

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
for _p, _u in NS.items():
    ET.register_namespace("" if _p == "inv" else _p, _u)

# tranziții permise ale statutului unui mesaj trimis
TRANSITIONS = {
    "draft": {"sent"},
    "sent": {"signed", "accepted", "rejected"},
    "signed": {"accepted", "rejected"},
    "rejected": {"draft"},
    "accepted": set(),
}
STATUSES = ("draft", "sent", "signed", "accepted", "rejected")
CENT = Decimal("0.01")


class EfacturaError(ValueError):
    """XML-ul / starea nu permit operația; mesajul e pentru utilizator."""


@dataclass
class ParsedLine:
    description: str
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    vat_rate: Decimal | None
    amount: Decimal


@dataclass
class ParsedInvoice:
    efactura_id: str
    number: str
    issue_date: date
    currency: str | None
    supplier_name: str
    supplier_idno: str | None
    supplier_vat: str | None
    lines: list[ParsedLine] = field(default_factory=list)


def _text(node: ET.Element | None, path: str) -> str | None:
    found = node.find(path, NS) if node is not None else None
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _num(value: str | None, where: str, *, required: bool = True) -> Decimal | None:
    if value is None:
        if required:
            raise EfacturaError(f"Lipsește {where}")
        return None
    try:
        out = Decimal(value)
    except InvalidOperation:
        raise EfacturaError(f"{where}: număr invalid „{value}”") from None
    if not out.is_finite():
        raise EfacturaError(f"{where}: număr invalid „{value}”")
    return out


def parse_invoice(text: str) -> ParsedInvoice:
    try:
        root = parse_xml(text)
    except ImportFormatError as exc:
        raise EfacturaError(str(exc)) from None
    if root.tag != f"{{{NS['inv']}}}Invoice":
        raise EfacturaError("Rădăcina trebuie să fie <Invoice> (UBL 2.1)")
    number = _text(root, "cbc:ID")
    issued = _text(root, "cbc:IssueDate")
    if not number or not issued:
        raise EfacturaError("Factura nu are număr (cbc:ID) sau dată (cbc:IssueDate)")
    try:
        issue_date = date.fromisoformat(issued)
    except ValueError:
        raise EfacturaError(f"Data „{issued}” trebuie să fie AAAA-LL-ZZ") from None
    party = root.find("cac:AccountingSupplierParty/cac:Party", NS)
    name = _text(party, "cac:PartyLegalEntity/cbc:RegistrationName") or _text(party, "cac:PartyName/cbc:Name")
    if not name:
        raise EfacturaError("Lipsește furnizorul (cac:AccountingSupplierParty)")
    idno = _text(party, "cac:PartyLegalEntity/cbc:CompanyID")
    if idno and len(idno) > 13:
        raise EfacturaError("IDNO-ul furnizorului depășește 13 caractere")
    parsed = ParsedInvoice(
        efactura_id=_text(root, "cbc:UUID") or f"{idno or name}:{number}",
        number=number,
        issue_date=issue_date,
        currency=_text(root, "cbc:DocumentCurrencyCode"),
        supplier_name=name,
        supplier_idno=idno,
        supplier_vat=_text(party, "cac:PartyTaxScheme/cbc:CompanyID"),
    )
    for i, ln in enumerate(root.findall("cac:InvoiceLine", NS), start=1):
        where = f"Rândul {i}"
        amount = _num(_text(ln, "cbc:LineExtensionAmount"), f"{where}: LineExtensionAmount")
        assert amount is not None
        if amount <= 0:
            raise EfacturaError(f"{where}: suma trebuie să fie pozitivă")
        qty_node = ln.find("cbc:InvoicedQuantity", NS)
        parsed.lines.append(
            ParsedLine(
                description=_text(ln, "cac:Item/cbc:Name") or _text(ln, "cbc:Note") or f"Rândul {i}",
                quantity=_num(qty_node.text.strip() if qty_node is not None and qty_node.text else None,
                              f"{where}: cantitatea", required=False),  # fmt: skip
                unit=qty_node.get("unitCode") if qty_node is not None else None,
                unit_price=_num(_text(ln, "cac:Price/cbc:PriceAmount"), f"{where}: prețul", required=False),
                vat_rate=_num(_text(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"), f"{where}: TVA", required=False),
                amount=amount.quantize(CENT),
            )
        )
    if not parsed.lines:
        raise EfacturaError("Factura nu are rânduri (cac:InvoiceLine)")
    return parsed


def import_invoice(db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, text: str) -> tuple[Document, EfacturaMessage]:
    """Factură primită din e-Factura. Același `efactura_id` nu se importă de două ori."""
    p = parse_invoice(text)
    if db.scalar(select(EfacturaMessage.id).where(EfacturaMessage.organization_id == organization_id,
                                                    EfacturaMessage.efactura_id == p.efactura_id)) is not None:  # fmt: skip
        raise EfacturaError(f"Factura {p.efactura_id} a fost deja importată")
    cp = None
    if p.supplier_idno:
        cp = db.scalar(select(Counterparty).where(Counterparty.organization_id == organization_id,
                                                  Counterparty.idno == p.supplier_idno))  # fmt: skip
    if cp is None:
        cp = Counterparty(organization_id=organization_id, name=p.supplier_name, idno=p.supplier_idno, vat_code=p.supplier_vat)
        db.add(cp)
        db.flush()
    doc = Document(organization_id=organization_id, type=DocumentType.invoice, doc_number=p.number, doc_date=p.issue_date,
                   counterparty_id=cp.id, total_amount=sum((ln.amount for ln in p.lines), Decimal(0)),
                   currency=p.currency, uploaded_by=user_id)  # fmt: skip
    db.add(doc)
    db.flush()
    invoice = Invoice(document_id=doc.id, e_invoice_id=p.efactura_id)
    invoice.lines = [
        InvoiceLine(position=i, description=ln.description, quantity=ln.quantity, unit=ln.unit, unit_price=ln.unit_price,
                    vat_rate=ln.vat_rate, amount=ln.amount)  # fmt: skip
        for i, ln in enumerate(p.lines)
    ]
    db.add(invoice)
    msg = EfacturaMessage(organization_id=organization_id, direction="received", efactura_id=p.efactura_id,
                          status="accepted", payload_xml=text, document_id=doc.id, synced_at=datetime.now())  # fmt: skip
    db.add(msg)
    db.flush()
    write_audit(db, action="import_efactura", entity="documents", entity_id=doc.id, organization_id=organization_id,
                user_id=user_id, new_values={"efactura_id": p.efactura_id})  # fmt: skip
    return doc, msg


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    prefix, name = tag.split(":")
    el = ET.SubElement(parent, f"{{{NS[prefix]}}}{name}", attrs)
    if text is not None:
        el.text = text
    return el


def export_invoice(db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, document_id: uuid.UUID,
                   supplier_name: str, supplier_idno: str | None) -> EfacturaMessage:  # fmt: skip
    """XML UBL al unei facturi din aplicație (furnizor = organizația noastră, client = contrapartida)."""
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.organization_id == organization_id,
                                           Document.type == DocumentType.invoice))  # fmt: skip
    invoice = db.scalar(select(Invoice).where(Invoice.document_id == document_id)) if doc else None
    if doc is None or invoice is None:
        raise EfacturaError("Factura nu a fost găsită")
    if db.scalar(select(EfacturaMessage.id).where(EfacturaMessage.organization_id == organization_id,
                                                  EfacturaMessage.document_id == doc.id,
                                                  EfacturaMessage.direction == "received")) is not None:  # fmt: skip
        raise EfacturaError("Factura a fost primită prin e-Factura; se exportă doar facturile emise de organizație")
    if not invoice.lines or doc.doc_date is None or not doc.doc_number:
        raise EfacturaError("Factura nu are număr, dată sau rânduri")
    customer = db.get(Counterparty, doc.counterparty_id) if doc.counterparty_id else None
    if customer is not None and customer.organization_id != organization_id:
        customer = None
    efactura_id = invoice.e_invoice_id or str(uuid.uuid4())
    root = ET.Element(f"{{{NS['inv']}}}Invoice")
    _sub(root, "cbc:ID", doc.doc_number)
    _sub(root, "cbc:UUID", efactura_id)
    _sub(root, "cbc:IssueDate", doc.doc_date.isoformat())
    _sub(root, "cbc:InvoiceTypeCode", "380")
    _sub(root, "cbc:DocumentCurrencyCode", doc.currency or "MDL")
    for tag, name, idno in (("cac:AccountingSupplierParty", supplier_name, supplier_idno),
                            ("cac:AccountingCustomerParty", customer.name if customer else "", customer.idno if customer else None)):  # fmt: skip
        legal = _sub(_sub(_sub(root, tag), "cac:Party"), "cac:PartyLegalEntity")
        _sub(legal, "cbc:RegistrationName", name)
        if idno:
            _sub(legal, "cbc:CompanyID", idno)
    net = Decimal(0)
    tax = Decimal(0)
    for i, ln in enumerate(invoice.lines, start=1):
        line = _sub(root, "cac:InvoiceLine")
        _sub(line, "cbc:ID", str(i))
        if ln.quantity is not None:
            attrs = {"unitCode": ln.unit} if ln.unit else {}
            _sub(line, "cbc:InvoicedQuantity", str(ln.quantity), **attrs)
        _sub(line, "cbc:LineExtensionAmount", str(ln.amount), currencyID=doc.currency or "MDL")
        item = _sub(line, "cac:Item")
        _sub(item, "cbc:Name", ln.description)
        if ln.vat_rate is not None:
            _sub(_sub(item, "cac:ClassifiedTaxCategory"), "cbc:Percent", str(ln.vat_rate))
            tax += (ln.amount * ln.vat_rate / 100).quantize(CENT)
        if ln.unit_price is not None:
            _sub(_sub(line, "cac:Price"), "cbc:PriceAmount", str(ln.unit_price))
        net += ln.amount
    totals = _sub(root, "cac:LegalMonetaryTotal")
    _sub(totals, "cbc:LineExtensionAmount", str(net))
    _sub(totals, "cbc:PayableAmount", str(net + tax))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

    msg = db.scalar(select(EfacturaMessage).where(EfacturaMessage.organization_id == organization_id,
                                                  EfacturaMessage.efactura_id == efactura_id))  # fmt: skip
    if msg is None:
        msg = EfacturaMessage(organization_id=organization_id, direction="sent", efactura_id=efactura_id, status="draft",
                              document_id=doc.id)  # fmt: skip
        db.add(msg)
    elif msg.direction != "sent" or msg.status not in (None, "draft", "rejected"):
        raise EfacturaError("Factura a fost deja trimisă; XML-ul nu se mai regenerează")
    msg.payload_xml, msg.status = xml, "draft"
    invoice.e_invoice_id = efactura_id
    write_audit(db, action="export_efactura", entity="documents", entity_id=doc.id, organization_id=organization_id,
                user_id=user_id, new_values={"efactura_id": efactura_id})  # fmt: skip
    db.flush()
    return msg
