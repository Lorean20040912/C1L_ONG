"""Pontajul (zile lucrate) și indemnizațiile de boală pe contract și lună (modulul salarii).

Revision ID: fix_0003
Revises: fix_0002
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "fix_0003"
down_revision = "fix_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_inputs",
        sa.Column("id", pg.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("contract_id", pg.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("worked_days", sa.Integer(), nullable=True),
        sa.Column("sick_benefit", sa.Numeric(15, 2), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "year", "month", name="uq_payroll_inputs_contract_month"),
        sa.CheckConstraint("worked_days IS NULL OR worked_days >= 0", name="ck_payroll_inputs_days"),
        sa.CheckConstraint("sick_benefit >= 0", name="ck_payroll_inputs_sick"),
    )


def downgrade() -> None:
    op.drop_table("payroll_inputs")
