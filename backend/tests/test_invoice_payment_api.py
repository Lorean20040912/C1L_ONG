from datetime import date
from decimal import Decimal

import pytest

from app.bank.models import BankAccount
from app.catalogs.models import Counterparty
from app.grants.models import BudgetLine, Grant
from app.posting.models import AccountingPolicy
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "123", "124", "211", "234.4", "242", "3411", "521", "537", "616", "716")
    db.add(
        AccountingPolicy(
            organization_id=org.id, valid_from=date(2026, 1, 1), grant_receivable_account_id=acc["234.4"].id
        )
    )
    grant = Grant(
        organization_id=org.id,
        code="SOR",
        title="Proiect",
        funding_type="grant",
        currency="MDL",
        total_amount=Decimal(100000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    db.add(grant)
    db.flush()
    line = BudgetLine(grant_id=grant.id, code="3.2", name="Comunicații", planned_amount=Decimal(5000))
    supplier = Counterparty(organization_id=org.id, name="„Moldtelecom” SA", idno="1002600000002")
    bank = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000225", currency="MDL", account_id=acc["242"].id)
    db.add_all([line, supplier, bank])
    db.flush()
    return user, org, grant, line, supplier, bank


def invoice_body(supplier, line, amount="612.40"):
    return {
        "doc_number": "EF2026117",
        "doc_date": "2026-11-05",
        "counterparty_id": str(supplier.id),
        "lines": [
            {
                "description": "Internet noiembrie",
                "amount": amount,
                "line_kind": "service",
                "budget_line_id": str(line.id),
            }
        ],
    }


def test_ciclul_facturii(client, ong):
    user, org, _, line, supplier, _ = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}/invoices"
    r = client.post(base, json=invoice_body(supplier, line), headers=h)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["total_amount"] == "612.40" and inv["counterparty_name"] == "„Moldtelecom” SA"
    doc_id = inv["document_id"]

    preview = client.post(f"{base}/{doc_id}/preview", headers=h).json()
    assert [(p["debit_account"], p["credit_account"]) for p in preview] == [("716", "521"), ("537", "616")]

    # modificarea cu versiunea corectă
    body = {**invoice_body(supplier, line, "700.00"), "version": inv["version"]}
    r = client.put(f"{base}/{doc_id}", json=body, headers=h)
    assert r.status_code == 200 and r.json()["total_amount"] == "700.00"
    # versiunea veche → conflict (alt utilizator a salvat între timp)
    assert client.put(f"{base}/{doc_id}", json={**body, "version": inv["version"]}, headers=h).status_code == 409

    assert client.post(f"{base}/{doc_id}/post", headers=h).status_code == 200
    listed = client.get(base, headers=h).json()
    assert listed[0]["is_posted"] is True
    # înregistrată → nu se modifică până la anulare
    assert client.put(f"{base}/{doc_id}", json=invoice_body(supplier, line), headers=h).status_code == 409
    # ruta generică trimite la ruta facturii
    r = client.post(f"/organizations/{org.id}/documents/{doc_id}/unpost", headers=h)
    assert r.status_code == 409 and "/invoices/" in r.json()["detail"]
    assert client.post(f"{base}/{doc_id}/unpost", headers=h).status_code == 204
    assert client.put(f"{base}/{doc_id}", json=invoice_body(supplier, line), headers=h).status_code == 200


def test_factura_cu_date_straine_e_respinsa(client, db, ong):
    user, org, _, line, supplier, _ = ong
    intrus = make_user(db, "intrus@exemplu.md")
    other = make_org(db, intrus, "AO Beta")
    foreign_supplier = Counterparty(organization_id=other.id, name="Străin")
    db.add(foreign_supplier)
    db.flush()
    r = client.post(
        f"/organizations/{org.id}/invoices", json=invoice_body(foreign_supplier, line), headers=auth_headers(user)
    )
    assert r.status_code == 422
    # utilizatorul altei organizații nu vede factura
    doc_id = client.post(
        f"/organizations/{org.id}/invoices", json=invoice_body(supplier, line), headers=auth_headers(user)
    ).json()["document_id"]
    assert client.get(f"/organizations/{org.id}/invoices/{doc_id}", headers=auth_headers(intrus)).status_code == 404
    assert client.get(f"/organizations/{other.id}/invoices/{doc_id}", headers=auth_headers(intrus)).status_code == 404


def test_eroarea_de_inregistrare_e_clara(client, ong):
    user, org, _, _, supplier, _ = ong
    body = {
        "doc_number": "1",
        "doc_date": "2026-11-05",
        "counterparty_id": str(supplier.id),
        "lines": [{"description": "Taxi", "amount": "350", "line_kind": "service"}],
    }
    doc_id = client.post(f"/organizations/{org.id}/invoices", json=body, headers=auth_headers(user)).json()[
        "document_id"
    ]
    r = client.post(f"/organizations/{org.id}/invoices/{doc_id}/post", headers=auth_headers(user))
    assert r.status_code == 422 and "linia de buget" in r.json()["detail"]


def test_plata_facturii(client, ong):
    user, org, _, line, supplier, bank = ong
    h = auth_headers(user)
    invoice_id = client.post(f"/organizations/{org.id}/invoices", json=invoice_body(supplier, line), headers=h).json()[
        "document_id"
    ]
    body = {
        "doc_number": "15",
        "doc_date": "2026-11-10",
        "amount": "612.40",
        "purpose": "Plata facturii EF2026117",
        "bank_account_id": str(bank.id),
        "counterparty_id": str(supplier.id),
        "invoice_document_id": invoice_id,
    }
    r = client.post(f"/organizations/{org.id}/payment-orders", json=body, headers=h)
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["beneficiary_name"] == "„Moldtelecom” SA" and order["currency"] == "MDL"
    assert order["invoice_document_id"] == invoice_id
    base = f"/organizations/{org.id}/payment-orders/{order['document_id']}"
    assert [(p["debit_account"], p["credit_account"]) for p in client.post(f"{base}/preview", headers=h).json()] == [
        ("521", "242")
    ]
    assert client.post(f"{base}/post", headers=h).status_code == 200
    assert client.post(f"{base}/unpost", headers=h).status_code == 204


def test_plata_in_alta_valuta_decat_contul(client, ong):
    user, org, _, _, supplier, bank = ong
    body = {
        "doc_number": "16",
        "doc_date": "2026-11-10",
        "amount": "10",
        "currency": "EUR",
        "bank_account_id": str(bank.id),
        "counterparty_id": str(supplier.id),
    }
    r = client.post(f"/organizations/{org.id}/payment-orders", json=body, headers=auth_headers(user))
    assert r.status_code == 422 and "MDL" in r.json()["detail"]


def test_cataloagele_pentru_formulare(client, ong):
    user, org, grant, line, supplier, bank = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}"
    grants = client.get(f"{base}/grants", headers=h).json()
    assert grants[0]["code"] == "SOR" and grants[0]["budget_lines"][0]["code"] == "3.2"
    assert client.get(f"{base}/counterparties", params={"q": "moldtel"}, headers=h).json()[0]["id"] == str(supplier.id)
    r = client.post(f"{base}/counterparties", json={"name": "„Print Expres” SRL", "idno": "1003600000099"}, headers=h)
    assert r.status_code == 201
    assert (
        client.post(f"{base}/counterparties", json={"name": "dublură", "idno": "1003600000099"}, headers=h).status_code
        == 409
    )
    assert client.get(f"{base}/bank-accounts", headers=h).json()[0]["iban"] == "MD00AG0000000225"
