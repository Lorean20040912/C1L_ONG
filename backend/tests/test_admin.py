"""Administrare: granturi și linii de buget, politica contabilă, perioade, conturi, utilizatori."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import OrganizationMember
from app.catalogs.models import Counterparty
from app.core.enums import UserRole
from app.posting.models import AccountingPeriod
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def ong(db):
    admin = make_user(db, "admin@exemplu.md")
    org = make_org(db, admin, "AO Alfa", role=UserRole.admin)
    acc = make_accounts(db, org, "234.4", "235", "242", "521", "537", "616", "716")
    accountant = make_user(db, "contabil@exemplu.md")
    chief = make_user(db, "sef@exemplu.md")
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=accountant.id, role=UserRole.accountant),
            OrganizationMember(organization_id=org.id, user_id=chief.id, role=UserRole.chief_accountant),
        ]
    )
    db.flush()
    return admin, chief, accountant, org, acc


GRANT = {
    "code": "SOR-2026-01",
    "title": "Proiect Soros",
    "funding_type": "grant",
    "total_amount": "120000",
    "start_date": "2026-01-01",
    "end_date": "2026-12-31",
}


# ───────────── granturi și linii de buget ─────────────


def test_grant_cu_linii_de_buget(client, ong):
    _, _, accountant, org, _ = ong
    h = auth_headers(accountant)
    base = f"/organizations/{org.id}"
    r = client.post(f"{base}/grants", json=GRANT, headers=h)
    assert r.status_code == 201, r.text
    grant_id = r.json()["id"]
    assert client.post(f"{base}/grants", json=GRANT, headers=h).status_code == 409  # cod unic

    line = {"code": "2.1", "name": "Echipament", "planned_amount": "30000", "cofinancing_amount": "5000"}
    r = client.post(f"{base}/grants/{grant_id}/budget-lines", json=line, headers=h)
    assert r.status_code == 201 and r.json()["in_use"] is False
    line_id = r.json()["id"]
    assert client.post(f"{base}/grants/{grant_id}/budget-lines", json=line, headers=h).status_code == 409
    # cofinanțarea nu poate depăși totalul liniei (docs/02 §9a)
    bad = {**line, "code": "2.2", "cofinancing_amount": "40000"}
    assert client.post(f"{base}/grants/{grant_id}/budget-lines", json=bad, headers=h).status_code == 422

    r = client.put(f"{base}/budget-lines/{line_id}", json={**line, "planned_amount": "35000"}, headers=h)
    assert Decimal(r.json()["planned_amount"]) == 35000
    listed = client.get(f"{base}/grants", headers=h).json()
    assert listed[0]["budget_lines"][0]["code"] == "2.1"

    r = client.put(
        f"{base}/grants/{grant_id}", json={**GRANT, "title": "Proiect redenumit", "is_closed": True}, headers=h
    )
    assert r.json()["title"] == "Proiect redenumit" and r.json()["is_closed"] is True
    assert client.delete(f"{base}/budget-lines/{line_id}", headers=h).status_code == 204


def test_grant_date_si_sursa_validate(client, ong):
    _, _, accountant, org, _ = ong
    h = auth_headers(accountant)
    assert (
        client.post(f"/organizations/{org.id}/grants", json={**GRANT, "end_date": "2025-01-01"}, headers=h).status_code
        == 422
    )
    assert (
        client.post(f"/organizations/{org.id}/grants", json={**GRANT, "funding_type": "altceva"}, headers=h).status_code
        == 422
    )


def test_linia_folosita_nu_se_sterge(client, db, ong):
    _, _, accountant, org, _ = ong
    h = auth_headers(accountant)
    base = f"/organizations/{org.id}"
    grant_id = client.post(f"{base}/grants", json=GRANT, headers=h).json()["id"]
    line_id = client.post(
        f"{base}/grants/{grant_id}/budget-lines",
        json={"code": "3.2", "name": "Comunicații", "planned_amount": "6000"},
        headers=h,
    ).json()["id"]
    supplier = Counterparty(organization_id=org.id, name="Furnizor")
    db.add(supplier)
    db.flush()
    invoice = {
        "doc_number": "1",
        "doc_date": "2026-03-01",
        "counterparty_id": str(supplier.id),
        "lines": [{"description": "Internet", "amount": "100", "budget_line_id": line_id}],
    }
    assert client.post(f"{base}/invoices", json=invoice, headers=h).status_code == 201
    r = client.delete(f"{base}/budget-lines/{line_id}", headers=h)
    assert r.status_code == 409 and "folosită" in r.json()["detail"]
    assert client.get(f"{base}/grants/{grant_id}/budget-lines", headers=h).json()[0]["in_use"] is True


def test_grantul_altei_organizatii(client, db, ong):
    admin, _, _, org, _ = ong
    grant_id = client.post(f"/organizations/{org.id}/grants", json=GRANT, headers=auth_headers(admin)).json()["id"]
    intrus = make_user(db, "intrus@exemplu.md")
    other = make_org(db, intrus, "AO Beta")
    assert client.get(f"/organizations/{other.id}/grants/{grant_id}", headers=auth_headers(intrus)).status_code == 404
    r = client.put(f"/organizations/{other.id}/grants/{grant_id}", json=GRANT, headers=auth_headers(intrus))
    assert r.status_code == 404


# ───────────── politica contabilă ─────────────


def test_politica_pe_versiuni_schimba_formula(client, db, ong):
    """Varianta B [SEM] de la o dată: tranșa trece direct pe 537, fără cod nou."""
    _, chief, accountant, org, acc = ong
    h = auth_headers(chief)
    base = f"/organizations/{org.id}"
    v1 = {
        "valid_from": "2026-01-01",
        "grant_receivable_account_id": str(acc["234.4"].id),
        "grant_recognition": "on_signing",
    }
    r = client.post(f"{base}/accounting-policies", json=v1, headers=h)
    assert r.status_code == 201 and r.json()["approved_by_name"] == chief.full_name
    assert client.post(f"{base}/accounting-policies", json=v1, headers=h).status_code == 409
    v2 = {**v1, "valid_from": "2026-07-01", "grant_recognition": "on_receipt"}
    assert client.post(f"{base}/accounting-policies", json=v2, headers=h).status_code == 201
    assert [p["valid_from"] for p in client.get(f"{base}/accounting-policies", headers=h).json()] == [
        "2026-07-01",
        "2026-01-01",
    ]
    # contabilul nu aprobă politica
    assert (
        client.post(
            f"{base}/accounting-policies", json={**v1, "valid_from": "2027-01-01"}, headers=auth_headers(accountant)
        ).status_code
        == 403
    )

    grant_id = client.post(f"{base}/grants", json=GRANT, headers=h).json()["id"]
    doc_id = client.post(f"{base}/documents", json={"type": "other", "doc_date": "2026-03-01"}, headers=h).json()["id"]
    op = {"operation": "tranche_received", "amount": "100", "grant_id": grant_id}
    march = client.post(
        f"{base}/documents/{doc_id}/preview", json={"document_type": "grant_income", "operations": [op]}, headers=h
    )
    assert march.json()[0]["credit_account"] == "234.4"
    august = client.post(
        f"{base}/documents/{doc_id}/preview",
        json={"document_type": "grant_income", "operations": [{**op, "entry_date": "2026-08-01"}]},
        headers=h,
    )
    assert august.json()[0]["credit_account"] == "537"


def test_politica_valori_invalide(client, ong):
    _, chief, _, org, _ = ong
    r = client.post(
        f"/organizations/{org.id}/accounting-policies",
        json={"valid_from": "2026-01-01", "grant_recognition": "cand_vrem"},
        headers=auth_headers(chief),
    )
    assert r.status_code == 422


# ───────────── perioade ─────────────


def test_inchiderea_si_redeschiderea_perioadei(client, db, ong):
    _, chief, accountant, org, _ = ong
    base = f"/organizations/{org.id}/periods"
    assert client.post(f"{base}/2026/3/close", headers=auth_headers(chief)).status_code == 200
    months = client.get(base, params={"year": 2026}, headers=auth_headers(accountant)).json()
    assert len(months) == 12 and months[2]["is_closed"] is True and months[2]["closed_by_name"] == chief.full_name
    assert months[3]["is_closed"] is False

    assert (
        client.post(
            f"{base}/2026/3/reopen", json={"reason": "corectare factură"}, headers=auth_headers(accountant)
        ).status_code
        == 403
    )
    assert client.post(f"{base}/2026/3/reopen", json={"reason": "x"}, headers=auth_headers(chief)).status_code == 422
    r = client.post(f"{base}/2026/3/reopen", json={"reason": "corectare factură"}, headers=auth_headers(chief))
    assert r.status_code == 200 and r.json()["is_closed"] is False
    assert (
        client.post(f"{base}/2026/3/reopen", json={"reason": "din nou"}, headers=auth_headers(chief)).status_code == 409
    )
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "reopen_period"))
    assert audit.new_values["reason"] == "corectare factură"
    assert db.scalar(select(AccountingPeriod.is_closed).where(AccountingPeriod.organization_id == org.id)) is False


# ───────────── planul de conturi ─────────────


def test_cont_nou_in_plan(client, ong):
    _, chief, accountant, org, acc = ong
    base = f"/organizations/{org.id}/accounts"
    body = {"code": "217", "name": "Mărfuri", "account_kind": "active"}
    assert client.post(base, json=body, headers=auth_headers(accountant)).status_code == 403
    r = client.post(base, json=body, headers=auth_headers(chief))
    assert r.status_code == 201
    assert client.post(base, json=body, headers=auth_headers(chief)).status_code == 409
    assert client.post(base, json={**body, "code": "21A"}, headers=auth_headers(chief)).status_code == 422
    sub = {"code": "242.1", "name": "Cont curent proiect", "account_kind": "active", "parent_id": str(acc["242"].id)}
    assert client.post(base, json=sub, headers=auth_headers(chief)).status_code == 201
    assert "217" in [a["code"] for a in client.get(base, headers=auth_headers(accountant)).json()]


# ───────────── utilizatori și drepturi ─────────────


def test_utilizatori_si_roluri(client, db, ong):
    admin, chief, accountant, org, _ = ong
    h = auth_headers(admin)
    base = f"/organizations/{org.id}/members"
    assert {m["email"] for m in client.get(base, headers=h).json()} == {
        "admin@exemplu.md",
        "sef@exemplu.md",
        "contabil@exemplu.md",
    }

    # utilizator nou: cere nume și parolă; apoi se poate autentifica și vede organizația
    assert client.post(base, json={"email": "nou@exemplu.md", "role": "auditor"}, headers=h).status_code == 422
    r = client.post(
        base,
        json={"email": "Nou@Exemplu.md", "full_name": "Auditor Nou", "role": "auditor", "password": "parola-initiala"},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["email"] == "nou@exemplu.md"
    tokens = client.post("/auth/login", json={"email": "nou@exemplu.md", "password": "parola-initiala"}).json()
    ws = client.get("/workspaces", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert ws[0]["organizations"][0]["role"] == "auditor"

    # utilizator existent din altă organizație: primește doar rolul
    other_user = make_user(db, "extern@exemplu.md")
    make_org(db, other_user, "AO Beta")
    r = client.post(base, json={"email": "extern@exemplu.md", "role": "project_manager"}, headers=h)
    assert r.status_code == 201
    assert client.post(base, json={"email": "extern@exemplu.md", "role": "accountant"}, headers=h).status_code == 409

    member_id = r.json()["id"]
    assert client.patch(f"{base}/{member_id}", json={"role": "accountant"}, headers=h).json()["role"] == "accountant"
    assert client.delete(f"{base}/{member_id}", headers=h).status_code == 204


def test_ramane_cel_putin_un_administrator(client, ong):
    admin, _, _, org, _ = ong
    h = auth_headers(admin)
    base = f"/organizations/{org.id}/members"
    me = next(m for m in client.get(base, headers=h).json() if m["email"] == "admin@exemplu.md")
    assert client.patch(f"{base}/{me['id']}", json={"role": "accountant"}, headers=h).status_code == 409
    assert client.delete(f"{base}/{me['id']}", headers=h).status_code == 409


def test_doar_administratorul_gestioneaza_utilizatorii(client, ong):
    _, chief, accountant, org, _ = ong
    base = f"/organizations/{org.id}/members"
    assert client.get(base, headers=auth_headers(chief)).status_code == 403
    assert client.get(base, headers=auth_headers(accountant)).status_code == 403
    body = {"email": "x@exemplu.md", "full_name": "X", "role": "admin", "password": "parola-initiala"}
    assert client.post(base, json=body, headers=auth_headers(chief)).status_code == 403
