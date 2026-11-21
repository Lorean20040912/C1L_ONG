"""Factura primită și ordinul de plată: invoices, invoice_lines, payment_orders,
payment_order_lines, plus bank_accounts și fixed_assets la care trimit.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LINE_KIND = postgresql.ENUM(
    "fixed_asset", "low_value_item", "material", "goods", "service", name="line_kind", create_type=False
)
PAYMENT_DIRECTION = postgresql.ENUM("incoming", "outgoing", name="payment_direction", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    LINE_KIND.create(bind, checkfirst=True)
    PAYMENT_DIRECTION.create(bind, checkfirst=True)

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("iban_enc", sa.String(), nullable=False),
        sa.Column("bank_name", sa.String(), nullable=True),
        sa.Column("bank_code", sa.String(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "fixed_assets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("inventory_no", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("initial_cost", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("residual_value", sa.Numeric(precision=15, scale=2), server_default=sa.text("0"), nullable=True),
        sa.Column("useful_life_months", sa.Integer(), nullable=True),
        sa.Column("depreciation_method", sa.String(), server_default=sa.text("'linear'"), nullable=True),
        sa.Column("asset_group", sa.String(), nullable=True),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("depreciation_account_id", sa.UUID(), nullable=True),
        sa.Column("expense_account_id", sa.UUID(), nullable=True),
        sa.Column("commissioning_date", sa.Date(), nullable=True),
        sa.Column("depreciation_start", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'in_use'"), nullable=True),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["depreciation_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["expense_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("series", sa.String(), nullable=True),
        sa.Column("e_invoice_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("warehouse_id", sa.UUID(), nullable=True),
        sa.Column("line_kind", LINE_KIND, server_default=sa.text("'service'"), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.Column("cost_item_id", sa.UUID(), nullable=True),
        sa.Column("fixed_asset_id", sa.UUID(), nullable=True),
        sa.Column("put_into_use", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["cost_item_id"],
            ["cost_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["fixed_asset_id"],
            ["fixed_assets.id"],
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("direction", PAYMENT_DIRECTION, nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("invoice_id", sa.UUID(), nullable=True),
        sa.Column("bank_account_id", sa.UUID(), nullable=True),
        sa.Column("beneficiary_iban", sa.String(), nullable=True),
        sa.Column("beneficiary_name", sa.String(), nullable=True),
        sa.Column("beneficiary_idno", sa.String(), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("kind", sa.String(), server_default=sa.text("'regular'"), nullable=True),
        sa.Column("tax_kind", sa.String(), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("bank_status", sa.String(), server_default=sa.text("'draft'"), nullable=True),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            ["bank_accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_table(
        "payment_order_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_order_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=True),
        sa.Column("payroll_entry_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.ForeignKeyConstraint(["payment_order_id"], ["payment_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("payment_order_lines")
    op.drop_table("payment_orders")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("fixed_assets")
    op.drop_table("bank_accounts")
    bind = op.get_bind()
    LINE_KIND.drop(bind, checkfirst=True)
    PAYMENT_DIRECTION.drop(bind, checkfirst=True)
