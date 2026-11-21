"""Salarii: persoane fizice, contracte (CIM / civil), scutiri, finanțarea pe granturi,
perioadele și rezultatele calculului, plățile către persoane fizice (database/schema.dbml).

Cheile străine ale payment_order_lines spre persons / payroll_entries (lipseau până acum).
Un contract are un singur rând de calcul pe lună (period_id, contract_id), iar cota
de finanțare e între 0 și 100.

Revision ID: sal_0001
Revises: 0005
Create Date: 2026-11-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "sal_0001"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "year", "month"),
    )
    op.create_table(
        "persons",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("idnp_enc", sa.String(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("cpas", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contracts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("type", postgresql.ENUM("cim", "civil", name="contract_type", create_type=False), nullable=False),
        sa.Column("is_main_job", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("special_function_code", sa.String(), nullable=True),
        sa.Column("number", sa.String(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("gross_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "individual_payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("payment_kind", sa.String(), nullable=False),
        sa.Column("income_code", sa.String(), nullable=False),
        sa.Column("accrual_date", sa.Date(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("gross", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("tax_rate_id", sa.UUID(), nullable=True),
        sa.Column("income_tax", sa.Numeric(precision=15, scale=2), server_default=sa.text("0"), nullable=True),
        sa.Column("net", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("cost_item_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["cost_item_id"],
            ["cost_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id"],
            ["tax_rates.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_table(
        "contract_funding",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.Column("share_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("share_percent > 0 AND share_percent <= 100", name="ck_contract_funding_share"),
    )
    op.create_table(
        "exemption_claims",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dependents_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "payroll_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("income_code", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("insured_category", sa.String(), nullable=True),
        sa.Column("cnas_tariff", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("cnas_base", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("sick_benefit", sa.Numeric(precision=15, scale=2), server_default=sa.text("0"), nullable=True),
        sa.Column("gross", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("personal_exemption", sa.Numeric(precision=15, scale=2), server_default=sa.text("0"), nullable=True),
        sa.Column(
            "dependents_exemption", sa.Numeric(precision=15, scale=2), server_default=sa.text("0"), nullable=True
        ),
        sa.Column("taxable_income", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("income_tax", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("cnam_employee", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("cnas_employer", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("net", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.Column("calc_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["period_id"],
            ["payroll_periods.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_id", "contract_id", name="uq_payroll_entries_period_contract"),
    )
    op.create_foreign_key("payment_order_lines_person_id_fkey", "payment_order_lines", "persons", ["person_id"], ["id"])
    op.create_foreign_key(
        "payment_order_lines_payroll_entry_id_fkey",
        "payment_order_lines",
        "payroll_entries",
        ["payroll_entry_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("payment_order_lines_payroll_entry_id_fkey", "payment_order_lines", type_="foreignkey")
    op.drop_constraint("payment_order_lines_person_id_fkey", "payment_order_lines", type_="foreignkey")
    op.drop_table("payroll_entries")
    op.drop_table("exemption_claims")
    op.drop_table("contract_funding")
    op.drop_table("individual_payments")
    op.drop_table("contracts")
    op.drop_table("persons")
    op.drop_table("payroll_periods")
