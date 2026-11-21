import jwt

from app.core.config import get_settings
from app.core.security import create_token, hash_password, verify_password
from tests.conftest import auth_headers, make_org, make_user


def test_parola_argon2():
    h = hash_password("secret")
    assert h.startswith("$argon2")
    assert verify_password(h, "secret")
    assert not verify_password(h, "altceva")


def test_login_si_me(client, db):
    make_user(db, "contabil@exemplu.md", "parola-buna")
    r = client.post("/auth/login", json={"email": "Contabil@Exemplu.md", "password": "parola-buna"})
    assert r.status_code == 200
    tokens = r.json()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "contabil@exemplu.md"


def test_login_parola_gresita(client, db):
    make_user(db, "contabil@exemplu.md", "parola-buna")
    r = client.post("/auth/login", json={"email": "contabil@exemplu.md", "password": "gresit"})
    assert r.status_code == 401


def test_refresh_nu_merge_ca_acces(client, db):
    user = make_user(db, "a@exemplu.md")
    refresh = create_token(user.id, "refresh")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    r = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_jeton_expirat(client, db):
    user = make_user(db, "a@exemplu.md")
    s = get_settings()
    expired = jwt.encode({"sub": str(user.id), "type": "access", "exp": 1}, s.jwt_secret, algorithm=s.jwt_algorithm)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_fara_jeton(client):
    assert client.get("/auth/me").status_code == 401


def test_acces_doar_la_organizatiile_proprii(client, db):
    a = make_user(db, "a@exemplu.md")
    b = make_user(db, "b@exemplu.md")
    org_b = make_org(db, b, "AO Beta")
    r = client.get(f"/organizations/{org_b.id}/accounts", headers=auth_headers(a))
    assert r.status_code == 404
    assert client.get(f"/organizations/{org_b.id}/accounts", headers=auth_headers(b)).status_code == 200
