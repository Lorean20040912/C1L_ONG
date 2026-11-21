"""API-ul salariilor: validări (scutiri doar la CIM de bază, finanțare ≤ 100%),
fluxul complet prin închiderea lunii și izolarea pe organizație."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.enums import UserRole
from app.grants.models import BudgetLine, Grant
from tests.conftest import auth_headers, make_org, make_user
from tests.test_payroll import ong  # noqa: F401 — fixture-ul comun

IDNP = "2001234567890"


def base(org) -> str:
    return f"/organizations/{org.id}"


@pytest.fixture
def api(client, ong):  # noqa: F811
    user, org, acc, grants, lines, bank = ong
    return client, auth_headers(user), org, grants, lines, bank


def new_person(client, h, org, name="Popescu Ion", idnp=IDNP, cpas="123"):
    r = client.post(f"{base(org)}/persons", json={"full_name": name, "idnp": idnp, "cpas": cpas}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def contract_body(person_id, grants, lines, **extra):
    body = {
        "person_id": person_id,
        "type": "cim",
        "is_main_job": True,
        "number": "CIM-1",
        "start_date": "2026-01-01",
        "gross_amount": "10000",
        "funding": [
            {"grant_id": str(grants["sor"].id), "budget_line_id": str(lines["sal"].id), "share_percent": "100",
             "valid_from": "2026-01-01"},
        ],  # fmt: skip
        "exemptions": [{"kind": "personal", "valid_from": "2026-01-01"}],
    }
    return {**body, **extra}


def test_persoana_idnp_criptat_si_unic(api, db):
    client, h, org, *_ = api
    p = new_person(client, h, org)
    assert p["idnp"] == IDNP and p["idnp_masked"] == "200•••••••890"
    # în listă IDNP-ul apare doar mascat; complet — la cererea unei persoane, pentru editare
    assert client.get(f"{base(org)}/persons", headers=h).json()[0]["idnp"] is None
    assert client.get(f"{base(org)}/persons/{p['id']}", headers=h).json()["idnp"] == IDNP
    from app.payroll.models import Person

    assert db.get(Person, p["id"]).idnp_enc != IDNP  # în BD stă criptat
    assert client.post(f"{base(org)}/persons", json={"full_name": "Alt", "idnp": IDNP}, headers=h).status_code == 422
    assert client.post(f"{base(org)}/persons", json={"full_name": "Alt", "idnp": "123"}, headers=h).status_code == 422


def test_validarile_contractului(api):
    client, h, org, grants, lines, _ = api
    p = new_person(client, h, org)
    url = f"{base(org)}/contracts"
    # scutirea la contract civil — refuzată
    r = client.post(url, json=contract_body(p["id"], grants, lines, type="civil", is_main_job=False), headers=h)
    assert r.status_code == 422 and "Locul de muncă" not in r.text
    # scutirea la CIM care nu e de bază — refuzată
    r = client.post(url, json=contract_body(p["id"], grants, lines, is_main_job=False), headers=h)
    assert r.status_code == 422 and "de bază" in r.json()["detail"]
    # dubla finanțare (peste 100%)
    body = contract_body(p["id"], grants, lines)
    body["funding"].append({**body["funding"][0], "grant_id": str(grants["own"].id), "budget_line_id": None,
                            "share_percent": "10"})  # fmt: skip
    r = client.post(url, json=body, headers=h)
    assert r.status_code == 422 and "100%" in r.json()["detail"]
    # linia de buget din alt grant
    body = contract_body(p["id"], grants, lines)
    body["funding"][0]["budget_line_id"] = str(lines["own"].id)
    assert client.post(url, json=body, headers=h).status_code == 422
    # corect
    r = client.post(url, json=contract_body(p["id"], grants, lines), headers=h)
    assert r.status_code == 201, r.text
    # al doilea CIM de bază în aceeași perioadă
    r = client.post(url, json=contract_body(p["id"], grants, lines, number="CIM-2"), headers=h)
    assert r.status_code == 422


def test_fluxul_complet_prin_api(api):
    client, h, org, grants, lines, bank = api
    p = new_person(client, h, org)
    c = client.post(f"{base(org)}/contracts", json=contract_body(p["id"], grants, lines), headers=h).json()
    mc = f"{base(org)}/month-close/2026/11/steps/payroll"
    preview = client.post(f"{mc}/preview", headers=h).json()
    assert preview["total"] == "10000.00" and preview["errors"] == []
    r = client.post(f"{mc}/run", headers=h)
    assert r.status_code == 200, r.text
    assert next(s for s in r.json()["steps"] if s["step"] == "payroll")["status"] == "done"

    sheet = client.get(f"{base(org)}/payroll/2026/11", headers=h).json()
    assert sheet["calculated"] and sheet["entries"][0]["net"] == "8305.00"
    assert sheet["totals"]["income_tax"] == "795.00"
    # contractul cu salarii calculate nu se șterge și nu-și schimbă persoana / tipul
    assert client.delete(f"{base(org)}/contracts/{c['id']}", headers=h).status_code == 409
    other = new_person(client, h, org, "Rusu Maria", "2009876543210")
    changed = contract_body(other["id"], grants, lines)
    assert client.put(f"{base(org)}/contracts/{c['id']}", json=changed, headers=h).status_code == 409
    raised = contract_body(p["id"], grants, lines, gross_amount="11000")
    assert client.put(f"{base(org)}/contracts/{c['id']}", json=raised, headers=h).status_code == 200

    gp = client.post(
        f"{base(org)}/payroll/2026/11/grouped-payments",
        json={"tax_kind": "cnam", "bank_account_id": str(bank.id), "doc_number": "55", "doc_date": "2026-12-03"},
        headers=h,
    )
    assert gp.status_code == 201, gp.text
    doc_id = gp.json()["document_id"]
    assert gp.json()["amount"] == "900.00" and gp.json()["lines"][0]["person_name"] == "Popescu Ion"
    assert len(client.get(f"{base(org)}/payroll/2026/11/grouped-payments", headers=h).json()) == 1
    # ordinul cumulat nu se editează ca un ordin obișnuit, dar se înregistrează pe ruta lui
    po = client.get(f"{base(org)}/payment-orders/{doc_id}", headers=h).json()
    assert po["kind"] == "grouped_tax" and po["tax_kind"] == "cnam"
    preview = client.post(f"{base(org)}/payment-orders/{doc_id}/preview", headers=h).json()
    assert [(x["debit_account"], x["credit_account"], x["amount"]) for x in preview] == [("533", "242", "900.00")]
    assert client.post(f"{base(org)}/payment-orders/{doc_id}/post", headers=h).status_code == 200
    # cât timp există plata, pasul nu se anulează
    assert client.post(f"{mc}/revert", headers=h).status_code == 422
    client.post(f"{base(org)}/payment-orders/{doc_id}/unpost", headers=h)
    assert client.delete(f"{base(org)}/grouped-payments/{doc_id}", headers=h).status_code == 204
    assert client.post(f"{mc}/revert", headers=h).status_code == 200

    rates = client.get(f"{base(org)}/tax-rates?on_date=2026-11-30", headers=h).json()
    assert {r["code"] for r in rates} >= {"INCOME_TAX", "CNAS_EMPLOYER", "WITHHOLDING_FOL"}


def test_plata_catre_persoana_fizica_si_ipc21(api):
    client, h, org, grants, lines, _ = api
    p = new_person(client, h, org, "Ceban Vasile", "2005555555555")
    body = {"doc_number": "CH-11", "person_id": p["id"], "payment_kind": "rent", "accrual_date": "2026-11-20",
            "gross": "2000", "budget_line_id": str(lines["chirie"].id)}  # fmt: skip
    r = client.post(f"{base(org)}/individual-payments", json=body, headers=h)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (doc["income_code"], doc["income_tax"], doc["net"]) == ("FOL", "140.00", "1860.00")
    assert client.post(f"{base(org)}/individual-payments/{doc['document_id']}/post", headers=h).status_code == 200
    # ruta generică de documente îl trimite la ruta lui
    assert client.post(f"{base(org)}/documents/{doc['document_id']}/post", json={"operations": []}, headers=h).status_code in (409, 422)
    report = client.get(f"{base(org)}/reports/ipc21/2026/11", headers=h).json()
    fol = next(x for x in report["table1"] if x["code"] == "FOL")
    assert (fol["c4"], fol["c5"]) == ("2000.00", "140.00")
    assert report["total"]["c5"] == "140.00" and report["control_sum"] == "0.00"
    xml = client.get(f"{base(org)}/reports/ipc21/2026/11/xml", headers=h)
    assert xml.status_code == 200 and b"<r41c5>140.00</r41c5>" in xml.content


def test_izolarea_pe_organizatie(api, db):
    client, h, org, grants, lines, bank = api
    p = new_person(client, h, org)
    c = client.post(f"{base(org)}/contracts", json=contract_body(p["id"], grants, lines), headers=h).json()

    intruder = make_user(db, "altul@exemplu.md")
    other = make_org(db, intruder, "AO Beta", role=UserRole.chief_accountant)
    foreign_grant = Grant(
        organization_id=other.id, code="X", title="X", funding_type="grant", currency="MDL",
        total_amount=Decimal(1000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )  # fmt: skip
    db.add(foreign_grant)
    db.flush()
    foreign_line = BudgetLine(grant_id=foreign_grant.id, code="1", name="X", planned_amount=Decimal(1000))
    db.add(foreign_line)
    db.flush()
    hx = auth_headers(intruder)

    # organizația altcuiva — 404
    for url in ("persons", "contracts", "payroll/2026/11", "reports/ipc21/2026/11", "individual-payments"):
        assert client.get(f"{base(org)}/{url}", headers=hx).status_code == 404
    # din propria organizație nu vede datele celeilalte
    assert client.get(f"{base(other)}/persons", headers=hx).json() == []
    assert client.get(f"{base(other)}/contracts", headers=hx).json() == []
    assert client.get(f"{base(other)}/contracts/{c['id']}", headers=hx).status_code == 404
    assert client.put(f"{base(other)}/persons/{p['id']}", json={"full_name": "Xu Yi", "idnp": IDNP}, headers=hx).status_code == 404
    # nu poate lega persoana / grantul altei organizații
    assert client.post(f"{base(other)}/contracts", json=contract_body(p["id"], grants, lines), headers=hx).status_code == 404
    own_person = new_person(client, hx, other, "Beta Ion", "2001111111111")
    r = client.post(f"{base(other)}/contracts", json=contract_body(own_person["id"], grants, lines), headers=hx)
    assert r.status_code == 422  # grantul primei organizații
    body = {"doc_number": "1", "person_id": own_person["id"], "payment_kind": "rent", "accrual_date": "2026-11-20",
            "gross": "100", "budget_line_id": str(lines["chirie"].id)}  # fmt: skip
    assert client.post(f"{base(other)}/individual-payments", json=body, headers=hx).status_code == 422
    # calculul celeilalte organizații nu include contractele primei
    client.post(f"{base(org)}/month-close/2026/11/steps/payroll/run", headers=h)
    assert client.get(f"{base(other)}/payroll/2026/11", headers=hx).json()["entries"] == []
    gp = {"tax_kind": "income_tax", "bank_account_id": str(bank.id), "doc_number": "1", "doc_date": "2026-12-01"}
    assert client.post(f"{base(other)}/payroll/2026/11/grouped-payments", json=gp, headers=hx).status_code == 422
    # rolul fără drept de înregistrare
    auditor = make_user(db, "auditor@exemplu.md")
    from app.auth.models import OrganizationMember

    db.add(OrganizationMember(organization_id=org.id, user_id=auditor.id, role=UserRole.auditor))
    db.flush()
    ha = auth_headers(auditor)
    assert client.get(f"{base(org)}/persons", headers=ha).status_code == 200
    assert client.get(f"{base(org)}/persons/{p['id']}", headers=ha).status_code == 403  # IDNP complet — nu
    assert client.post(f"{base(org)}/persons", json={"full_name": "Yu Yi", "idnp": "2002222222222"}, headers=ha).status_code == 403
