"""Documente de bancă și casă, decont de avans, acte de servicii (tabele + reguli de înregistrare).

Revision ID: fix7_0001
Revises: fix6_0001
Create Date: 2026-11-23
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.core.rls import disable_rls_sql, enable_rls_sql

revision = "fix7_0001"
down_revision = "fix6_0001"
branch_labels = None
depends_on = None

TABLES = ("treasury_docs", "treasury_doc_lines")
REASON = "Documente de bancă și casă (fix7)"

# (document_type, operation, Dt, Kt, source_ref)
RULES = [
    ("bank_receipt", "supplier_refund", "242", "521", "ART sit.2 (restituire de la furnizor)"),
    ("bank_receipt", "cash_deposit", "242", "241", "ART sit.1 (depunere numerar în bancă)"),
    ("bank_payment", "cash_withdrawal", "241", "242", "ART sit.1 (ridicare numerar din bancă)"),
    ("bank_payment", "salary", "531", "242", "ART sit.2 (plata salariilor)"),
    ("bank_payment", "social", "533", "242", "ART sit.2 (contribuții sociale / medicale)"),
    ("bank_payment", "budget", "534", "242", "ART sit.2 (plăți către buget)"),
]


def _id():
    return sa.Column("id", pg.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _org():
    return sa.Column("organization_id", pg.UUID, sa.ForeignKey("organizations.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "treasury_docs",
        _id(),
        _org(),
        sa.Column("document_id", pg.UUID, sa.ForeignKey("documents.id"), nullable=False, unique=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("operation", sa.String),
        sa.Column("bank_account_id", pg.UUID, sa.ForeignKey("bank_accounts.id")),
        sa.Column("person_id", pg.UUID, sa.ForeignKey("persons.id")),
        sa.Column("account_id", pg.UUID, sa.ForeignKey("accounts.id")),
        sa.Column("grant_id", pg.UUID, sa.ForeignKey("grants.id")),
        sa.Column("exchange_rate", sa.Numeric(12, 4)),
        sa.Column("purpose", sa.String),
        sa.Column("basis", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind in ('bank_receipt','bank_payment','cash_receipt','cash_payment','advance_report','service_act')",
            name="ck_treasury_docs_kind",
        ),
    )
    op.create_index("ix_treasury_docs_org_kind", "treasury_docs", ["organization_id", "kind"])
    op.create_table(
        "treasury_doc_lines",
        _id(),
        _org(),
        sa.Column("treasury_doc_id", pg.UUID, sa.ForeignKey("treasury_docs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("description", sa.String, nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("line_kind", sa.String, nullable=False, server_default="service"),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("account_id", pg.UUID, sa.ForeignKey("accounts.id")),
        sa.Column("budget_line_id", pg.UUID, sa.ForeignKey("budget_lines.id")),
        sa.Column("cost_item_id", pg.UUID, sa.ForeignKey("cost_items.id")),
    )
    op.create_index("ix_treasury_doc_lines_doc", "treasury_doc_lines", ["treasury_doc_id"])
    for table in TABLES:
        for stmt in enable_rls_sql(table):
            op.execute(stmt)

    insert = sa.text(
        "INSERT INTO posting_rules (id, document_type, operation, conditions, debit_account, credit_account, "
        "analytics, source_ref, valid_from, version, change_reason) VALUES (:id, :dt, :op, NULL, :d, :c, "
        "CAST(:analytics AS jsonb), :src, :vf, 1, :reason)"
    )
    for doc_type, operation, debit, credit, source in RULES:
        op.execute(
            insert.bindparams(
                id=uuid.uuid4(), dt=doc_type, op=operation, d=debit, c=credit, analytics=json.dumps({}),
                src=source, vf=date(2015, 1, 1), reason=REASON,
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
    for table in reversed(TABLES):
        for stmt in disable_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
