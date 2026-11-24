"""Testele rulează pe un PostgreSQL real (TEST_DATABASE_URL).

Schema se creează o dată prin migrarea Alembic; fiecare test lucrează într-o
tranzacție care se anulează la final, deci testele nu se influențează.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://contahub:contahub@localhost:5432/contahub_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.auth.models import OrganizationMember, User  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.enums import AccountKind, EntityType, UserRole  # noqa: E402
from app.core.security import create_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, Organization, Workspace  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "heads")
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine):
    conn = engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        outer.rollback()
        conn.close()


@pytest.fixture
def db(connection) -> Iterator[Session]:
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session, connection) -> Iterator[TestClient]:
    """Fiecare cerere are sesiunea ei (ca în producție), pe aceeași conexiune de test:
    un rollback după o eroare anulează doar cererea, nu și datele pregătite de test."""

    def request_session() -> Iterator[Session]:
        db.flush()
        session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            db.expire_all()

    app.dependency_overrides[get_db] = request_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db: Session, email: str, password: str = "parola-test-1") -> User:
    user = User(email=email, full_name=email.split("@")[0], password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def make_org(db: Session, owner: User, name: str, role: UserRole = UserRole.chief_accountant) -> Organization:
    ws = Workspace(name=name, created_by=owner.id, source="empty")
    db.add(ws)
    db.flush()
    org = Organization(
        workspace_id=ws.id,
        name=name,
        idno=str(uuid.uuid4().int)[:13],
        entity_type=EntityType.ngo_association,
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role=role))
    db.flush()
    return org


def make_accounts(db: Session, org: Organization, *codes: str) -> dict[str, Account]:
    accounts = {}
    for code in codes:
        acc = Account(organization_id=org.id, code=code, name=f"Contul {code}", account_kind=AccountKind.active_passive)
        db.add(acc)
        accounts[code] = acc
    db.flush()
    return accounts


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user.id, 'access')}"}
