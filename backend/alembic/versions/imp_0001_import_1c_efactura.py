"""Import 1C (rulări, corespondența GUID, solduri inițiale) și mesajele e-Factura.

Revision ID: imp_0001
Revises: mrg_0003
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "imp_0001"
down_revision = "mrg_0003"
branch_labels = None
depends_on = None

IMPORT_STATUS = postgresql.ENUM("pending", "running", "done", "failed", name="import_status", create_type=False)


def upgrade() -> None:
    IMPORT_STATUS.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "onec_import_runs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source", sa.String()),
        sa.Column("period_from", sa.Date()),
        sa.Column("period_to", sa.Date()),
        sa.Column("status", IMPORT_STATUS, server_default=sa.text("'pending'")),
        sa.Column("stats", postgresql.JSONB()),
        sa.Column("reconciliation", postgresql.JSONB()),
        sa.Column("started_by", postgresql.UUID(), sa.ForeignKey("users.id")),
        sa.Column("started_at", postgresql.TIMESTAMP()),
        sa.Column("finished_at", postgresql.TIMESTAMP()),
    )
    op.create_table(
        "onec_id_map",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("onec_type", sa.String(), nullable=False),
        sa.Column("onec_guid", postgresql.UUID(), nullable=False),
        sa.Column("local_table", sa.String(), nullable=False),
        sa.Column("local_id", postgresql.UUID(), nullable=False),
        sa.Column("import_run_id", postgresql.UUID(), sa.ForeignKey("onec_import_runs.id")),
        sa.UniqueConstraint("organization_id", "onec_type", "onec_guid"),
    )
    op.create_table(
        "opening_balances",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("account_id", postgresql.UUID(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("debit", sa.Numeric(15, 2), server_default=sa.text("0")),
        sa.Column("credit", sa.Numeric(15, 2), server_default=sa.text("0")),
        sa.Column("subconto", postgresql.JSONB()),
        sa.Column("imported_from_1c", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_index(
        "ix_opening_balances_organization_id_balance_date", "opening_balances", ["organization_id", "balance_date"]
    )
    op.create_table(
        "efactura_messages",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("efactura_id", sa.String(), nullable=False),
        sa.Column("status", sa.String()),
        sa.Column("payload_xml", sa.Text()),
        sa.Column("document_id", postgresql.UUID(), sa.ForeignKey("documents.id")),
        sa.Column("synced_at", postgresql.TIMESTAMP()),
        sa.UniqueConstraint("organization_id", "efactura_id"),
    )


def downgrade() -> None:
    op.drop_table("efactura_messages")
    op.drop_index("ix_opening_balances_organization_id_balance_date", table_name="opening_balances")
    op.drop_table("opening_balances")
    op.drop_table("onec_id_map")
    op.drop_table("onec_import_runs")
    IMPORT_STATUS.drop(op.get_bind(), checkfirst=True)
