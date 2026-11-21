"""e-Factura: import XML → factură primită, export XML, statut, izolare, roluri."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.auth.models import OrganizationMember
from app.catalogs.models import Counterparty
from app.core.enums import UserRole
from app.documents.models import Document, Invoice
from app.efactura.service import EfacturaError, parse_invoice
from tests.conftest import auth_headers, make_org, make_user

XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>AB-123</cbc:ID>
  <cbc:UUID>EF-0001</cbc:UUID>
  <cbc:IssueDate>2026-03-15</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>MDL</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyLegalEntity><cbc:RegistrationName>Furnizor SRL</cbc:RegistrationName><cbc:CompanyID>1003600000001</cbc:CompanyID></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="buc">2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>200.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Hârtie A4</cbc:Name><cac:ClassifiedTaxCategory><cbc:Percent>20</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID><cbc:LineExtensionAmount>50.50</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Transport</cbc:Name></cac:Item>
  </cac:InvoiceLine>
</Invoice>"""


@pytest.fixture
def org(db):
    user = make_user(db, "ef@exemplu.md")
    return user, make_org(db, user, "AO Factura")


def test_parse_si_erori():
    p = parse_invoice(XML)
    assert (p.number, p.efactura_id, len(p.lines)) == ("AB-123", "EF-0001", 2)
    assert p.lines[0].vat_rate == Decimal("20") and p.lines[0].unit == "buc"
    for bad in ("<Invoice/>", XML.replace("<cbc:IssueDate>2026-03-15</cbc:IssueDate>", ""),
                XML.replace("200.00", "0"), "<!DOCTYPE a [<!ENTITY b 'c'>]>" + XML):  # fmt: skip
        with pytest.raises(EfacturaError):
            parse_invoice(bad)


def test_import_creeaza_factura_primita_si_nu_dubleaza(client, db, org):
    user, o = org
    h = auth_headers(user)
    r = client.post(f"/organizations/{o.id}/efactura/import", json={"xml": XML}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "received"
    inv = client.get(f"/organizations/{o.id}/invoices/{r.json()['document_id']}", headers=h).json()
    assert inv["doc_number"] == "AB-123" and Decimal(inv["total_amount"]) == Decimal("250.50")
    assert inv["counterparty_name"] == "Furnizor SRL" and len(inv["lines"]) == 2
    assert client.post(f"/organizations/{o.id}/efactura/import", json={"xml": XML}, headers=h).status_code == 422
    assert db.scalar(select(func.count()).select_from(Counterparty).where(Counterparty.organization_id == o.id)) == 1
    assert db.scalar(select(Invoice.e_invoice_id).join(Document).where(Document.organization_id == o.id)) == "EF-0001"


def test_factura_primita_din_efactura_nu_se_reexporta(client, db, org):
    user, o = org
    h = auth_headers(user)
    imported = client.post(f"/organizations/{o.id}/efactura/import", json={"xml": XML}, headers=h).json()
    r = client.post(f"/organizations/{o.id}/efactura/invoices/{imported['document_id']}/export", headers=h)
    assert r.status_code == 422


def test_export_factura_din_aplicatie(client, db, org):
    user, o = org
    h = auth_headers(user)
    cp = Counterparty(organization_id=o.id, name="Client SRL", idno="1002600000009")
    db.add(cp)
    db.flush()
    body = {"doc_number": "F-7", "doc_date": "2026-04-01", "counterparty_id": str(cp.id),
            "lines": [{"description": "Servicii", "amount": "300.00", "vat_rate": "20"}]}  # fmt: skip
    doc_id = client.post(f"/organizations/{o.id}/invoices", json=body, headers=h).json()["document_id"]
    r = client.post(f"/organizations/{o.id}/efactura/invoices/{doc_id}/export", headers=h)
    assert r.status_code == 201 and r.json()["status"] == "draft" and r.json()["direction"] == "sent"
    mid = r.json()["id"]
    xml = client.get(f"/organizations/{o.id}/efactura/messages/{mid}/xml", headers=h).text
    assert "Client SRL" in xml and o.idno in xml and "<cbc:PayableAmount>360.00</cbc:PayableAmount>" in xml
    assert parse_invoice(xml).number == "F-7"  # ciclu complet: exportul se poate reimporta
    r = client.put(f"/organizations/{o.id}/efactura/messages/{mid}/status", json={"status": "sent"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "sent"
    assert client.put(f"/organizations/{o.id}/efactura/messages/{mid}/status", json={"status": "?"}, headers=h).status_code == 422
    put = lambda st: client.put(f"/organizations/{o.id}/efactura/messages/{mid}/status", json={"status": st}, headers=h)  # noqa: E731
    assert put("draft").status_code == 422  # înapoi nu se poate
    assert put("accepted").status_code == 200
    assert put("rejected").status_code == 422  # acceptata e finală
    assert client.post(f"/organizations/{o.id}/efactura/invoices/{doc_id}/export", headers=h).status_code == 422


def test_izolare_si_roluri(client, db, org):
    user, o = org
    h = auth_headers(user)
    msg = client.post(f"/organizations/{o.id}/efactura/import", json={"xml": XML}, headers=h).json()
    other = make_user(db, "alt-ef@exemplu.md")
    other_org = make_org(db, other, "AO Alta")
    ho = auth_headers(other)
    assert client.get(f"/organizations/{o.id}/efactura/messages", headers=ho).status_code == 404
    assert client.get(f"/organizations/{other_org.id}/efactura/messages/{msg['id']}/xml", headers=ho).status_code == 404
    assert client.post(f"/organizations/{other_org.id}/efactura/invoices/{msg['document_id']}/export",
                       headers=ho).status_code == 422  # factura altei organizații nu se exportă  # fmt: skip
    auditor = make_user(db, "audit-ef@exemplu.md")
    db.add(OrganizationMember(organization_id=o.id, user_id=auditor.id, role=UserRole.auditor))
    db.flush()
    ha = auth_headers(auditor)
    assert client.get(f"/organizations/{o.id}/efactura/messages", headers=ha).status_code == 200
    assert client.post(f"/organizations/{o.id}/efactura/import", json={"xml": XML}, headers=ha).status_code == 403
