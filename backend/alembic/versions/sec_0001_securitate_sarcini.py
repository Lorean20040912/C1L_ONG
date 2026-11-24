"""Securitate (2FA, coduri de rezervă, RLS) și sarcini.

Revision ID: sec_0001
Revises: mrg_0003
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import TASK_PRIVATE_CONDITION, disable_rls_sql, enable_rls_sql

revision = "sec_0001"
down_revision = "mrg_0003"
branch_labels = None
depends_on = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")


def _org_tables(conn) -> list[str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped
            WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
            ORDER BY c.relname
            """
        )
    )
    return [r[0] for r in rows]


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("totp_failures", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("users", sa.Column("totp_locked_until", postgresql.TIMESTAMP(), nullable=True))
    op.create_table(
        "user_backup_codes",
        sa.Column("id", postgresql.UUID(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_backup_codes_user_id", "user_backup_codes", ["user_id"])

    op.create_table(
        "task_templates",
        sa.Column("id", postgresql.UUID(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=True),
        sa.Column("feature_code", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("recurrence", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=True),
        sa.Column("action_params", postgresql.JSONB(), nullable=True),
        sa.Column("remind_days_before", sa.Integer(), server_default=sa.text("2"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("created_by_ai", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["feature_code"], ["features.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=True),
        sa.Column("template_id", postgresql.UUID(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(), nullable=False),
        sa.Column("is_private", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("period", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'open'"), nullable=True),
        sa.Column("done_at", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("linked_document_id", postgresql.UUID(), nullable=True),
        sa.Column("calendar_id", postgresql.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["task_templates.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["linked_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["calendar_id"], ["reporting_calendar.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_owner_status_due", "tasks", ["owner_user_id", "status", "due_date"])
    op.create_index("ix_tasks_organization_period", "tasks", ["organization_id", "period"])

    conn = op.get_bind()
    for table in _org_tables(conn):
        for stmt in enable_rls_sql(table):
            op.execute(stmt)
    op.execute(
        f'CREATE POLICY tasks_private ON "tasks" AS RESTRICTIVE USING ({TASK_PRIVATE_CONDITION}) '
        f"WITH CHECK ({TASK_PRIVATE_CONDITION})"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tasks_private ON "tasks"')
    conn = op.get_bind()
    for table in _org_tables(conn):
        for stmt in disable_rls_sql(table):
            op.execute(stmt)
    op.drop_table("tasks")
    op.drop_table("task_templates")
    op.drop_index("ix_user_backup_codes_user_id", table_name="user_backup_codes")
    op.drop_table("user_backup_codes")
    for col in ("totp_locked_until", "totp_failures", "totp_last_step", "totp_enabled"):
        op.drop_column("users", col)
