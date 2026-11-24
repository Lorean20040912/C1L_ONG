"""Modulul de vânzări: facturi emise, stornări, stingerea încasărilor, reguli de înregistrare.

Revision ID: fixa_0001
Revises: fix9_0001
Create Date: 2026-11-24
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.core.rls import disable_rls_sql, enable_rls_sql

revision = "fixa_0001"
down_revision = "fix9_0001"
branch_labels = None
depends_on = None

TABLES = ("sales_invoices", "sales_invoice_lines", "sales_settlements")
REASON = "Modulul de vânzări (fixa)"
CHECK = " (configurația 1C: РеализацияТоваровУслуг / СчетФактураВыданный)"

ECON = {"revenue_type": "economic"}
ORG = {"revenue_type": "organization"}
# (document_type, operation, conditions, Dt, Kt, source_ref)
RULES = [
    ("sales_invoice", "revenue", ECON, "221", "618", "Factură emisă: creanța față de client / venit din activitatea economică" + CHECK),
    ("sales_invoice", "revenue", ORG, "221", "617", "Factură emisă: creanța față de client / venituri ale organizației" + CHECK),
    ("sales_invoice", "vat_collected", None, "221", "534.4", "Factură emisă: TVA colectată (Cod fiscal, Titlul III)" + CHECK),
    ("sales_invoice", "revenue_storno", ECON, "618", "221", "Stornare factură emisă: venit din activitatea economică" + CHECK),
    ("sales_invoice", "revenue_storno", ORG, "617", "221", "Stornare factură emisă: venituri ale organizației" + CHECK),
    ("sales_invoice", "vat_storno", None, "534.4", "221", "Stornare factură emisă: TVA colectată" + CHECK),
    ("bank_receipt", "customer_payment", None, "242", "221", "Încasare de la client (ПоступлениеНаРасчетныйСчет)"),
]

# conturile folosite de vânzări, adăugate planurilor create fără șablon complet
ACCOUNTS = (
    ("221", "Creanțe comerciale pe termen scurt", "active"),
    ("534.4", "Datorii privind TVA", "passive"),
    ("617", "Venituri ale organizației", "passive"),
    ("618", "Venituri din activitatea economică", "passive"),
)


def _id():
    return sa.Column("id", pg.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _org():
    return sa.Column("organization_id", pg.UUID, sa.ForeignKey("organizations.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "sales_invoices",
        _id(),
        _org(),
        sa.Column("document_id", pg.UUID, sa.ForeignKey("documents.id"), nullable=False, unique=True),
        sa.Column("kind", sa.String, nullable=False, server_default="invoice"),
        sa.Column("series", sa.String, nullable=False, server_default=""),
        sa.Column("number", sa.String, nullable=False),
        sa.Column("due_date", sa.Date),
        sa.Column("exchange_rate", sa.Numeric(12, 4)),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("storno_of_id", pg.UUID, sa.ForeignKey("sales_invoices.id")),
        sa.Column("notes", sa.Text),
        sa.Column("cancel_reason", sa.String),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "series", "number", name="uq_sales_invoices_number"),
        sa.CheckConstraint("kind in ('invoice','credit_note')", name="ck_sales_invoices_kind"),
        sa.CheckConstraint("status in ('active','cancelled')", name="ck_sales_invoices_status"),
    )
    op.create_index("ix_sales_invoices_org", "sales_invoices", ["organization_id"])
    op.create_index("ix_sales_invoices_storno", "sales_invoices", ["storno_of_id"])
    op.create_table(
        "sales_invoice_lines",
        _id(),
        _org(),
        sa.Column("sales_invoice_id", pg.UUID, sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("description", sa.String, nullable=False),
        sa.Column("unit", sa.String),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit_price", sa.Numeric(15, 4)),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("revenue_type", sa.String, nullable=False, server_default="economic"),
        sa.Column("account_id", pg.UUID, sa.ForeignKey("accounts.id")),
        sa.Column("grant_id", pg.UUID, sa.ForeignKey("grants.id")),
        sa.CheckConstraint("revenue_type in ('economic','organization')", name="ck_sales_invoice_lines_revenue"),
    )
    op.create_index("ix_sales_invoice_lines_invoice", "sales_invoice_lines", ["sales_invoice_id"])
    op.create_table(
        "sales_settlements",
        _id(),
        _org(),
        sa.Column("receipt_document_id", pg.UUID, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sales_invoice_id", pg.UUID, sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("receipt_document_id", "sales_invoice_id", name="uq_sales_settlements_pair"),
    )
    op.create_index("ix_sales_settlements_invoice", "sales_settlements", ["sales_invoice_id"])
    for table in TABLES:
        for stmt in enable_rls_sql(table):
            op.execute(stmt)

    insert = sa.text(
        "INSERT INTO posting_rules (id, document_type, operation, conditions, debit_account, credit_account, "
        "analytics, source_ref, valid_from, version, change_reason) VALUES (:id, :dt, :op, CAST(:cond AS jsonb), "
        ":d, :c, CAST(:analytics AS jsonb), :src, :vf, 1, :reason)"
    )
    for doc_type, operation, cond, debit, credit, source in RULES:
        op.execute(
            insert.bindparams(
                id=uuid.uuid4(), dt=doc_type, op=operation, cond=json.dumps(cond) if cond else None, d=debit,
                c=credit, analytics=json.dumps({}), src=source, vf=date(2015, 1, 1), reason=REASON,
            )
        )
    for code, name, kind in ACCOUNTS:
        op.execute(
            f"""
            INSERT INTO accounts (organization_id, code, name, account_kind)
            SELECT a.organization_id, '{code}', '{name}', '{kind}'
            FROM accounts a
            WHERE a.code = '242'
              AND NOT EXISTS (SELECT 1 FROM accounts x WHERE x.organization_id = a.organization_id AND x.code = '{code}')
            """
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
    for table in reversed(TABLES):
        for stmt in disable_rls_sql(table):
            op.execute(stmt)
        op.drop_table(table)
