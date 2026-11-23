"""Ecrane complete: evenimente mijloace fixe, ajustări de perioadă, tipuri de calcul, surse de documente, scanuri.

Revision ID: fix6_0001
Revises: fix4_0001
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.core.rls import disable_rls_sql, enable_rls_sql

revision = "fix6_0001"
down_revision = "fix4_0001"
branch_labels = None
depends_on = None

TABLES = ("fixed_asset_events", "period_adjustments", "payroll_calc_types", "document_sources", "scanned_files")


def _id():
    return sa.Column("id", pg.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _org():
    return sa.Column("organization_id", pg.UUID, sa.ForeignKey("organizations.id"), nullable=False)


def _ts(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"))


def upgrade() -> None:
    op.create_table(
        "fixed_asset_events",
        _id(),
        _org(),
        sa.Column("fixed_asset_id", pg.UUID, sa.ForeignKey("fixed_assets.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="posted"),
        sa.Column("reason", sa.Text),
        sa.Column("document_id", pg.UUID, sa.ForeignKey("documents.id")),
        sa.Column("loss_account_id", pg.UUID, sa.ForeignKey("accounts.id")),
        sa.Column("amount", sa.Numeric(15, 2)),
        sa.Column("previous_status", sa.String),
        sa.Column("created_by", pg.UUID, sa.ForeignKey("users.id")),
        _ts(),
        sa.CheckConstraint("kind in ('commissioning','writeoff')", name="ck_fixed_asset_events_kind"),
        sa.CheckConstraint("status in ('posted','cancelled')", name="ck_fixed_asset_events_status"),
    )
    op.create_index("ix_fixed_asset_events_asset", "fixed_asset_events", ["fixed_asset_id"])
    op.create_table(
        "period_adjustments",
        _id(),
        _org(),
        sa.Column("document_id", pg.UUID, sa.ForeignKey("documents.id")),
        sa.Column("reversal_document_id", pg.UUID, sa.ForeignKey("documents.id")),
        sa.Column("adjustment_date", sa.Date, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("debit_account_id", pg.UUID, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("credit_account_id", pg.UUID, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("grant_id", pg.UUID, sa.ForeignKey("grants.id")),
        sa.Column("status", sa.String, nullable=False, server_default="posted"),
        sa.Column("created_by", pg.UUID, sa.ForeignKey("users.id")),
        _ts(),
        sa.CheckConstraint("status in ('posted','cancelled')", name="ck_period_adjustments_status"),
    )
    op.create_table(
        "payroll_calc_types",
        _id(),
        _org(),
        sa.Column("code", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("taxable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("social_base", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("organization_id", "code"),
        sa.CheckConstraint("kind in ('accrual','deduction')", name="ck_payroll_calc_types_kind"),
    )
    op.create_table(
        "document_sources",
        _id(),
        _org(),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("location", sa.String, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        _ts(),
        sa.CheckConstraint("kind in ('google_drive','local_agent','server_folder')", name="ck_document_sources_kind"),
    )
    op.create_table(
        "scanned_files",
        sa.Column("document_id", pg.UUID, sa.ForeignKey("documents.id"), primary_key=True),
        _org(),
        sa.Column("source_id", pg.UUID, sa.ForeignKey("document_sources.id")),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("ai_fields", pg.JSONB),
        _ts("ai_at"),
        sa.Column("note", sa.Text),
    )
    op.execute("ALTER TABLE scanned_files ALTER COLUMN ai_at DROP DEFAULT")
    for table in TABLES:
        for stmt in enable_rls_sql(table):
            op.execute(stmt)


def downgrade() -> None:
    for table in reversed(TABLES):
        for stmt in disable_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
