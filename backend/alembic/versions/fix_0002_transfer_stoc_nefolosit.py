"""Transferul stocului nefolosit la venituri anticipate (docs/11 §2.3): Dt 537 — Kt 535.

Regula oglindă nu repetă linia de buget (cheltuiala s-a numărat la achiziție).

Revision ID: fix_0002
Revises: fix_0001
Create Date: 2026-11-21
"""

import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "fix_0002"
down_revision = "fix_0001"
branch_labels = None
depends_on = None

REASON = "Transferul stocului nefolosit pe 535 la închiderea proiectului (docs/11 §2.3)"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO posting_rules (id, organization_id, document_type, operation, conditions, debit_account, "
            "credit_account, analytics, source_ref, valid_from, version, change_reason) "
            "VALUES (:id, NULL, 'stock_distribution', 'deferred_transfer', CAST(:cond AS jsonb), '537', '535', "
            "CAST(:an AS jsonb), 'ART sit.2', :vf, 1, :why)"
        ),
        {
            "id": uuid.uuid4(),
            "cond": '{"funding": "special_purpose"}',
            "an": '{"required": ["grant"], "activity_type": "special_purpose", "budget_line": "drop"}',
            "vf": date(2015, 1, 1),
            "why": REASON,
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
