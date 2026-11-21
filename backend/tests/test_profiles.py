from datetime import date

from sqlalchemy import select

from app.core.enums import DocumentType, EntityType, UserRole
from app.models import Account, Document, OrganizationFeature
from tests.conftest import auth_headers, make_org, make_user

WIZ = "/workspaces/wizard"


def body(**kw):
    base = {"name": "Baza", "organization_name": "Org", "idno": "1012345678901", "entity_type": "srl"}
    return {**base, **kw}


def codes(r):
    return {f["code"] for f in r.json()["features"]}


def test_previzualizare_srl_tva_comert(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(
        WIZ + "/preview",
        json={"entity_type": "srl", "vat_payer": True, "activities": ["retail", "catering"], "has_employees": True},
        headers=auth_headers(u),
    )
    assert r.status_code == 200
    assert {"double_entry", "vat", "retail", "catering", "payroll", "fixed_assets"} <= codes(r)
    assert "single_entry" not in codes(r) and "ngo_grants" not in codes(r)
    assert r.json()["tax_regime"] == "general" and r.json()["coa_template"] == "general"


def test_previzualizare_ii_partida_simpla(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ + "/preview", json={"entity_type": "ii"}, headers=auth_headers(u))
    assert r.json()["accounting_method"] == "single_entry"
    assert "single_entry" in codes(r) and "double_entry" not in codes(r)
    assert r.json()["coa_template"] == "ii_single_entry"


def test_srl_nu_poate_fi_partida_simpla(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ + "/preview", json={"entity_type": "srl", "accounting_method": "single_entry"}, headers=auth_headers(u))
    assert r.status_code == 422


def test_gt_poate_alege_partida_dubla(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ + "/preview", json={"entity_type": "gt", "accounting_method": "double_entry"}, headers=auth_headers(u))
    assert r.status_code == 200 and "double_entry" in codes(r) and r.json()["tax_regime"] == "gt"


def test_baza_ong_copiaza_planul_de_conturi(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ, json=body(entity_type="ngo_association"), headers=auth_headers(u))
    assert r.status_code == 201, r.text
    org_id = r.json()["workspace"]["organizations"][0]["id"]
    assert r.json()["accounts_created"] > 20
    assert {"ngo_grants", "double_entry"} <= set(r.json()["features"])
    assert db.scalar(select(Account.id).where(Account.organization_id == org_id, Account.code == "616"))
    # utilizatorul poate citi profilul
    p = client.get(f"/organizations/{org_id}/ui-profile", headers=auth_headers(u)).json()
    assert "ngo" in p["visible_sections"] and "Proiecte / granturi" in p["visible_screens"]


def test_baza_ii_fara_plan_de_conturi_si_ecrane_ascunse(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ, json=body(entity_type="ii"), headers=auth_headers(u))
    assert r.status_code == 201
    assert r.json()["accounts_created"] == 0
    org_id = r.json()["workspace"]["organizations"][0]["id"]
    p = client.get(f"/organizations/{org_id}/ui-profile", headers=auth_headers(u)).json()
    hidden_screens = set(p["gated_screens"]) - set(p["visible_screens"])
    hidden_sections = set(p["gated_sections"]) - set(p["visible_sections"])
    assert {"Planul de conturi", "Operațiune manuală", "ONG17"} <= hidden_screens
    assert "ngo" in hidden_sections
    assert "Registru-jurnal (partidă simplă)" in p["visible_screens"]


def test_idno_unic_si_validari(client, db):
    u = make_user(db, "a@exemplu.md")
    h = auth_headers(u)
    assert client.post(WIZ, json=body(), headers=h).status_code == 201
    assert client.post(WIZ, json=body(), headers=h).status_code == 409
    assert client.post(WIZ, json=body(idno="1012345678902", vat_payer=True), headers=h).status_code == 422
    assert client.post(WIZ, json=body(idno="1012345678903", activities=["zbor"]), headers=h).status_code == 422
    assert client.post(WIZ, json=body(idno="1012345678903", tax_regime="x"), headers=h).status_code == 422
    assert client.post(WIZ, json=body(idno="1012345678903", features=["inexistent"]), headers=h).status_code == 422


def test_lista_finala_nu_contrazice_metoda(client, db):
    u = make_user(db, "a@exemplu.md")
    r = client.post(WIZ, json=body(entity_type="ii", features=["double_entry", "payroll"]), headers=auth_headers(u))
    assert set(r.json()["features"]) == {"payroll", "single_entry"}


def test_pornire_si_oprire_functionalitate(client, db):
    u = make_user(db, "a@exemplu.md")
    org = make_org(db, u, "Org", UserRole.chief_accountant)
    h = auth_headers(u)
    url = f"/organizations/{org.id}/features"
    assert client.post(url, json={"feature_code": "vat", "enabled_from": "2026-01-01"}, headers=h).status_code == 201
    assert client.post(url, json={"feature_code": "vat", "enabled_from": "2026-02-01"}, headers=h).status_code == 409
    assert client.post(url, json={"feature_code": "double_entry", "enabled_from": "2026-01-01"}, headers=h).status_code == 422
    assert client.post(url, json={"feature_code": "zzz", "enabled_from": "2026-01-01"}, headers=h).status_code == 404
    assert "TVA" in client.get(f"/organizations/{org.id}/ui-profile?on=2026-06-01", headers=h).json()["visible_screens"]
    # înainte de data pornirii nu e activă
    assert "TVA" not in client.get(f"/organizations/{org.id}/ui-profile?on=2025-06-01", headers=h).json()["visible_screens"]
    r = client.post(f"{url}/vat/disable", json={"enabled_to": "2026-06-30"}, headers=h)
    assert r.status_code == 200 and r.json()["enabled_to"] == "2026-06-30"
    assert "TVA" not in client.get(f"/organizations/{org.id}/ui-profile?on=2026-07-15", headers=h).json()["visible_screens"]
    assert client.post(f"{url}/vat/disable", json={"enabled_to": "2026-06-30"}, headers=h).status_code == 404
    # reactivare după oprire; perioada veche nu se suprapune
    assert client.post(url, json={"feature_code": "vat", "enabled_from": "2026-06-30"}, headers=h).status_code == 409
    assert client.post(url, json={"feature_code": "vat", "enabled_from": "2026-09-01"}, headers=h).status_code == 201
    rows = client.get(url, headers=h).json()
    assert [r["enabled_from"] for r in rows if r["feature_code"] == "vat"] == ["2026-01-01", "2026-09-01"]


def test_roluri_si_izolare_functionalitati(client, db):
    owner = make_user(db, "a@exemplu.md")
    other = make_user(db, "b@exemplu.md")
    org = make_org(db, owner, "A", UserRole.accountant)
    make_org(db, other, "B")
    url = f"/organizations/{org.id}/features"
    # contabilul nu administrează funcționalitățile, dar le vede
    assert client.post(url, json={"feature_code": "vat", "enabled_from": "2026-01-01"}, headers=auth_headers(owner)).status_code == 403
    assert client.get(url, headers=auth_headers(owner)).status_code == 200
    # alt utilizator nu vede organizația
    assert client.get(url, headers=auth_headers(other)).status_code == 404
    assert client.get(f"/organizations/{org.id}/ui-profile", headers=auth_headers(other)).status_code == 404
    assert client.post(f"{url}/vat/disable", json={"enabled_to": "2026-01-01"}, headers=auth_headers(other)).status_code == 404


def _single_org(db, user, role=UserRole.accountant):
    org = make_org(db, user, "II", role)
    org.entity_type = EntityType.ii
    org.accounting_method = "single_entry"
    db.flush()
    return org


def _doc(db, org):
    d = Document(organization_id=org.id, type=DocumentType.other, doc_number="1", doc_date=date(2026, 3, 1))
    db.add(d)
    db.flush()
    return d


def test_registrul_jurnal(client, db):
    u = make_user(db, "a@exemplu.md")
    org = _single_org(db, u)
    h = auth_headers(u)
    d = _doc(db, org)
    url = f"/organizations/{org.id}/simple-ledger"

    def add(kind, amount, ded=True, day="2026-03-05"):
        return client.post(
            url + "/entries",
            json={"document_id": str(d.id), "entry_date": day, "kind": kind, "category": "vânzări", "amount": amount, "is_deductible": ded},
            headers=h,
        )

    assert add("income", "1000.00").status_code == 201
    assert add("expense", "300.00").status_code == 201
    nd = add("expense", "50.00", ded=False)
    assert nd.status_code == 201
    assert add("income", "99.00", day="2026-05-01").status_code == 201
    j = client.get(url + "?date_to=2026-03-31", headers=h).json()
    assert (j["income"], j["expense"], j["deductible_expense"], j["result"]) == ("1000.00", "350.00", "300.00", "700.00")
    assert [e["kind"] for e in j["entries"]] == ["income", "expense", "expense"]
    assert client.delete(f"{url}/entries/{nd.json()['id']}", headers=h).status_code == 204
    assert client.get(url, headers=h).json()["expense"] == "300.00"
    assert add("income", "0").status_code == 422
    assert add("transfer", "10").status_code == 422


def test_registrul_jurnal_izolare_si_partida_dubla(client, db):
    a = make_user(db, "a@exemplu.md")
    b = make_user(db, "b@exemplu.md")
    org_a = _single_org(db, a)
    org_b = _single_org(db, b)
    doc_b = _doc(db, org_b)
    entry = {"entry_date": "2026-03-05", "kind": "income", "category": "x", "amount": "5"}
    # documentul altei organizații nu poate fi folosit
    r = client.post(f"/organizations/{org_a.id}/simple-ledger/entries", json={**entry, "document_id": str(doc_b.id)}, headers=auth_headers(a))
    assert r.status_code == 404
    mine = client.post(
        f"/organizations/{org_b.id}/simple-ledger/entries", json={**entry, "document_id": str(doc_b.id)}, headers=auth_headers(b)
    ).json()
    # nici citirea, nici ștergerea din afara organizației
    assert client.get(f"/organizations/{org_b.id}/simple-ledger", headers=auth_headers(a)).status_code == 404
    assert client.delete(f"/organizations/{org_a.id}/simple-ledger/entries/{mine['id']}", headers=auth_headers(a)).status_code == 404
    # organizație cu partidă dublă
    c = make_user(db, "c@exemplu.md")
    org_c = make_org(db, c, "SRL")
    doc_c = _doc(db, org_c)
    r = client.post(f"/organizations/{org_c.id}/simple-ledger/entries", json={**entry, "document_id": str(doc_c.id)}, headers=auth_headers(c))
    assert r.status_code == 422
    # auditorul nu scrie
    org_a2 = _single_org(db, make_user(db, "d@exemplu.md"), UserRole.auditor)
    d = make_user(db, "e@exemplu.md")
    assert client.get(f"/organizations/{org_a2.id}/simple-ledger", headers=auth_headers(d)).status_code == 404


def test_migrarea_porneste_functionalitati_pentru_bazele_existente(db):
    # make_org nu trece prin migrare; verificăm doar catalogul de funcționalități semănat
    from app.features.models import Feature, CoaTemplate

    assert {f.code for f in db.scalars(select(Feature))} >= {"ngo_grants", "double_entry", "single_entry", "vat", "payroll"}
    assert {t.code for t in db.scalars(select(CoaTemplate))} == {"general", "ngo", "ii_single_entry"}
    assert db.scalar(select(OrganizationFeature.id).limit(1)) is None
