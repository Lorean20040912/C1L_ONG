"""Versiuni de buget: stare (proiect / aprobat), aprobare cu utilizator și dată, notă.

Revision ID: fix2_0001
Revises: mrg_0008
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "fix2_0001"
down_revision = "mrg_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_versions", sa.Column("status", sa.Text(), server_default="approved", nullable=False))
    op.add_column("budget_versions", sa.Column("approved_by", pg.UUID(), nullable=True))
    op.add_column("budget_versions", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("budget_versions", sa.Column("note", sa.Text(), nullable=True))
    op.create_foreign_key("fk_budget_versions_approved_by", "budget_versions", "users", ["approved_by"], ["id"])
    op.create_check_constraint("ck_budget_versions_status", "budget_versions", "status IN ('draft', 'approved')")


def downgrade() -> None:
    op.drop_constraint("ck_budget_versions_status", "budget_versions", type_="check")
    op.drop_constraint("fk_budget_versions_approved_by", "budget_versions", type_="foreignkey")
    for col in ("note", "approved_at", "approved_by", "status"):
        op.drop_column("budget_versions", col)
