from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401 — înregistrează toate tabelele în metadata
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    # partițiile anuale ale entry_lines nu sunt modele separate
    if type_ == "table" and reflected and name.startswith("entry_lines_"):
        return False
    # PostgreSQL dublează cheile străine spre tabela partiționată pentru fiecare partiție
    if type_ == "foreign_key_constraint" and reflected and obj.referred_table.name.startswith("entry_lines_"):
        return False
    return True


def database_url() -> str:
    # testele pot transmite o altă bază prin config.attributes
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
