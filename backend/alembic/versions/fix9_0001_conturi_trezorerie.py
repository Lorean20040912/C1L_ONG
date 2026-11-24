"""Conturile de casă și de valută lipsă din planurile de conturi create fără șablon (demo).

Revision ID: fix9_0001
Revises: fix7_0001
Create Date: 2026-11-24
"""

from alembic import op

revision = "fix9_0001"
down_revision = "fix7_0001"
branch_labels = None
depends_on = None

NEW = (("241", "Casa"), ("243", "Conturi curente în valută străină"))


def upgrade() -> None:
    for code, name in NEW:
        op.execute(
            f"""
            INSERT INTO accounts (organization_id, code, name, account_kind)
            SELECT a.organization_id, '{code}', '{name}', 'active'
            FROM accounts a
            WHERE a.code = '242'
              AND NOT EXISTS (SELECT 1 FROM accounts x WHERE x.organization_id = a.organization_id AND x.code = '{code}')
            """
        )


def downgrade() -> None:
    for code, _ in NEW:
        op.execute(
            f"DELETE FROM accounts a WHERE a.code = '{code}' AND NOT EXISTS (SELECT 1 FROM entry_lines e WHERE e.debit_account_id = a.id OR e.credit_account_id = a.id)"
        )
