"""Închiderea lunii (month_close_runs) și execuția bugetului fără dublări.

Regulile „oglindă” (recunoașterea venitului 537/616, formarea fondului 3411,
veniturile anticipate 535) nu mai poartă linia de buget: cheltuiala propriu-zisă
o poartă deja, iar execuția bugetului = suma înregistrărilor pe linia de buget.
Grantul rămâne pe aceste rânduri (venitul 616 se ține pe proiecte).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

MIRROR_OPERATIONS = ("income_recognition", "fixed_asset_fund", "deferred_income")


def upgrade() -> None:
    op.create_table(
        "month_close_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("run_by", sa.UUID(), nullable=True),
        sa.Column("run_at", postgresql.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["run_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "year", "month"),
    )
    op.execute(
        sa.text(
            "UPDATE posting_rules SET analytics = COALESCE(analytics, '{}'::jsonb) || '{\"budget_line\": \"drop\"}'::jsonb "
            "WHERE organization_id IS NULL AND operation IN :ops"
        ).bindparams(sa.bindparam("ops", MIRROR_OPERATIONS, expanding=True))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE posting_rules SET analytics = NULLIF(analytics - 'budget_line', '{}'::jsonb) "
            "WHERE organization_id IS NULL AND operation IN :ops"
        ).bindparams(sa.bindparam("ops", MIRROR_OPERATIONS, expanding=True))
    )
    op.drop_table("month_close_runs")
