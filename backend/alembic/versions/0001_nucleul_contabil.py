"""Nucleul contabil: baze, organizații, utilizatori, audit, plan de conturi,
documente, înregistrări (partiționate pe ani), rulaje, perioade, cote,
reguli de înregistrare și politica contabilă (database/schema.dbml).

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CONTRACT_TYPE = postgresql.ENUM("cim", "civil", name="contract_type", create_type=False)
ENTITY_TYPE = postgresql.ENUM(
    "srl",
    "sa",
    "ii",
    "gt",
    "ngo_association",
    "ngo_foundation",
    "ngo_other",
    "other",
    name="entity_type",
    create_type=False,
)
ACCOUNTING_METHOD = postgresql.ENUM("double_entry", "single_entry", name="accounting_method", create_type=False)
ACCOUNT_KIND = postgresql.ENUM("active", "passive", "active_passive", name="account_kind", create_type=False)
USER_ROLE = postgresql.ENUM(
    "admin", "chief_accountant", "accountant", "project_manager", "auditor", name="user_role", create_type=False
)
SUBCONTO_TYPE = postgresql.ENUM(
    "counterparty",
    "contract",
    "person",
    "item",
    "fixed_asset",
    "bank_account",
    "grant",
    "budget_line",
    "financing_source",
    name="subconto_type",
    create_type=False,
)
DOCUMENT_TYPE = postgresql.ENUM(
    "invoice",
    "e_invoice",
    "payment_order",
    "bank_statement",
    "contract",
    "act",
    "receipt",
    "individual_payment",
    "other",
    name="document_type",
    create_type=False,
)
DOCUMENT_STATUS = postgresql.ENUM(
    "new", "ai_processed", "to_review", "validated", "rejected", name="document_status", create_type=False
)
ENUMS = [
    CONTRACT_TYPE,
    ENTITY_TYPE,
    ACCOUNTING_METHOD,
    ACCOUNT_KIND,
    USER_ROLE,
    SUBCONTO_TYPE,
    DOCUMENT_TYPE,
    DOCUMENT_STATUS,
]

# entry_lines e partiționată pe ani; partiția implicită prinde anii neprevăzuți
PARTITION_YEARS = range(2015, 2041)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("totp_secret_enc", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("last_login_at", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("applies_to", CONTRACT_TYPE, nullable=True),
        sa.Column("value", sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column("is_percent", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("legal_basis", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("legal_update_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code",
            "applies_to",
            "valid_from",
            name="uq_tax_rates_code_applies_valid",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("idno", sa.String(length=13), nullable=False),
        sa.Column("entity_type", ENTITY_TYPE, nullable=False),
        sa.Column("accounting_method", ACCOUNTING_METHOD, server_default=sa.text("'double_entry'"), nullable=False),
        sa.Column("vat_payer_from", sa.Date(), nullable=True),
        sa.Column("vat_code", sa.String(), nullable=True),
        sa.Column("legal_form", sa.String(), nullable=True),
        sa.Column("drive_root_folder_id", sa.String(), nullable=True),
        sa.Column("base_currency", sa.CHAR(length=3), server_default=sa.text("'MDL'"), nullable=True),
        sa.Column("ngo_category", sa.CHAR(length=1), nullable=True),
        sa.Column("cuiio", sa.String(), nullable=True),
        sa.Column("cfoj", sa.String(), nullable=True),
        sa.Column("cfp", sa.String(), nullable=True),
        sa.Column("cuatm", sa.String(), nullable=True),
        sa.Column("caem", sa.String(), nullable=True),
        sa.Column("cnas_code", sa.String(), nullable=True),
        sa.Column("sfs_office", sa.String(), nullable=True),
        sa.Column("director_name", sa.String(), nullable=True),
        sa.Column("chief_accountant_name", sa.String(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idno"),
    )
    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("closed_by", sa.UUID(), nullable=True),
        sa.Column("closed_at", postgresql.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(
            ["closed_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "year", "month"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("account_kind", ACCOUNT_KIND, nullable=False),
        sa.Column("is_group", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("is_currency", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cost_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("con5_article", sa.String(), nullable=True),
        sa.Column("designation_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("cuatm", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["departments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organization_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_table(
        "posting_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("debit_account", sa.String(), nullable=False),
        sa.Column("credit_account", sa.String(), nullable=False),
        sa.Column("analytics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("release_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_analytics",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("subconto_type", SUBCONTO_TYPE, nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "position"),
    )
    op.create_table(
        "accounting_policies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("grant_receivable_account_id", sa.UUID(), nullable=True),
        sa.Column("grant_recognition", sa.String(), server_default=sa.text("'on_signing'"), nullable=True),
        sa.Column("stock_to_deferred_income", sa.String(), server_default=sa.text("'unused_only'"), nullable=True),
        sa.Column("fa_valuation_method", sa.String(), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["grant_receivable_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "valid_from"),
    )
    op.create_table(
        "grants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("funding_type", sa.String(), nullable=True),
        sa.Column("designation_year", sa.Integer(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("accrue_funding_debt", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("drive_folder_id", sa.String(), nullable=True),
        sa.Column("report_template_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_turnovers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), server_default=sa.text("'MDL'"), nullable=False),
        sa.Column("debit", sa.Numeric(precision=17, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("credit", sa.Numeric(precision=17, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("debit_currency", sa.Numeric(precision=17, scale=2), server_default=sa.text("0"), nullable=True),
        sa.Column("credit_currency", sa.Numeric(precision=17, scale=2), server_default=sa.text("0"), nullable=True),
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
        sa.UniqueConstraint(
            "organization_id",
            "account_id",
            "period",
            "grant_id",
            "currency",
            name="uq_account_turnovers_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "budget_lines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("cost_item_id", sa.UUID(), nullable=True),
        sa.Column("budget_version_id", sa.UUID(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("planned_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("donor_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("cofinancing_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["cost_item_id"],
            ["cost_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["budget_lines.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", "budget_version_id", "code"),
        sa.UniqueConstraint("id", "grant_id", name="uq_budget_lines_id_grant"),
    )
    op.create_table(
        "counterparties",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("idno", sa.String(length=13), nullable=True),
        sa.Column("vat_code", sa.String(), nullable=True),
        sa.Column("iban_enc", sa.String(), nullable=True),
        sa.Column("bank_code", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("default_budget_line_id", sa.UUID(), nullable=True),
        sa.Column("onec_guid", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["default_budget_line_id"],
            ["budget_lines.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idno"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("type", DOCUMENT_TYPE, nullable=True),
        sa.Column("status", DOCUMENT_STATUS, server_default=sa.text("'new'"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("deletion_mark", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=True),
        sa.Column("storage_connection_id", sa.UUID(), nullable=True),
        sa.Column("file_id", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("counterparty_id", sa.UUID(), nullable=True),
        sa.Column("doc_number", sa.String(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("validated_by", sa.UUID(), nullable=True),
        sa.Column("validated_at", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["counterparties.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["validated_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "sha256"),
    )
    op.create_index("ix_documents_organization_id_status", "documents", ["organization_id", "status"], unique=False)
    op.create_table(
        "entry_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("debit_account_id", sa.UUID(), nullable=False),
        sa.Column("credit_account_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=True),
        sa.Column("currency_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=15, scale=3), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("budget_line_id", sa.UUID(), nullable=True),
        sa.Column("cost_item_id", sa.UUID(), nullable=True),
        sa.Column("activity_type", sa.String(), nullable=True),
        sa.Column("is_non_statutory", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["budget_line_id", "grant_id"],
            ["budget_lines.id", "budget_lines.grant_id"],
            name="fk_entry_lines_budget_line_grant",
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
            ["credit_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["debit_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
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
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id", "entry_date"),
        postgresql_partition_by="RANGE (entry_date)",
    )
    op.create_index(
        "ix_entry_lines_credit_account_id_entry_date", "entry_lines", ["credit_account_id", "entry_date"], unique=False
    )
    op.create_index(
        "ix_entry_lines_debit_account_id_entry_date", "entry_lines", ["debit_account_id", "entry_date"], unique=False
    )
    op.create_index("ix_entry_lines_document_id", "entry_lines", ["document_id"], unique=False)
    op.create_index(
        "ix_entry_lines_grant_budget_line_entry_date",
        "entry_lines",
        ["grant_id", "budget_line_id", "entry_date"],
        unique=False,
    )
    op.create_index(
        "ix_entry_lines_organization_id_entry_date", "entry_lines", ["organization_id", "entry_date"], unique=False
    )
    for year in PARTITION_YEARS:
        op.execute(
            f"CREATE TABLE entry_lines_{year} PARTITION OF entry_lines "
            f"FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')"
        )
    op.execute("CREATE TABLE entry_lines_default PARTITION OF entry_lines DEFAULT")
    op.create_table(
        "entry_line_analytics",
        sa.Column("entry_line_id", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.CHAR(length=1), nullable=False),
        sa.Column("subconto_type", SUBCONTO_TYPE, nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("ref_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_line_id", "entry_date"],
            ["entry_lines.id", "entry_lines.entry_date"],
            name="fk_entry_line_analytics_entry_line",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entry_line_id", "side", "subconto_type"),
    )
    op.create_index(
        "ix_entry_line_analytics_subconto_type_ref_id",
        "entry_line_analytics",
        ["subconto_type", "ref_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_entry_line_analytics_subconto_type_ref_id", table_name="entry_line_analytics")
    op.drop_table("entry_line_analytics")
    op.drop_index("ix_entry_lines_organization_id_entry_date", table_name="entry_lines")
    op.drop_index("ix_entry_lines_grant_budget_line_entry_date", table_name="entry_lines")
    op.drop_index("ix_entry_lines_document_id", table_name="entry_lines")
    op.drop_index("ix_entry_lines_debit_account_id_entry_date", table_name="entry_lines")
    op.drop_index("ix_entry_lines_credit_account_id_entry_date", table_name="entry_lines")
    op.drop_table("entry_lines")
    op.drop_index("ix_documents_organization_id_status", table_name="documents")
    op.drop_table("documents")
    op.drop_table("counterparties")
    op.drop_table("budget_lines")
    op.drop_table("account_turnovers")
    op.drop_table("grants")
    op.drop_table("accounting_policies")
    op.drop_table("account_analytics")
    op.drop_table("posting_rules")
    op.drop_table("organization_members")
    op.drop_table("departments")
    op.drop_table("cost_items")
    op.drop_table("audit_log")
    op.drop_table("accounts")
    op.drop_table("accounting_periods")
    op.drop_table("organizations")
    op.drop_table("workspaces")
    op.drop_table("tax_rates")
    op.drop_table("users")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
