"""Regula pasului „Recunoașterea veniturilor” din închiderea lunii (docs/11 §2.2).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

REASON = "Închiderea lunii: venituri din mijloace cu destinație specială"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO posting_rules (id, document_type, operation, conditions, debit_account, credit_account, "
            "analytics, source_ref, valid_from, version, change_reason) VALUES "
            "(:id, 'month_close.income', 'income_recognition', NULL, '537', '616', CAST(:analytics AS jsonb), "
            "'IM188; ART sit.2', :valid_from, 1, :reason)"
        ).bindparams(
            id=uuid.uuid4(),
            analytics=json.dumps({"required": ["grant"], "budget_line": "drop", "activity_type": "special_purpose"}),
            valid_from=date(2015, 1, 1),
            reason=REASON,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
