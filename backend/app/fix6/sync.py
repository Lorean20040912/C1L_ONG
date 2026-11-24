"""Sincronizarea surselor de documente: scanare periodică a unui folder / Drive și intrarea fișierelor noi în `scanned_files`.

Conectorii sunt abstracți (`SourceConnector`): folder pe server (în rădăcina permisă din `DOCUMENT_SYNC_ROOT`) și
Google Drive (folder partajat prin link, cu `GOOGLE_API_KEY` opțională din mediu). Sursa „folder local prin agent”
se alimentează de agent (încărcare prin API), deci nu se scanează de pe server. Deduplicarea se face pe hash
(SHA-256 al conținutului, per organizație), la fel ca la încărcarea manuală.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.core.config import get_settings
from app.core.enums import DocumentStatus, DocumentType
from app.documents.models import Document
from app.fix6.models import DocumentSource, ScannedFile

MAX_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_RUN = 200
EXT_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MIME_OK = set(EXT_MIME.values())
DRIVE_FOLDER_RE = re.compile(r"/folders/([\w-]{10,})")
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
STALE_RUNNING = timedelta(minutes=30)


class SyncError(Exception):
    """Eroare de configurare sau de acces la sursă (mesaj în română, afișat în ecran)."""


@dataclass
class RemoteFile:
    name: str
    mime: str | None
    size: int | None
    read: Callable[[], bytes]


class SourceConnector:
    def list_files(self) -> Iterator[RemoteFile]:  # pragma: no cover - interfață
        raise NotImplementedError


class ServerFolderConnector(SourceConnector):
    """Folder de pe server; calea trebuie să fie în interiorul `DOCUMENT_SYNC_ROOT`."""

    def __init__(self, location: str, root: str | None):
        if not root:
            raise SyncError("Folderele de pe server nu se sincronizează: administratorul serverului trebuie să seteze DOCUMENT_SYNC_ROOT")
        self.root = Path(root).resolve()
        self.path = Path(location).resolve()
        if self.path != self.root and self.root not in self.path.parents:
            raise SyncError("Folderul se află în afara rădăcinii permise pentru sincronizare (DOCUMENT_SYNC_ROOT)")
        if not self.path.is_dir():
            raise SyncError("Folderul nu există pe server sau nu este accesibil")

    def list_files(self) -> Iterator[RemoteFile]:
        for p in sorted(self.path.rglob("*")):
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXT_MIME:
                yield RemoteFile(name=str(p.relative_to(self.path)), mime=EXT_MIME[p.suffix.lower()], size=p.stat().st_size, read=p.read_bytes)


Fetch = Callable[[str], bytes]


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "contahub-sync"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - doar https către Google
            return resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SyncError("Google Drive a refuzat accesul: folderul trebuie partajat „oricine are linkul” iar cheia API trebuie să aibă Drive API activat") from None
        if exc.code == 404:
            raise SyncError("Folderul Google Drive nu a fost găsit; verificați linkul") from None
        raise SyncError(f"Google Drive a răspuns cu eroarea {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SyncError("Google Drive nu poate fi contactat de pe server") from None


class GoogleDriveConnector(SourceConnector):
    """Folder Google Drive partajat prin link public, citit prin API cu cheie (opțională, din mediu)."""

    def __init__(self, location: str, api_key: str | None, fetch: Fetch = _http_get):
        if not api_key:
            raise SyncError("Google Drive nu este configurat: lipsește GOOGLE_API_KEY pe server; încărcați scanurile manual sau folosiți un folder pe server")
        m = DRIVE_FOLDER_RE.search(location)
        if not m:
            raise SyncError("Linkul nu este al unui folder Google Drive")
        self.folder_id, self.key, self.fetch = m.group(1), api_key, fetch

    def list_files(self) -> Iterator[RemoteFile]:
        token = None
        while True:
            params = {
                "q": f"'{self.folder_id}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,size)",
                "pageSize": "200",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "key": self.key,
            }
            if token:
                params["pageToken"] = token
            try:
                data = json.loads(self.fetch(f"{DRIVE_API}?{urllib.parse.urlencode(params)}"))
            except ValueError:
                raise SyncError("Răspuns neașteptat de la Google Drive") from None
            for f in data.get("files", []):
                if f.get("mimeType") not in MIME_OK:
                    continue
                url = f"{DRIVE_API}/{f['id']}?{urllib.parse.urlencode({'alt': 'media', 'supportsAllDrives': 'true', 'key': self.key})}"
                yield RemoteFile(name=f["name"], mime=f["mimeType"], size=int(f["size"]) if f.get("size") else None,
                                 read=lambda u=url: self.fetch(u))  # fmt: skip
            token = data.get("nextPageToken")
            if not token:
                return


def connector_for(source: DocumentSource, fetch: Fetch | None = None) -> SourceConnector | None:
    """Conectorul sursei; `None` pentru sursele care se alimentează din afară (agentul local)."""
    cfg = get_settings()
    if source.kind == "server_folder":
        return ServerFolderConnector(source.location, cfg.document_sync_root)
    if source.kind == "google_drive":
        return GoogleDriveConnector(source.location, cfg.google_api_key, fetch or _http_get)
    return None


@dataclass
class SyncResult:
    status: str = "ok"
    found: int = 0
    added: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _record(source: DocumentSource, res: SyncResult, now: datetime) -> None:
    source.last_sync_at = now
    source.last_status = res.status
    source.last_found, source.last_added = res.found, res.added
    source.last_duplicates, source.last_failed = res.duplicates, res.failed
    source.last_error = "\n".join(res.errors[:10]) or None


def sync_source(db: Session, source_id: uuid.UUID, *, user_id: uuid.UUID | None = None, fetch: Fetch | None = None) -> SyncResult:
    """Scanează sursa și adaugă fișierele noi. Nu ridică erori de sursă: le păstrează în starea sursei."""
    try:
        source = db.scalar(select(DocumentSource).where(DocumentSource.id == source_id).with_for_update(nowait=True))
    except OperationalError:
        db.rollback()
        raise SyncError("Sincronizarea acestei surse rulează deja") from None
    if source is None:
        raise SyncError("Sursa nu a fost găsită")
    now = datetime.now(timezone.utc)
    res = SyncResult()
    try:
        conn = connector_for(source, fetch)
        if conn is None:
            res.status = "skipped"
            res.errors.append("Sursa „folder local” se alimentează prin agent (încărcare automată din calculator); nu se scanează de pe server")
        else:
            _scan(db, source, conn, res, user_id)
    except SyncError as exc:
        res.status = "error"
        res.errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - orice eroare a conectorului rămâne vizibilă în ecran
        res.status = "error"
        res.errors.append(f"Eroare neașteptată la sincronizare: {type(exc).__name__}")
    if res.status == "ok" and res.failed:
        res.status = "error"
    _record(source, res, now)
    write_audit(db, action="sync", entity="document_sources", entity_id=source.id, organization_id=source.organization_id,
                user_id=user_id, new_values={"status": res.status, "added": res.added, "duplicates": res.duplicates, "failed": res.failed})  # fmt: skip
    db.commit()
    return res


def _scan(db: Session, source: DocumentSource, conn: SourceConnector, res: SyncResult, user_id: uuid.UUID | None) -> None:
    for rf in conn.list_files():
        if res.found >= MAX_FILES_PER_RUN:
            res.errors.append(f"S-au procesat primele {MAX_FILES_PER_RUN} fișiere; restul la următoarea sincronizare")
            break
        res.found += 1
        try:
            if rf.size is not None and rf.size > MAX_BYTES:
                raise SyncError("depășește 10 MB")
            data = rf.read()
            if not data:
                raise SyncError("fișier gol")
            if len(data) > MAX_BYTES:
                raise SyncError("depășește 10 MB")
        except SyncError as exc:
            res.failed += 1
            res.errors.append(f"{rf.name}: {exc}")
            continue
        except OSError:
            res.failed += 1
            res.errors.append(f"{rf.name}: nu poate fi citit")
            continue
        digest = hashlib.sha256(data).hexdigest()
        if db.scalar(select(Document.id).where(Document.organization_id == source.organization_id, Document.sha256 == digest)):
            res.duplicates += 1
            continue
        doc = Document(organization_id=source.organization_id, type=DocumentType.other, status=DocumentStatus.new,
                       file_name=os.path.basename(rf.name)[:200], mime_type=rf.mime, sha256=digest, uploaded_by=user_id)  # fmt: skip
        db.add(doc)
        db.flush()
        db.add(ScannedFile(document_id=doc.id, organization_id=source.organization_id, source_id=source.id, content=data,
                           note=f"sincronizat din „{source.name}”"))  # fmt: skip
        db.flush()
        res.added += 1


def due_sources(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Sursele active, sincronizabile, a căror ultimă rulare e mai veche decât intervalul propriu."""
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(select(DocumentSource).where(
        DocumentSource.is_active.is_(True), DocumentSource.sync_interval_minutes > 0,
        DocumentSource.kind.in_(("server_folder", "google_drive")),
        or_(DocumentSource.last_status.is_(None), DocumentSource.last_status != "running"))).all()  # fmt: skip
    return [s.id for s in rows if s.last_sync_at is None or s.last_sync_at + timedelta(minutes=s.sync_interval_minutes) <= now]


def run_due_syncs() -> dict:
    """Sarcina RQ: sincronizează sursele scadente, apoi programează următoarea verificare."""
    from app.core.db import SessionLocal  # import târziu: worker-ul nu cere baza la import

    done = failed = 0
    try:
        with SessionLocal() as db:
            for sid in due_sources(db):
                try:
                    res = sync_source(db, sid)
                    done += 1
                    failed += res.status == "error"
                except SyncError:
                    db.rollback()
    finally:
        schedule_next()  # lanțul continuă chiar dacă o rulare a eșuat
    return {"sources": done, "errors": failed}


LOCK_KEY = "contahub:document-sync:scheduled"


def schedule_next(*, first: bool = False) -> bool:
    """Programează următoarea rulare (auto-reprogramare). `first=True` (pornirea worker-ului) pune o rulare imediată
    doar dacă nu există deja un lanț activ (cheie Redis cu expirare), ca pornirile repetate să nu dubleze lanțul."""
    tick = get_settings().document_sync_tick_minutes
    if tick <= 0:
        return False
    from app.worker import QUEUE_NAME, connection
    from rq import Queue

    conn = connection()
    ttl = tick * 60 * 2 + 60
    if first:
        if not conn.set(LOCK_KEY, "1", nx=True, ex=ttl):
            return False
        Queue(QUEUE_NAME, connection=conn).enqueue(run_due_syncs)
        return True
    conn.set(LOCK_KEY, "1", ex=ttl)
    Queue(QUEUE_NAME, connection=conn).enqueue_in(timedelta(minutes=tick), run_due_syncs)
    return True
