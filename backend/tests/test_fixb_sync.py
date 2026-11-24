"""Sincronizarea automată a surselor de documente: folder pe server, Drive (cu cheie opțională), deduplicare, stare."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.documents.models import Document
from app.fix6.models import DocumentSource, ScannedFile
from app.fix6.sync import SyncError, due_sources, sync_source
from tests.conftest import auth_headers, make_org, make_user

PDF_A = b"%PDF-1.4 fisier A"
PDF_B = b"%PDF-1.4 fisier B"


@pytest.fixture
def env(db, tmp_path, monkeypatch):
    user = make_user(db, "sync@test.md")
    org = make_org(db, user, "AO Sincronizare")
    root = tmp_path / "scanari"
    (root / "org").mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "document_sync_root", str(root))
    return user, org, root, auth_headers(user), f"/organizations/{org.id}"


def new_source(client, base, h, **kw):
    body = {"kind": "server_folder", "name": "Scanări server", "location": "/x", **kw}
    r = client.post(f"{base}/document-sources", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_sincronizare_folder_fisiere_noi_si_deduplicare(client, db, env):
    user, org, root, h, base = env
    folder = root / "org"
    (folder / "f1.pdf").write_bytes(PDF_A)
    (folder / "sub").mkdir()
    (folder / "sub" / "f2.pdf").write_bytes(PDF_B)
    (folder / "copie.pdf").write_bytes(PDF_A)  # același conținut ⇒ duplicat pe hash
    (folder / "note.txt").write_text("ignorat")
    src = new_source(client, base, h, location=str(folder))

    r = client.post(f"{base}/document-sources/{src['id']}/sync", headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["last_status"], out["last_found"], out["last_added"], out["last_duplicates"], out["last_failed"]) == ("ok", 3, 2, 1, 0)
    assert out["documents"] == 2 and out["last_sync_at"] and out["last_error"] is None
    scans = client.get(f"{base}/scanned-documents", headers=h).json()
    assert sorted(s["file_name"] for s in scans) == ["copie.pdf", "f2.pdf"] and all(s["source_id"] == src["id"] for s in scans)

    # a doua rulare: nimic nou, tot ce e în folder e duplicat
    (folder / "f3.pdf").write_bytes(b"%PDF-1.4 fisier C")
    out = client.post(f"{base}/document-sources/{src['id']}/sync", headers=h).json()
    assert (out["last_added"], out["last_duplicates"]) == (1, 3) and out["documents"] == 3
    assert db.scalar(select(func.count()).select_from(ScannedFile).where(ScannedFile.organization_id == org.id)) == 3


def test_deduplicare_fata_de_incarcarea_manuala(client, db, env):
    import base64

    user, org, root, h, base = env
    (root / "org" / "a.pdf").write_bytes(PDF_A)
    src = new_source(client, base, h, location=str(root / "org"))
    up = client.post(f"{base}/scanned-documents", headers=h,
                     json={"file_name": "manual.pdf", "mime_type": "application/pdf", "content_base64": base64.b64encode(PDF_A).decode()})  # fmt: skip
    assert up.status_code == 201
    out = client.post(f"{base}/document-sources/{src['id']}/sync", headers=h).json()
    assert (out["last_added"], out["last_duplicates"]) == (0, 1)


def test_erori_vizibile_in_stare(client, db, env, monkeypatch):
    user, org, root, h, base = env
    # în afara rădăcinii permise
    out_src = new_source(client, base, h, location="/etc")
    out = client.post(f"{base}/document-sources/{out_src['id']}/sync", headers=h).json()
    assert out["last_status"] == "error" and "rădăcinii permise" in out["last_error"]
    # folder inexistent
    miss = new_source(client, base, h, name="Lipsă", location=str(root / "nu-exista"))
    assert "nu există" in client.post(f"{base}/document-sources/{miss['id']}/sync", headers=h).json()["last_error"]
    # fără rădăcină configurată
    monkeypatch.setattr(get_settings(), "document_sync_root", None)
    out = client.post(f"{base}/document-sources/{out_src['id']}/sync", headers=h).json()
    assert "DOCUMENT_SYNC_ROOT" in out["last_error"]
    # fișier prea mare / gol: eroare pe fișier, restul se importă
    monkeypatch.setattr(get_settings(), "document_sync_root", str(root))
    (root / "org" / "gol.pdf").write_bytes(b"")
    (root / "org" / "bun.pdf").write_bytes(PDF_B)
    ok = new_source(client, base, h, name="Cu erori", location=str(root / "org"))
    out = client.post(f"{base}/document-sources/{ok['id']}/sync", headers=h).json()
    assert (out["last_status"], out["last_added"], out["last_failed"]) == ("error", 1, 1) and "gol.pdf" in out["last_error"]
    # sursă dezactivată
    client.put(f"{base}/document-sources/{ok['id']}", json={**ok, "is_active": False}, headers=h)
    assert client.post(f"{base}/document-sources/{ok['id']}/sync", headers=h).status_code == 422


def test_agent_local_nu_se_scaneaza(client, db, env):
    user, org, root, h, base = env
    src = new_source(client, base, h, kind="local_agent", location="C:\\Scanări")
    out = client.post(f"{base}/document-sources/{src['id']}/sync", headers=h).json()
    assert out["last_status"] == "skipped" and "agent" in out["last_error"]


def test_drive_fara_cheie_si_cu_cheie(client, db, env, monkeypatch):
    user, org, root, h, base = env
    link = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQ"
    src = new_source(client, base, h, kind="google_drive", location=link)
    monkeypatch.setattr(get_settings(), "google_api_key", None)
    out = client.post(f"{base}/document-sources/{src['id']}/sync", headers=h).json()
    assert out["last_status"] == "error" and "GOOGLE_API_KEY" in out["last_error"]

    monkeypatch.setattr(get_settings(), "google_api_key", "cheie-de-test")
    calls = []

    def fake(url: str) -> bytes:
        calls.append(url)
        if "alt=media" in url:
            return PDF_A if "ID1" in url else PDF_B
        assert "1AbCdEfGhIjKlMnOpQ" in url and "key=cheie-de-test" in url
        return json.dumps({"files": [
            {"id": "ID1", "name": "factura.pdf", "mimeType": "application/pdf", "size": "17"},
            {"id": "ID2", "name": "bon.pdf", "mimeType": "application/pdf"},
            {"id": "ID3", "name": "doc.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ]}).encode()  # fmt: skip

    res = sync_source(db, __import__("uuid").UUID(src["id"]), fetch=fake)
    assert (res.status, res.found, res.added) == ("ok", 2, 2)
    assert db.scalar(select(func.count()).select_from(ScannedFile).where(ScannedFile.organization_id == org.id)) == 2


def test_scadente_dupa_interval(client, db, env):
    user, org, root, h, base = env
    auto = new_source(client, base, h, name="Auto", location=str(root / "org"), sync_interval_minutes=30)
    new_source(client, base, h, name="Manual", location=str(root / "org"), sync_interval_minutes=0)
    new_source(client, base, h, name="Agent", kind="local_agent", location="C:\\x")
    ids = set(due_sources(db))
    assert {s.name for s in db.scalars(select(DocumentSource).where(DocumentSource.id.in_(ids)))} == {"Auto"}
    client.post(f"{base}/document-sources/{auto['id']}/sync", headers=h)
    assert not due_sources(db)  # tocmai sincronizată
    src = db.get(DocumentSource, auto["id"])
    src.last_sync_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.flush()
    assert due_sources(db) == [src.id]


def test_sincronizarea_cere_administrator(client, db, env):
    user, org, root, h, base = env
    src = new_source(client, base, h, location=str(root / "org"))
    other = make_user(db, "alt@test.md")
    assert client.post(f"{base}/document-sources/{src['id']}/sync", headers=auth_headers(other)).status_code in (403, 404)
    with pytest.raises(SyncError):
        sync_source(db, __import__("uuid").uuid4())


def test_programarea_job_ului_nu_dubleaza_lantul(monkeypatch):
    import rq

    import app.worker as worker
    from app.fix6 import sync

    class FakeRedis:
        def __init__(self):
            self.keys = {}

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.keys:
                return None
            self.keys[key] = value
            return True

    jobs = []

    class FakeQueue:
        def __init__(self, name, connection=None):
            pass

        def enqueue(self, fn, *a, **k):
            jobs.append(("acum", fn.__name__))

        def enqueue_in(self, delta, fn, *a, **k):
            jobs.append((delta, fn.__name__))

    fake = FakeRedis()
    monkeypatch.setattr(worker, "connection", lambda: fake)
    monkeypatch.setattr(rq, "Queue", FakeQueue)
    monkeypatch.setattr(get_settings(), "document_sync_tick_minutes", 15)
    assert sync.schedule_next(first=True) is True  # prima pornire: rulare imediată
    assert sync.schedule_next(first=True) is False  # a doua pornire nu dublează lanțul
    assert sync.schedule_next() is True  # reprogramare după o rulare
    assert jobs == [("acum", "run_due_syncs"), (timedelta(minutes=15), "run_due_syncs")]
    monkeypatch.setattr(get_settings(), "document_sync_tick_minutes", 0)
    assert sync.schedule_next(first=True) is False  # sincronizarea automată oprită
