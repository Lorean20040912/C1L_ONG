import base64

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import totp
from app.core.crypto import decrypt
from app.core.enums import UserRole
from tests.conftest import auth_headers, make_org, make_user


def _login(client, email, password="parola-test-1"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _enable_2fa(client, user):
    h = auth_headers(user)
    secret = client.post("/auth/2fa/setup", headers=h).json()["secret"]
    r = client.post("/auth/2fa/enable", json={"code": totp._code(secret, totp.current_step())}, headers=h)
    assert r.status_code == 200, r.text
    return secret, r.json()["backup_codes"]


def test_totp_rfc6238_vector():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", now=59, last_step=1) is None  # fără refolosire
    assert totp.verify(secret, "000000", now=59) is None


def test_change_password(client, db):
    u = make_user(db, "pw@x.md")
    h = auth_headers(u)
    assert client.post("/auth/password", json={"current_password": "greșită", "new_password": "noua-parola-1"}, headers=h).status_code == 400
    assert client.post("/auth/password", json={"current_password": "parola-test-1", "new_password": "scurt"}, headers=h).status_code == 422
    assert client.post("/auth/password", json={"current_password": "parola-test-1", "new_password": "noua-parola-1"}, headers=h).status_code == 204
    assert _login(client, "pw@x.md").status_code == 401
    assert _login(client, "pw@x.md", "noua-parola-1").status_code == 200
    assert client.post("/auth/password", json={"current_password": "x"}).status_code in (401, 403)


def test_setup_stores_encrypted_secret_and_not_active_until_confirmed(client, db):
    u = make_user(db, "s@x.md")
    h = auth_headers(u)
    out = client.post("/auth/2fa/setup", headers=h).json()
    assert out["otpauth_uri"].startswith("otpauth://totp/")
    db.refresh(u)
    assert u.totp_secret_enc and u.totp_secret_enc != out["secret"] and decrypt(u.totp_secret_enc) == out["secret"]
    assert client.get("/auth/2fa", headers=h).json()["enabled"] is False
    assert _login(client, "s@x.md").json()["access_token"]  # încă fără 2FA
    assert client.post("/auth/2fa/enable", json={"code": "000000"}, headers=h).status_code == 400


def test_login_with_2fa_and_backup_codes(client, db):
    u = make_user(db, "t@x.md")
    secret, backups = _enable_2fa(client, u)
    assert len(backups) == 8
    r = _login(client, "t@x.md").json()
    assert r["requires_2fa"] and r["challenge_token"] and r["access_token"] is None
    ch = r["challenge_token"]
    # jetonul de provocare nu dă acces la API
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {ch}"}).status_code == 401
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": "111111"}).status_code == 401
    # codul TOTP al pasului curent a fost deja folosit la activare → pasul următor e acceptat
    code = totp._code(secret, totp.current_step() + 1)
    ok = client.post("/auth/login/2fa", json={"challenge_token": ch, "code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": code}).status_code == 401  # refolosire
    # cod de rezervă: o singură dată
    ch = _login(client, "t@x.md").json()["challenge_token"]
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": backups[0]}).status_code == 200
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": backups[0]}).status_code == 401
    assert client.get("/auth/2fa", headers=auth_headers(u)).json()["backup_codes_left"] == 7


def test_login_2fa_lockout(client, db):
    u = make_user(db, "l@x.md")
    secret, _ = _enable_2fa(client, u)
    ch = _login(client, "l@x.md").json()["challenge_token"]
    for _ in range(5):
        assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": "000000"}).status_code == 401
    good = totp._code(secret, totp.current_step() + 1)
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": good}).status_code == 429


def test_disable_and_regenerate_need_password_and_code(client, db):
    u = make_user(db, "d@x.md")
    secret, backups = _enable_2fa(client, u)
    h = auth_headers(u)
    nxt = lambda n: totp._code(secret, totp.current_step() + n)  # noqa: E731
    assert client.post("/auth/2fa/disable", json={"password": "alta", "code": nxt(1)}, headers=h).status_code == 400
    assert client.post("/auth/2fa/disable", json={"password": "parola-test-1", "code": "000000"}, headers=h).status_code == 400
    new = client.post("/auth/2fa/backup-codes", json={"password": "parola-test-1", "code": nxt(1)}, headers=h)
    assert new.status_code == 200 and set(new.json()["backup_codes"]).isdisjoint(backups)
    assert client.post("/auth/2fa/disable", json={"password": "parola-test-1", "code": new.json()["backup_codes"][0]}, headers=h).status_code == 204
    assert client.get("/auth/2fa", headers=h).json() == {"enabled": False, "backup_codes_left": 0}
    assert _login(client, "d@x.md").json()["access_token"]


def test_rls_restricts_to_current_organization(db, connection):
    """Cu un rol fără drepturi de superutilizator, politica `org_isolation` taie rândurile altei organizații."""
    owner = make_user(db, "rls@x.md")
    a, b = make_org(db, owner, "Org A"), make_org(db, owner, "Org B")
    from app.audit.service import write_audit

    write_audit(db, action="create", entity="t", organization_id=a.id)
    write_audit(db, action="create", entity="t", organization_id=b.id)
    db.flush()
    connection.execute(text("DROP ROLE IF EXISTS rls_probe"))
    connection.execute(text("CREATE ROLE rls_probe NOSUPERUSER NOBYPASSRLS"))
    connection.execute(text("GRANT USAGE ON SCHEMA public TO rls_probe"))
    connection.execute(text("GRANT SELECT, INSERT ON audit_log TO rls_probe"))
    connection.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO rls_probe"))
    connection.execute(text("SET LOCAL ROLE rls_probe"))
    try:
        count = lambda: connection.execute(text("SELECT count(*) FROM audit_log WHERE entity = 't'")).scalar()  # noqa: E731
        connection.execute(text("SELECT set_config('app.org_id', '', true)"))
        assert count() == 2  # fără context (login, worker) nu se restrânge
        connection.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(a.id)})
        assert count() == 1
        rows = connection.execute(text("SELECT organization_id FROM audit_log WHERE entity = 't'")).all()
        assert [str(r[0]) for r in rows] == [str(a.id)]
        with pytest.raises(Exception, match="row-level security"), connection.begin_nested():
            connection.execute(text("INSERT INTO audit_log (organization_id, action, entity) VALUES (:o, 'x', 't')"), {"o": str(b.id)})
    finally:
        connection.execute(text("RESET ROLE"))


def test_rls_enabled_on_organization_tables(connection):
    names = {
        r[0]
        for r in connection.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' "
                "WHERE c.relkind IN ('r','p') AND NOT c.relispartition AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        )
    }
    assert {"entry_lines", "documents", "audit_log", "tasks", "accounts", "grants", "onec_import_runs", "opening_balances"} <= names
    every = {
        r[0]
        for r in connection.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped "
                "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r','p') AND NOT c.relispartition"
            )
        )
    }
    assert every - names == set()  # niciun tabel cu organization_id fără RLS


def test_password_change_needs_second_factor_when_enabled(client, db):
    u = make_user(db, "p2@x.md")
    secret, _ = _enable_2fa(client, u)
    h = auth_headers(u)
    body = {"current_password": "parola-test-1", "new_password": "noua-parola-1"}
    assert client.post("/auth/password", json=body, headers=h).status_code == 400
    code = totp._code(secret, totp.current_step() + 1)
    assert client.post("/auth/password", json={**body, "code": code}, headers=h).status_code == 204


def test_login_password_lockout(client, db):
    from app.auth.twofa import MAX_FAILURES

    u = make_user(db, "lock@x.md")
    for _ in range(MAX_FAILURES):
        assert _login(client, "lock@x.md", "gresita-1234").status_code == 401
    # blocat: nici parola corectă nu mai trece
    assert _login(client, "lock@x.md").status_code == 429
    db.refresh(u)
    from datetime import datetime, timedelta

    u.password_locked_until = datetime.now() - timedelta(seconds=1)
    db.flush()
    assert _login(client, "lock@x.md").status_code == 200


def test_login_failure_counter_resets_on_success(client, db):
    from app.auth.twofa import MAX_FAILURES

    make_user(db, "reset@x.md")
    for _ in range(MAX_FAILURES - 1):
        assert _login(client, "reset@x.md", "gresita-1234").status_code == 401
    assert _login(client, "reset@x.md").status_code == 200
    for _ in range(MAX_FAILURES - 1):
        assert _login(client, "reset@x.md", "gresita-1234").status_code == 401
    assert _login(client, "reset@x.md").status_code == 200


def test_password_change_lockout(client, db):
    from app.auth.twofa import MAX_FAILURES

    u = make_user(db, "pw@x.md")
    h = auth_headers(u)
    for _ in range(MAX_FAILURES):
        r = client.post("/auth/password", json={"current_password": "gresita-1234", "new_password": "noua-parola-1"}, headers=h)
        assert r.status_code == 400
    r = client.post("/auth/password", json={"current_password": "parola-test-1", "new_password": "noua-parola-1"}, headers=h)
    assert r.status_code == 429


def test_2fa_backup_codes_share_lockout(client, db):
    from app.auth.twofa import MAX_FAILURES

    u = make_user(db, "bk@x.md")
    _, backups = _enable_2fa(client, u)
    ch = _login(client, "bk@x.md").json()["challenge_token"]
    for _ in range(MAX_FAILURES):
        assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": "abcde-12345"}).status_code == 401
    # blocat: nici un cod de rezervă valid nu trece
    assert client.post("/auth/login/2fa", json={"challenge_token": ch, "code": backups[0]}).status_code == 429


def test_2fa_enable_wrong_codes_lock(client, db):
    from app.auth.twofa import MAX_FAILURES

    u = make_user(db, "en@x.md")
    h = auth_headers(u)
    secret = client.post("/auth/2fa/setup", headers=h).json()["secret"]
    for _ in range(MAX_FAILURES):
        assert client.post("/auth/2fa/enable", json={"code": "000000"}, headers=h).status_code == 400
    good = totp._code(secret, totp.current_step())
    assert client.post("/auth/2fa/enable", json={"code": good}, headers=h).status_code == 429


def test_removing_from_last_organization_deactivates_account(client, db):
    admin = make_user(db, "adm@x.md")
    org_a, org_b = make_org(db, admin, "A", UserRole.admin), make_org(db, admin, "B", UserRole.admin)
    guest = make_user(db, "guest@x.md")
    ha, hb = auth_headers(admin), auth_headers(admin)
    ma = client.post(f"/organizations/{org_a.id}/members", json={"email": "guest@x.md", "role": "accountant"}, headers=ha).json()
    mb = client.post(f"/organizations/{org_b.id}/members", json={"email": "guest@x.md", "role": "accountant"}, headers=hb).json()
    assert client.delete(f"/organizations/{org_a.id}/members/{ma['id']}", headers=ha).status_code == 204
    assert _login(client, "guest@x.md").status_code == 200  # încă membru în B
    assert client.delete(f"/organizations/{org_b.id}/members/{mb['id']}", headers=hb).status_code == 204
    assert _login(client, "guest@x.md").status_code == 401
    assert client.get("/auth/me", headers=auth_headers(guest)).status_code == 401
    # readăugat: contul revine activ
    client.post(f"/organizations/{org_a.id}/members", json={"email": "guest@x.md", "role": "accountant"}, headers=ha)
    assert _login(client, "guest@x.md").status_code == 200


def _probe_role(connection):
    connection.execute(text("DROP ROLE IF EXISTS rls_probe"))
    connection.execute(text("CREATE ROLE rls_probe NOSUPERUSER NOBYPASSRLS"))
    connection.execute(text("GRANT USAGE ON SCHEMA public TO rls_probe"))
    connection.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rls_probe"))
    connection.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO rls_probe"))
    connection.execute(text("SET LOCAL ROLE rls_probe"))


def test_rls_isolates_even_without_app_filters(db, connection):
    """Interogări FĂRĂ filtru pe organizație (ca după o greșeală în rută) nu văd altă organizație, pe mai multe tabele."""
    from sqlalchemy import select

    from app.core.rls import set_rls_context
    from app.models import Account, Organization

    owner = make_user(db, "iso@x.md")
    a, b = make_org(db, owner, "Org A"), make_org(db, owner, "Org B")
    for org in (a, b):
        connection.execute(text("INSERT INTO accounts (organization_id, code, name, account_kind) VALUES (:o, '521', 'x', 'active_passive')"), {"o": org.id})
        connection.execute(text("INSERT INTO ai_conversations (organization_id, user_id, title) VALUES (:o, :u, 't')"), {"o": org.id, "u": owner.id})
    db.flush()
    _probe_role(connection)
    try:
        s = Session(bind=connection, join_transaction_mode="create_savepoint")
        set_rls_context(s, a.id, owner.id)
        assert {x.organization_id for x in s.scalars(select(Account))} == {a.id}  # fără WHERE organization_id
        assert {r[0] for r in s.execute(text("SELECT organization_id FROM ai_conversations"))} == {a.id}  # tabelă adăugată târziu
        with pytest.raises(Exception, match="row-level security"), s.begin_nested():
            s.execute(text("INSERT INTO ai_conversations (organization_id, user_id) VALUES (:o, :u)"), {"o": b.id, "u": owner.id})
        with pytest.raises(Exception, match="row-level security"), s.begin_nested():
            s.execute(text("INSERT INTO accounts (organization_id, code, name, account_kind) VALUES (:o, '1', 'y', 'active_passive')"), {"o": b.id})
        assert s.execute(text("UPDATE accounts SET name = 'hack' WHERE organization_id = :b"), {"b": b.id}).rowcount == 0
        s.close()
    finally:
        connection.execute(text("RESET ROLE"))


def test_removal_keeps_account_active_under_rls_role(client, db, connection):
    """Sub un rol fără ocolirea RLS, numărarea organizațiilor rămase nu trebuie să vadă doar organizația curentă."""
    admin = make_user(db, "adm2@x.md")
    org_a, org_b = make_org(db, admin, "A", UserRole.admin), make_org(db, admin, "B", UserRole.admin)
    guest = make_user(db, "guest2@x.md")
    h = auth_headers(admin)
    ma = client.post(f"/organizations/{org_a.id}/members", json={"email": "guest2@x.md", "role": "accountant"}, headers=h).json()
    client.post(f"/organizations/{org_b.id}/members", json={"email": "guest2@x.md", "role": "accountant"}, headers=h)
    db.flush()
    # în producție fiecare cerere are tranzacția ei; aici contextul cererilor anterioare rămâne în tranzacția de test
    connection.execute(text("SELECT set_config('app.org_id', '', true), set_config('app.user_id', '', true)"))
    _probe_role(connection)
    try:
        r = client.delete(f"/organizations/{org_a.id}/members/{ma['id']}", headers=h)
        assert r.status_code == 204, r.text
    finally:
        connection.execute(text("RESET ROLE"))
    db.refresh(guest)
    assert guest.is_active is not False


def test_reactivation_only_for_auto_deactivated(client, db):
    admin = make_user(db, "adm3@x.md")
    org = make_org(db, admin, "A", UserRole.admin)
    blocked = make_user(db, "blk@x.md")
    blocked.is_active = False
    db.flush()
    r = client.post(f"/organizations/{org.id}/members", json={"email": "blk@x.md", "role": "accountant"}, headers=auth_headers(admin))
    assert r.status_code == 409
