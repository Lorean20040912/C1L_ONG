"""Stingerea facturilor primite cu plățile către furnizori (`invoice_settlements`).

Revision ID: fixb_0002
Revises: fixb_0001
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.core.rls import disable_rls_sql, enable_rls_sql

revision = "fixb_0002"
down_revision = "fixb_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_settlements",
        sa.Column("id", pg.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_document_id", pg.UUID, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("payment_document_id", pg.UUID, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("created_by", pg.UUID, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("invoice_document_id", "payment_document_id"),
        sa.CheckConstraint("amount > 0", name="ck_invoice_settlements_amount"),
    )
    op.create_index("ix_invoice_settlements_payment", "invoice_settlements", ["payment_document_id"])
    op.create_index("ix_invoice_settlements_invoice", "invoice_settlements", ["invoice_document_id"])
    for stmt in enable_rls_sql("invoice_settlements"):
        op.execute(stmt)
    # ordinele de plată existente cu factură indicată devin stingeri (suma plății, plafonată la suma facturii)
    op.execute(
        """
        INSERT INTO invoice_settlements (organization_id, invoice_document_id, payment_document_id, amount)
        SELECT pd.organization_id, inv.document_id, pd.id, LEAST(pd.total_amount, idoc.total_amount)
        FROM payment_orders po
        JOIN documents pd ON pd.id = po.document_id
        JOIN invoices inv ON inv.id = po.invoice_id
        JOIN documents idoc ON idoc.id = inv.document_id
        WHERE po.direction = 'outgoing' AND pd.total_amount > 0 AND idoc.total_amount > 0
          AND pd.organization_id = idoc.organization_id
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    for stmt in disable_rls_sql("invoice_settlements"):
        op.execute(stmt)
    op.drop_index("ix_invoice_settlements_invoice", table_name="invoice_settlements")
    op.drop_index("ix_invoice_settlements_payment", table_name="invoice_settlements")
    op.drop_table("invoice_settlements")
