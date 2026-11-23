"""Fum: orice GET simplu (fără parametri de cale în afară de organizație) răspunde fără 5xx."""

from app.main import app
from tests.conftest import auth_headers, make_org, make_user

SKIP = ("/bnm",)  # apelează servicii externe


def test_toate_get_urile_organizatiei_fara_5xx(client, db):
    user = make_user(db, "fum@example.com")
    org = make_org(db, user, "Org Fum")
    paths = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or not path.startswith("/organizations/{organization_id}"):
            continue
        rest = path.replace("{organization_id}", str(org.id))
        if "{" in rest or any(s in rest for s in SKIP) or rest.endswith("/export") or "/export/" in rest:
            continue
        paths.append(rest)
    assert paths
    esuate = []
    for p in paths:
        r = client.get(p, headers=auth_headers(user))
        if r.status_code >= 500:
            esuate.append((p, r.status_code))
    assert not esuate, esuate
