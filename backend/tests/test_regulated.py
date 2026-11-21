"""ONG17, 5-CON, calendarul raportărilor, descifrarea celulelor și exportul (docs/06, docs/07)."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.auth.models import OrganizationMember
from app.core.enums import DocumentType, UserRole
from app.documents.models import Document
from app.grants.models import BudgetLine, CostItem, Grant
from app.posting.engine import LineInput, post_document
from app.regulated.formulas import FormulaError, evaluate
from app.regulated.models import OrganizationStats
from tests.conftest import auth_headers, make_accounts, make_org, make_user

CODES = ("124", "234", "242", "331", "3411", "521", "537", "616", "617", "618", "716", "717", "718")


def _grant(db, org, code, funding, **kw):
    g = Grant(organization_id=org.id, code=code, title=code, funding_type=funding, currency="MDL",
              total_amount=kw.pop("total", Decimal(10000)), start_date=date(2025, 1, 1), end_date=date(2027, 12, 31), **kw)  # fmt: skip
    db.add(g)
    db.flush()
    return g


@pytest.fixture
def ong(db):
    """Un an de activitate (2026, tot în trimestrul IV) cu toate tipurile de venituri și cheltuieli."""
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    org.ngo_category, org.caem, org.sfs_office, org.cuiio = "A", "9499", "DFC Centru", "40000000"
    acc = make_accounts(db, org, *CODES)
    sor = _grant(db, org, "SOR", "grant")
    own = _grant(db, org, "PROP", "unrestricted")
    dp = _grant(db, org, "DP2025", "percentage_designation", designation_year=2025, total=Decimal(5000))
    line = BudgetLine(grant_id=sor.id, code="1", name="Comunicații", planned_amount=Decimal(1000))
    internet = CostItem(organization_id=org.id, name="Internet", con5_article="072")
    charity = CostItem(organization_id=org.id, name="Ajutoare", con5_article="210", designation_category="social_charity")
    db.add_all([line, internet, charity])
    db.flush()

    def post(d, dt, kt, amount, **kw):
        doc = Document(organization_id=org.id, type=DocumentType.other, doc_number=f"D{amount}", doc_date=d)
        db.add(doc)
        db.flush()
        post_document(db, organization_id=org.id, document_id=doc.id, user_id=user.id,
                      lines=[LineInput(debit_account_id=acc[dt].id, credit_account_id=acc[kt].id, amount=Decimal(amount), **kw)])  # fmt: skip
        return doc

    q4 = date(2026, 10, 15)
    post(q4, "716", "521", 1500, grant_id=sor.id, budget_line_id=line.id, cost_item_id=internet.id,
         activity_type="special_purpose")  # 500 peste buget
    post(q4, "537", "616", 1500, grant_id=sor.id, activity_type="special_purpose")
    post(q4, "234", "617", 300)  # cotizație
    post(q4, "242", "618", 2000)
    post(q4, "718", "521", 800)
    post(q4, "717", "521", 200, grant_id=own.id, is_non_statutory=True)
    post(date(2025, 6, 1), "242", "617", 5000, grant_id=dp.id)  # desemnarea primită în 2025
    post(q4, "717", "521", 600, grant_id=dp.id, cost_item_id=charity.id)
    post(q4, "717", "521", 100, grant_id=dp.id, is_non_statutory=True)
    post(q4, "3411", "124", 50)  # amortizarea
    post(date(2026, 12, 31), "616", "331", 1500)  # închiderea anului — nu se numără
    db.add(OrganizationStats(organization_id=org.id, period_end=date(2026, 12, 31), members_count=40, volunteers_count=12))
    db.flush()
    return user, org, acc


def _generate(client, org, user, code, period_from):
    r = client.post(f"/organizations/{org.id}/reports/tax-reports", json={"code": code, "period_from": period_from},
                    headers=auth_headers(user))  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def _values(report):
    return {row["code"]: Decimal(row["value"]) for row in report["rows"]}


def test_ong17_fiecare_rand(client, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "ONG17", "2026-01-01")
    v = _values(report)
    expected = {
        "01011": 1500, "01012": 2000, "01013": 300, "0101": 3800, "01014": 0,
        "01021": 1500, "010211": 500, "01022": 800, "01023": 900, "010231": 200, "01024": 700, "010241": 100,
        "0102": 3200, "010": 600, "020": 800, "030": 0, "040": 0, "050": 12, "060": 96, "CTRL": 96,
    }  # fmt: skip
    assert {k: v[k] for k in expected} == {k: Decimal(x) for k, x in expected.items()}
    assert report["header"]["ngo_category"] == "A" and report["header"]["period"] == "2026"
    assert not [c for c in report["checks"] if c["severity"] == "error"]
    # totalurile coincid cu balanța (fără închiderea anului)
    assert not [c for c in report["checks"] if "diferă" in c["message"]]
    annex = report["annex_1d"][0]
    assert annex["grant_code"] == "DP2025" and Decimal(annex["received"]) == 5000
    assert annex["columns"][0]["total"] == "0" and Decimal(annex["columns"][1]["total"]) == 700
    assert Decimal(annex["columns"][1]["social_charity"]) == 600 and annex["columns"][2] is None
    assert Decimal(annex["remaining"]) == 4300 and annex["to_refund"] is False
    assert any("fără categoria desemnării" in c["message"] for c in report["checks"])


def test_ong17_de_restituit_dupa_doi_ani(client, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "ONG17", "2027-01-01")
    annex = report["annex_1d"][0]
    assert annex["to_refund"] is True and Decimal(annex["remaining"]) == 4300
    assert any("de restituit" in c["message"] for c in report["checks"])


def test_corectii_verificari_si_depunere(client, db, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "ONG17", "2026-01-01")
    base = f"/organizations/{org.id}/reports/tax-reports/{report['id']}"
    h = auth_headers(user)

    r = client.put(f"{base}/overrides", json={"cells": {"010211": "5000"}}, headers=h)
    assert r.status_code == 200
    rows = {x["code"]: x for x in r.json()["rows"]}
    assert rows["010211"]["overridden"] and Decimal(rows["010211"]["calculated"]) == 500
    assert Decimal(rows["020"]["value"]) == 5300  # totalurile urmează corecția
    assert any("010211 nu poate depăși 01021" in c["message"] for c in r.json()["checks"])
    assert client.post(f"{base}/status", json={"status": "submitted"}, headers=h).status_code == 422
    assert client.put(f"{base}/overrides", json={"cells": {"XYZ": "1"}}, headers=h).status_code == 422

    # o corecție a unui total care nu se potrivește cu formula = eroare
    r = client.put(f"{base}/overrides", json={"cells": {"010211": None, "0101": "1"}}, headers=h)
    assert any(c.get("cell") == "0101" for c in r.json()["checks"])
    client.put(f"{base}/overrides", json={"cells": {"0101": None}}, headers=h)

    # contabilul nu depune, contabilul-șef da
    accountant = make_user(db, "contabil2@exemplu.md")
    db.add(OrganizationMember(organization_id=org.id, user_id=accountant.id, role=UserRole.accountant))
    db.flush()
    assert client.post(f"{base}/status", json={"status": "submitted"}, headers=auth_headers(accountant)).status_code == 403
    r = client.post(f"{base}/status", json={"status": "submitted"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "submitted"

    # înghețat: nici corecții, nici ștergere; „Generează” face un raport nou
    assert client.put(f"{base}/overrides", json={"cells": {"010": "1"}}, headers=h).status_code == 409
    assert client.delete(base, headers=h).status_code == 409
    again = _generate(client, org, user, "ONG17", "2026-01-01")
    assert again["id"] != report["id"] and again["status"] == "draft"
    assert client.get(base, headers=h).json()["status"] == "submitted"


def test_descifrarea_celulei(client, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "ONG17", "2026-01-01")
    base = f"/organizations/{org.id}/reports/tax-reports/{report['id']}/cells"
    r = client.get(f"{base}/010211", headers=auth_headers(user)).json()
    assert [i["kind"] for i in r["items"]] == ["budget_excess"] and Decimal(r["items"][0]["amount"]) == 500
    r = client.get(f"{base}/0101", headers=auth_headers(user)).json()
    entries = [i for i in r["items"] if i["kind"] == "entry"]
    assert sorted(Decimal(i["amount"]) for i in entries) == [300, 1500, 2000]
    assert all(i["credit_account"] != "331" for i in entries) and r["changed_since_report"] is False
    assert client.get(f"{base}/999", headers=auth_headers(user)).status_code == 404


def test_5con_trimestrul_iv(client, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "5-CON", "2026-10-01")
    v = _values(report)
    expected = {
        "011": "0.3", "017": "1.5", "012": "1.5", "029": "2.0", "024": "2.0", "010": "3.8",
        "072": "1.5", "070": "1.5", "091": "0.1", "090": "0.1", "210": "0.6", "230": "1.1", "120": "1.7",
        "040": "3.3", "300": "40", "320": "12", "013": "0",
    }  # fmt: skip
    assert {k: v[k] for k in expected} == {k: Decimal(x) for k, x in expected.items()}
    assert report["header"]["flag1"] == "1" and report["header"]["TRIM"] == "4"
    assert any("fără articol 5-CON" in c["message"] for c in report["checks"])
    assert not [c for c in report["checks"] if c["severity"] == "error"]

    h = auth_headers(user)
    xml = client.get(f"/organizations/{org.id}/reports/tax-reports/{report['id']}/export.xml", headers=h)
    assert xml.status_code == 200 and b"<CAP1_R072_C1>1.5</CAP1_R072_C1>" in xml.content
    assert b"<CUIIO>40000000</CUIIO>" in xml.content
    xlsx = client.get(f"/organizations/{org.id}/reports/tax-reports/{report['id']}/export.xlsx", headers=h)
    ws = load_workbook(BytesIO(xlsx.content)).active
    assert any(row[0] == "072" and row[2] == 1.5 for row in ws.iter_rows(values_only=True))


def test_5con_fara_activitate_si_perioada_gresita(client, ong):
    user, org, _ = ong
    report = _generate(client, org, user, "5-CON", "2026-01-01")
    assert report["header"]["flag1"] == "0" and _values(report)["040"] == 0
    r = client.post(f"/organizations/{org.id}/reports/tax-reports", json={"code": "5-CON", "period_from": "2026-02-01"},
                    headers=auth_headers(user))  # fmt: skip
    assert r.status_code == 422
    # XML există doar pentru 5-CON
    ong17 = _generate(client, org, user, "ONG17", "2026-01-01")
    assert client.get(f"/organizations/{org.id}/reports/tax-reports/{ong17['id']}/export.xml",
                      headers=auth_headers(user)).status_code == 422  # fmt: skip


def test_calendarul_raportarilor(client, ong):
    user, org, _ = ong
    h = auth_headers(user)
    url = f"/organizations/{org.id}/reports/calendar"
    items = client.get(url, params={"on": "2027-01-20"}, headers=h).json()
    by = {(i["code"], i["period_from"]): i for i in items}
    assert by[("5-CON", "2026-10-01")]["due_date"] == "2027-01-25"
    assert by[("5-CON", "2026-10-01")]["status_label"] == "A rămas o săptămână"
    assert by[("5-CON", "2026-07-01")]["status_label"] == "Restanță"
    assert by[("IPC21", "2026-12-01")]["due_date"] == "2027-01-25"
    assert by[("ONG17", "2026-01-01")]["status_label"] == "În termen"
    assert by[("ONG17", "2026-01-01")]["due_date"] == "2027-03-25"

    report = _generate(client, org, user, "5-CON", "2026-10-01")
    client.post(f"/organizations/{org.id}/reports/tax-reports/{report['id']}/status", json={"status": "submitted"}, headers=h)
    items = {(i["code"], i["period_from"]): i for i in client.get(url, params={"on": "2027-01-20"}, headers=h).json()}
    assert items[("5-CON", "2026-10-01")]["status_label"] == "Prezentat"
    assert items[("5-CON", "2026-10-01")]["tax_report_id"] == report["id"]


def test_calendar_fara_rapoarte_ong_pentru_srl(client, db):
    from app.core.enums import EntityType

    user = make_user(db, "srl@exemplu.md")
    org = make_org(db, user, "SRL Beta")
    org.entity_type = EntityType.srl
    db.flush()
    items = client.get(f"/organizations/{org.id}/reports/calendar", params={"on": "2027-01-20"},
                       headers=auth_headers(user)).json()  # fmt: skip
    assert {i["code"] for i in items} == {"IPC21"}
    # o bază nouă fără istoric: fără termene dinaintea creării organizației
    assert min(i["period_to"] for i in items) >= org.created_at.date().isoformat()


def test_izolarea_pe_organizatie(client, db, ong):
    user, org, acc = ong
    report = _generate(client, org, user, "ONG17", "2026-01-01")
    intrus = make_user(db, "intrus@exemplu.md")
    other = make_org(db, intrus, "AO Gama")
    h = auth_headers(intrus)
    for path in ("reports/calendar", "reports/tax-reports", "cost-items", "organization-stats", "reporting-profile",
                 f"reports/tax-reports/{report['id']}"):  # fmt: skip
        assert client.get(f"/organizations/{org.id}/{path}", headers=h).status_code == 404
    # raportul altei organizații nu se vede nici prin organizația proprie
    assert client.get(f"/organizations/{other.id}/reports/tax-reports/{report['id']}", headers=h).status_code == 404
    assert client.get(f"/organizations/{other.id}/reports/account-card",
                      params={"account_id": str(acc["521"].id), "date_from": "2026-01-01", "date_to": "2026-12-31"},
                      headers=h).status_code == 404  # fmt: skip
    # rapoartele organizației noi nu văd datele celeilalte
    mine = _generate(client, other, intrus, "ONG17", "2026-01-01")
    assert _values(mine)["0101"] == 0


def test_articolele_de_cheltuieli(client, db, ong):
    user, org, _ = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}/cost-items"
    assert any(a["code"] == "071" for a in client.get(f"/organizations/{org.id}/con5-articles", headers=h).json())
    assert client.post(base, json={"name": "X", "con5_article": "999"}, headers=h).status_code == 422
    assert client.post(base, json={"name": "X", "designation_category": "alta"}, headers=h).status_code == 422
    r = client.post(base, json={"name": "Transport", "con5_article": "71"}, headers=h)
    assert r.status_code == 201 and r.json()["con5_article"] == "071"
    item = r.json()["id"]
    r = client.put(f"{base}/{item}", json={"name": "Transport local", "con5_article": "071"}, headers=h)
    assert r.json()["name"] == "Transport local"
    assert client.delete(f"{base}/{item}", headers=h).status_code == 204
    used = next(i for i in client.get(base, headers=h).json() if i["name"] == "Internet")
    assert client.delete(f"{base}/{used['id']}", headers=h).status_code == 409


def test_statistica_si_antetul(client, ong):
    user, org, _ = ong
    h = auth_headers(user)
    r = client.put(f"/organizations/{org.id}/organization-stats",
                   json={"period_end": "2026-12-31", "members_count": 41, "volunteers_count": 9}, headers=h)  # fmt: skip
    assert r.status_code == 200
    assert len(client.get(f"/organizations/{org.id}/organization-stats", headers=h).json()) == 1
    report = _generate(client, org, user, "5-CON", "2026-10-01")
    assert _values(report)["300"] == 41
    r = client.put(f"/organizations/{org.id}/reporting-profile", json={"ngo_category": "h"}, headers=h)
    assert r.status_code == 422
    r = client.put(f"/organizations/{org.id}/reporting-profile", json={"ngo_category": "b", "cfoj": "890"}, headers=h)
    assert r.json()["ngo_category"] == "B" and r.json()["cuiio"] is None
    assert any("CUIIO" in c["message"] for c in _generate(client, org, user, "5-CON", "2026-10-01")["checks"])


def test_fisa_si_analiza_contului(client, ong):
    user, org, acc = ong
    h = auth_headers(user)
    params = {"account_id": str(acc["521"].id), "date_from": "2026-01-01", "date_to": "2026-12-31"}
    card = client.get(f"/organizations/{org.id}/reports/account-card", params=params, headers=h).json()
    assert Decimal(card["opening"]) == 0 and Decimal(card["turnover_credit"]) == 3200
    assert Decimal(card["closing"]) == -3200 and Decimal(card["rows"][-1]["balance"]) == -3200
    assert {r["corresponding_account"] for r in card["rows"]} == {"716", "718", "717"}
    analysis = client.get(f"/organizations/{org.id}/reports/account-analysis", params=params, headers=h).json()
    assert {r["code"]: Decimal(r["credit"]) for r in analysis["rows"]} == {"716": 1500, "717": 900, "718": 800}
    params = {"account_id": str(acc["242"].id), "date_from": "2026-01-01", "date_to": "2026-12-31"}
    card = client.get(f"/organizations/{org.id}/reports/account-card", params=params, headers=h).json()
    assert Decimal(card["opening"]) == 5000 and Decimal(card["closing"]) == 7000
    xlsx = client.get(f"/organizations/{org.id}/reports/account-card.xlsx", params=params, headers=h)
    assert xlsx.status_code == 200 and load_workbook(BytesIO(xlsx.content)).active["A1"].value == "Fișa contului 242"


def test_formulele_nu_executa_cod():
    cell = {"a": Decimal(2)}.__getitem__
    assert evaluate("max(0, [a] - 5) + {s}", cell, lambda s: Decimal(1)) == 1
    assert evaluate("[a] * 3 / 2 >= 3 and 1 < 2", cell, lambda s: Decimal(0)) is True
    for bad in ("__import__('os')", "[a].real", "open('x')", "[a] ** 2"):
        with pytest.raises(FormulaError):
            evaluate(bad, cell, lambda s: Decimal(0))
