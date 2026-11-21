"""Conexiunea la PostgreSQL și baza modelelor SQLAlchemy."""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(_settings.app_database_url or _settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """O sesiune pe cerere; tranzacția o confirmă endpoint-ul (commit explicit)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def role_bypasses_rls(conn) -> bool:
    """Adevărat dacă rolul conexiunii este superutilizator sau are BYPASSRLS (politicile RLS nu s-ar aplica)."""
    return bool(
        conn.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar()
    )


def assert_rls_role() -> None:
    """Cu `REQUIRE_RLS_ROLE=true`, refuză pornirea dacă aplicația rulează cu un rol care ocolește RLS."""
    if not get_settings().require_rls_role:
        return
    with engine.connect() as conn:
        if role_bypasses_rls(conn):
            raise RuntimeError(
                "Rolul bazei de date este superuser/BYPASSRLS: RLS nu se aplică. Setați APP_DATABASE_URL pe un rol obișnuit."
            )
