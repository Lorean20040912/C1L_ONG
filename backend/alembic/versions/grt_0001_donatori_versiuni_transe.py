"""Granturi avansat: donatori, versiuni de buget, tranșe, repartizări.

- tabelele `donors`, `grant_donors`, `budget_versions`, `grant_tranches`, `allocations`
  (database/schema.dbml) și cheia străină `budget_lines.budget_version_id`;
- regula distribuirii stocurilor nu mai repetă linia de buget (cheltuiala a numărat-o
  deja la achiziție: Dt 211 — Kt 521 poartă linia, Dt 716 — Kt 211 nu);
- regula repartizării cheltuielilor comune pe granturi (pasul „Repartizarea pe granturi”).

Revision ID: grt_0001
Revises: 0005
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "grt_0001"
down_revision = "0005"
branch_labels = None
depends_on = None

REASON = "Granturi avansat: repartizarea cheltuielilor comune pe granturi"


def upgrade() -> None:
    op.create_table(
        "donors",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "grant_donors",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("donor_id", sa.UUID(), nullable=False),
        sa.Column("share_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.ForeignKeyConstraint(["grant_id"], ["grants.id"]),
        sa.ForeignKeyConstraint(["donor_id"], ["donors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", "donor_id"),
    )
    op.create_table(
        "budget_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("approved_document_id", sa.UUID(), nullable=True),
        sa.Column("import_id", sa.UUID(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.ForeignKeyConstraint(["grant_id"], ["grants.id"]),
        sa.ForeignKeyConstraint(["approved_document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", "version"),
    )
    op.create_foreign_key(
        "budget_lines_budget_version_id_fkey", "budget_lines", "budget_versions", ["budget_version_id"], ["id"]
    )
    op.create_table(
        "grant_tranches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("donor_id", sa.UUID(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'planned'"), nullable=True),
        sa.Column("received_document_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["grant_id"], ["grants.id"]),
        sa.ForeignKeyConstraint(["donor_id"], ["donors.id"]),
        sa.ForeignKeyConstraint(["received_document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "allocations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("budget_line_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("amount_mdl", sa.Numeric(15, 2), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("suggested_by_ai", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["budget_line_id"], ["budget_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "UPDATE posting_rules SET analytics = COALESCE(analytics, '{}'::jsonb) || '{\"budget_line\": \"drop\"}'::jsonb "
        "WHERE organization_id IS NULL AND document_type = 'stock_distribution' AND operation = 'expense'"
    )
    # Dt 716 — Kt <contul cheltuielii comune ales la pas>; Kt 717 doar dacă pasul nu indică alt cont
    op.execute(
        sa.text(
            "INSERT INTO posting_rules (id, document_type, operation, conditions, debit_account, credit_account, "
            "analytics, source_ref, valid_from, version, change_reason) VALUES "
            "(:id, 'month_close.allocation', 'cost_allocation', NULL, '716', '717', CAST(:analytics AS jsonb), "
            "'MFG; docs/11 §2.8', :valid_from, 1, :reason)"
        ).bindparams(
            id=uuid.uuid4(),
            analytics=json.dumps({"required": ["grant", "budget_line"], "activity_type": "special_purpose"}),
            valid_from=date(2015, 1, 1),
            reason=REASON,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
    op.execute(
        "UPDATE posting_rules SET analytics = NULLIF(analytics - 'budget_line', '{}'::jsonb) "
        "WHERE organization_id IS NULL AND document_type = 'stock_distribution' AND operation = 'expense'"
    )
    op.drop_table("allocations")
    op.drop_table("grant_tranches")
    op.drop_constraint("budget_lines_budget_version_id_fkey", "budget_lines", type_="foreignkey")
    op.drop_table("budget_versions")
    op.drop_table("grant_donors")
    op.drop_table("donors")
