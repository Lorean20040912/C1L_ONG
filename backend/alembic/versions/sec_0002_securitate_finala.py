"""Securitate: blocarea parolei, schimbarea parolei la prima intrare, RLS pe toate tabelele cu organization_id,
rol de aplicație fără drept de ocolire a RLS.

Revision ID: sec_0002
Revises: mrg_0007
Create Date: 2026-11-21
"""

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings
from app.core.rls import disable_rls_sql, enable_rls_sql

revision = "sec_0002"
down_revision = "mrg_0007"
branch_labels = None
depends_on = None

# tabele create după sec_0001, rămase fără RLS
LATE_TABLES = ("ai_conversations", "efactura_messages", "onec_id_map", "onec_import_runs", "opening_balances")


def _missing_rls(conn) -> list[str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT c.relname FROM pg_class c
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped
            WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') AND NOT c.relispartition
              AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
            ORDER BY c.relname
            """
        )
    )
    return [r[0] for r in rows]


def _app_role() -> None:
    """Rol de aplicație fără superuser/BYPASSRLS (doar dacă APP_DB_USER e setat)."""
    settings = get_settings()
    user, password = settings.app_db_user, settings.app_db_password
    if not user:
        return
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", user):
        raise RuntimeError("APP_DB_USER invalid")
    if not password:
        raise RuntimeError("APP_DB_PASSWORD lipsește")
    # ':' ar fi luat drept parametru de text(); în literalul SQL se scrie cu \\:
    pw = "'" + password.replace("'", "''").replace(":", "\\:") + "'"
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{user}') THEN
                CREATE ROLE "{user}" LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END $$
        """
    )
    op.execute(f'ALTER ROLE "{user}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {pw}')
    op.execute(f'GRANT CONNECT ON DATABASE "{op.get_bind().engine.url.database}" TO "{user}"')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{user}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{user}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{user}"')
    # tabelele create de migrările viitoare (de același proprietar) primesc drepturile automat
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{user}"')
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{user}"')


def upgrade() -> None:
    op.add_column("users", sa.Column("password_failures", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("users", sa.Column("password_locked_until", postgresql.TIMESTAMP(), nullable=True))
    op.add_column("users", sa.Column("deactivated_reason", sa.String(), nullable=True))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    for table in _missing_rls(op.get_bind()):
        for stmt in enable_rls_sql(table):
            op.execute(stmt)
    _app_role()


def downgrade() -> None:
    for table in LATE_TABLES:
        for stmt in disable_rls_sql(table):
            op.execute(stmt)
    for col in ("deactivated_reason", "must_change_password", "password_locked_until", "password_failures"):
        op.drop_column("users", col)
