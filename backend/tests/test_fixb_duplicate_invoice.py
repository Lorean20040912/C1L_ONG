"""Facturile primite: același număr de la același furnizor în același an se refuză (manual, e-Factura, scanuri)."""

import base64

import pytest

from app.catalogs.models import Account, Counterparty
from tests.conftest import auth_headers, make_accounts, make_org, make_user
from tests.test_efactura import XML


@pytest.fixture
def env(db):
    user = make_user(db, "dup@test.md")
    org = make_org(db, user, "AO Dubluri")
    acc = make_accounts(db, org, "628", "521")
    a = Counterparty(organization_id=org.id, name="Furnizor A", idno="1003600000011")
    b = Counterparty(organization_id=org.id, name="Furnizor B", idno="1003600000022")
    db.add_all([a, b])
    db.flush()
    return user, org, acc, a, b, auth_headers(user), f"/organizations/{org.id}"


def body(acc, cp, number="F-100", day="2026-03-10", **kw):
    return {"doc_number": number, "doc_date": day, "counterparty_id": str(cp.id),
            "lines": [{"description": "Servicii", "amount": "100.00", "line_kind": "service", "account_id": str(acc["628"].id)}], **kw}  # fmt: skip


def test_factura_cu_acelasi_numar_furnizor_si_an_se_refuza(client, env):
    user, org, acc, a, b, h, base = env
    url = f"{base}/invoices"
    first = client.post(url, json=body(acc, a), headers=h)
    assert first.status_code == 201, first.text
    dup = client.post(url, json=body(acc, a, number=" f-100 ", day="2026-11-20"), headers=h)  # alte litere/spații, aceeași an
    assert dup.status_code == 409
    msg = dup.json()["detail"]
    assert "F-100" in msg.replace("f-100", "F-100") and "Furnizor A" in msg and "2026" in msg and "nu se admite" in msg
    # alt furnizor, alt an, altă serie: permise
    assert client.post(url, json=body(acc, b), headers=h).status_code == 201
    assert client.post(url, json=body(acc, a, day="2027-01-05"), headers=h).status_code == 201
    assert client.post(url, json=body(acc, a, series="AB"), headers=h).status_code == 201
    assert client.post(url, json=body(acc, a, series="ab"), headers=h).status_code == 409


def test_modificarea_nu_se_blocheaza_pe_ea_insasi_dar_nici_nu_creeaza_dublura(client, env):
    user, org, acc, a, b, h, base = env
    url = f"{base}/invoices"
    one = client.post(url, json=body(acc, a, number="X-1"), headers=h).json()
    two = client.post(url, json=body(acc, a, number="X-2"), headers=h).json()
    ok = client.put(f"{url}/{one['document_id']}", json=body(acc, a, number="X-1", version=one["version"]), headers=h)
    assert ok.status_code == 200, ok.text
    clash = client.put(f"{url}/{two['document_id']}", json=body(acc, a, number="X-1"), headers=h)
    assert clash.status_code == 409 and "X-1" in clash.json()["detail"]


def test_efactura_cu_numar_existent_se_refuza(client, env):
    user, org, acc, a, b, h, base = env
    a.idno = "1003600000001"  # furnizorul din XML
    a.name = "Furnizor SRL"
    client.post(f"{base}/invoices", json=body(acc, a, number="AB-123", day="2026-03-01"), headers=h)
    r = client.post(f"{base}/efactura/import", json={"xml": XML}, headers=h)
    assert r.status_code == 422 and "nu se admite" in r.json()["detail"]


def test_scanul_cu_factura_existenta_nu_se_valideaza(client, env):
    user, org, acc, a, b, h, base = env
    client.post(f"{base}/invoices", json=body(acc, a, number="S-77"), headers=h)
    content = base64.b64encode(b"%PDF-1.4 scan duplicat").decode()
    scan = client.post(f"{base}/scanned-documents", json={"file_name": "s.pdf", "mime_type": "application/pdf", "content_base64": content}, headers=h).json()
    patch = {"type": "invoice", "counterparty_id": str(a.id), "doc_number": "S-77", "doc_date": "2026-05-02", "total_amount": "100.00"}
    r = client.patch(f"{base}/scanned-documents/{scan['id']}", json=patch, headers=h)
    assert r.status_code == 409 and "S-77" in r.json()["detail"]
    ok = client.patch(f"{base}/scanned-documents/{scan['id']}", json={**patch, "doc_number": "S-78"}, headers=h)
    assert ok.status_code == 200
    assert client.post(f"{base}/scanned-documents/{scan['id']}/validate", headers=h).status_code == 200
    # un al doilea scan cu numărul S-78 al aceluiași furnizor nu mai trece
    other = client.post(f"{base}/scanned-documents", json={"file_name": "t.pdf", "mime_type": "application/pdf",
                        "content_base64": base64.b64encode(b"%PDF-1.4 alt scan").decode()}, headers=h).json()  # fmt: skip
    assert client.patch(f"{base}/scanned-documents/{other['id']}", json={**patch, "doc_number": "s-78"}, headers=h).status_code == 409
