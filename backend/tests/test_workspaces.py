from tests.conftest import auth_headers, make_org, make_user


def test_bazele_mele_arata_doar_bazele_proprii(client, db):
    a = make_user(db, "a@exemplu.md")
    b = make_user(db, "b@exemplu.md")
    make_org(db, a, "AO Alfa")
    make_org(db, b, "AO Beta")
    r = client.get("/workspaces", headers=auth_headers(a))
    assert r.status_code == 200
    names = [w["name"] for w in r.json()]
    assert names == ["AO Alfa"]
    assert r.json()[0]["organizations"][0]["role"] == "chief_accountant"


def test_baza_noua(client, db):
    user = make_user(db, "a@exemplu.md")
    body = {"name": "GȚ Popescu", "organization_name": "GȚ Popescu Ion", "idno": "1012345678901", "entity_type": "gt"}
    r = client.post("/workspaces", json=body, headers=auth_headers(user))
    assert r.status_code == 201
    org = r.json()["organizations"][0]
    assert org["role"] == "admin"
    assert org["accounting_method"] == "single_entry"
    assert len(client.get("/workspaces", headers=auth_headers(user)).json()) == 1
    # IDNO-ul e unic
    assert client.post("/workspaces", json=body, headers=auth_headers(user)).status_code == 409
