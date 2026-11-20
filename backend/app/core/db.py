"""Conexiunea la PostgreSQL și baza modelelor SQLAlchemy."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """O sesiune pe cerere; tranzacția o confirmă endpoint-ul (commit explicit)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
