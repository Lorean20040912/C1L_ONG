"""Modulul bancă: profilurile băncilor, importul extraselor, loturile de export,
cursul BNM, regulile diferențelor de curs și criptarea IBAN-ului (docs/09, docs/02 §6, docs/11 §2.5).

Revision ID: bnk_0001
Revises: 0005
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "bnk_0001"
down_revision = "0005"
branch_labels = None
depends_on = None

BANK_FILE_TYPE = postgresql.ENUM("txt", "dbf", "dbo", "xml", "csv", name="bank_file_type", create_type=False)
PAYMENT_DIRECTION = postgresql.ENUM("incoming", "outgoing", name="payment_direction", create_type=False)

PROFILES_REASON = "standard"
RULES_REASON = "Închiderea lunii: diferențe de curs valutar (docs/11 §2.5)"

# ───────────── profilurile standard (structura din docs/09; datele — fictive) ─────────────

MAIB_FIELDS = {
    "date": "DATA",
    "doc_number": "NDOC",
    "dc": "DC",
    "account": "CCL",
    "counterparty_iban": "CCOR",
    "counterparty_idno": "CFCCOR",
    "counterparty_name": "DENCT",
    "amount": "SUMN",
    "currency": "TV",
    "purpose": ["DE1", "DE2", "DE3", "DE4"],
    "tx_code": "COD_TRANZ",
}
MAIB_DIRECTION = {"field": "dc", "outgoing": ["D"], "incoming": ["C", "K"]}

IMPORT_PROFILES = [
    ("MAIB", "txt", "cp1251", {
        "parser": "delimited", "separator": "^", "header": True, "skip_rows": 1,
        "date_formats": ["%d.%m.%Y", "%Y%m%d"], "fields": MAIB_FIELDS, "direction": MAIB_DIRECTION,
    }),
    ("MAIB", "csv", "cp1251", {
        "parser": "delimited", "separator": ",", "header": True, "skip_rows": 1,
        "date_formats": ["%d-%m-%Y", "%d.%m.%Y"], "fields": MAIB_FIELDS, "direction": MAIB_DIRECTION,
    }),
    ("MAIB", "dbf", "cp866", {"parser": "dbf", "fields": MAIB_FIELDS, "direction": MAIB_DIRECTION}),
    ("MAIB (DBO)", "dbo", "cp1251", {"parser": "client_bank_exchange", "direction": {"mode": "by_account"}}),
    ("Moldindconbank", "dbo", "cp1251", {"parser": "client_bank_exchange", "direction": {"mode": "by_account"}}),
    ("OTP Bank", "txt", "cp1251", {"parser": "client_bank_exchange", "direction": {"mode": "by_account"}}),
    ("Moldindconbank", "xml", "utf-8", {
        "parser": "xml_rowdata", "row_tag": "ROW",
        "fields": {
            "date": "DOCUMENTDATE", "doc_number": "DOCUMENTNO", "amount": "AMOUNT",
            "payer_account": "IBAN_A", "receiver_account": "IBAN_B",
            "payer_idno": "FISCALCODE", "receiver_idno": "CORRFISCALCODE",
            "payer_name": "CONTRAGENTSNAME", "receiver_name": "CORRSNAME",
            "purpose": "DETAILSOFPAYMENT", "tx_code": "TRANSACTIONCODE",
        },
        "direction": {"mode": "by_account"},
        "date_formats": ["%y%m%d", "%d.%m.%Y", "%Y-%m-%d"],
    }),
    # pozițiile se verifică după documentația FinComBank (docs/09: „de la contabil”)
    ("FinComBank", "txt", "cp1251", {
        "parser": "fixed_width", "skip_rows": 0,
        "fields": {
            "date": [0, 8], "doc_number": [8, 10], "dc": [18, 1], "account": [19, 24],
            "counterparty_iban": [43, 24], "counterparty_idno": [67, 13], "counterparty_name": [80, 100],
            "amount": [180, 15], "currency": [195, 3], "purpose": [198, 210],
        },
        "date_formats": ["%Y%m%d", "%d.%m.%Y"],
        "direction": MAIB_DIRECTION,
    }),
]

EXPORT_PROFILES = [
    ("MAIB", "dbf", "cp1251", {
        "exporter": "dbf", "total_row_first": True,
        "fields": [
            {"name": "DATA", "type": "D", "value": "date"},
            {"name": "NDOC", "type": "C", "length": 10, "value": "doc_number"},
            {"name": "CCL", "type": "C", "length": 30, "value": "payer_iban"},
            {"name": "CCOR", "type": "C", "length": 30, "value": "beneficiary_iban"},
            {"name": "CCORT", "type": "C", "length": 30, "value": "const:"},
            {"name": "CFC", "type": "C", "length": 18, "value": "payer_idno"},
            {"name": "CFCCOR", "type": "C", "length": 18, "value": "beneficiary_idno"},
            {"name": "CBC", "type": "N", "length": 3, "decimals": 0, "value": "const:"},
            {"name": "DENC", "type": "C", "length": 55, "value": "beneficiary_name", "prefix": "(R) "},
            {"name": "DENCT", "type": "C", "length": 50, "value": "const:"},
            {"name": "SUMN", "type": "N", "length": 15, "decimals": 2, "value": "amount"},
            {"name": "TD", "type": "N", "length": 2, "decimals": 0, "value": "const:8"},
            {"name": "DE1", "type": "C", "length": 220, "value": "purpose", "part": 0, "part_length": 220},
            {"name": "DE2", "type": "C", "length": 220, "value": "purpose", "part": 1, "part_length": 220},
            {"name": "BIC", "type": "C", "length": 220, "value": "bank_code"},
            {"name": "URGENT", "type": "C", "length": 1, "value": "urgent"},
        ],
    }),
    ("OTP Bank", "dbf", "cp1251", {
        "exporter": "dbf",
        "fields": [
            {"name": "DATAV", "type": "C", "length": 8, "value": "date", "format": "%Y%m%d"},
            {"name": "NDOC", "type": "C", "length": 10, "value": "doc_number"},
            {"name": "CCL", "type": "C", "length": 24, "value": "payer_iban"},
            {"name": "CFC", "type": "C", "length": 13, "value": "payer_idno"},
            {"name": "CSC", "type": "C", "length": 4, "value": "const:"},
            {"name": "CCOR", "type": "C", "length": 24, "value": "beneficiary_iban"},
            {"name": "DENC", "type": "C", "length": 105, "value": "beneficiary_name"},
            {"name": "REZB", "type": "C", "length": 1, "value": "residency"},
            {"name": "CFCCOR", "type": "C", "length": 13, "value": "beneficiary_idno"},
            {"name": "SUMN", "type": "N", "length": 15, "decimals": 2, "value": "amount"},
            {"name": "TC", "type": "C", "length": 3, "value": "currency"},
            {"name": "DE", "type": "C", "length": 210, "value": "purpose"},
            {"name": "URGENT", "type": "C", "length": 1, "value": "urgent"},
        ],
    }),
    ("FinComBank", "xml", "utf-8", {
        "exporter": "xml_rowdata",
        "fields": [
            {"name": "ACCOUNTNO", "value": "payer_iban"},
            {"name": "IBAN_A", "value": "payer_iban"},
            {"name": "BIC_B", "value": "bank_code"},
            {"name": "CORRACCOUNTNO", "value": "beneficiary_iban"},
            {"name": "IBAN_B", "value": "beneficiary_iban"},
            {"name": "TRANSACTIONCODE", "value": "transaction_code"},
            {"name": "DOCUMENTNO", "value": "doc_number"},
            {"name": "DOCUMENTDATE", "value": "date", "format": "%y%m%d"},
            {"name": "VALUEDATE", "value": "date", "format": "%y%m%d"},
            {"name": "AMOUNT", "value": "amount"},
            {"name": "FISCALCODE", "value": "payer_idno"},
            {"name": "CONTRAGENTSNAME", "value": "payer_name"},
            {"name": "CORRFISCALCODE", "value": "beneficiary_idno"},
            {"name": "CORRSNAME", "value": "beneficiary_name"},
            {"name": "DETAILSOFPAYMENT", "value": "purpose"},
            {"name": "CORRRESIDENCY", "value": "residency"},
            {"name": "RESIDENCY", "value": "residency"},
            {"name": "PRIORITY", "value": "urgent"},
        ],
    }),
    ("Victoriabank / Moldindconbank (BS-Client)", "txt", "cp1251", {
        "exporter": "client_bank_exchange", "purpose_length": 210,
    }),
]

# ───────────── regulile pasului „Diferențe de curs valutar” ─────────────
# Contul reevaluat (243, 234.4/235, 521...) vine din rând (debit/credit_account_id); formula dă contrapartida.
GRANT = {"required": ["grant"], "activity_type": "special_purpose"}
SP = {"funding": "special_purpose"}
FX_RULES = [
    ("revaluation_increase", SP, "243", "537", GRANT, "IM188; ART sit.4"),
    ("revaluation_decrease", SP, "537", "243", GRANT, "IM188; ART sit.4"),
    ("revaluation_increase", None, "243", "622", None, "PGC: 622 Venituri financiare"),
    ("revaluation_decrease", None, "722", "243", None, "PGC: 722 Cheltuieli financiare"),
]


def upgrade() -> None:
    bind = op.get_bind()
    BANK_FILE_TYPE.create(bind, checkfirst=True)

    op.create_table(
        "bank_formats",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("bank_name", sa.String(), nullable=False),
        sa.Column("file_type", BANK_FILE_TYPE, nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("encoding", sa.String(), server_default=sa.text("'cp1251'"), nullable=True),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bank_imports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("bank_account_id", sa.UUID(), nullable=False),
        sa.Column("format_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=True),
        sa.Column("rows_created", sa.Integer(), nullable=True),
        sa.Column("rows_skipped", sa.Integer(), nullable=True),
        sa.Column("rows_failed", sa.Integer(), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("imported_by", sa.UUID(), nullable=True),
        sa.Column("imported_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["format_id"], ["bank_formats.id"]),
        sa.ForeignKeyConstraint(["imported_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("tx_date", sa.Date(), nullable=False),
        sa.Column("direction", PAYMENT_DIRECTION, nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("counterparty_iban", sa.String(), nullable=True),
        sa.Column("counterparty_idno", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("doc_number", sa.String(), nullable=True),
        sa.Column("counterparty_name", sa.String(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=True),
        sa.Column("match", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["bank_imports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    op.create_table(
        "payment_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("bank_format_id", sa.UUID(), nullable=False),
        sa.Column("bank_account_id", sa.UUID(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(), server_default=sa.text("now()"), nullable=True),
        sa.Column("folder_path", sa.String(), nullable=True),
        sa.Column("file_id", sa.String(), nullable=True),
        sa.Column("orders_count", sa.Integer(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["bank_format_id"], ["bank_formats.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "payment_orders_batch_id_fkey", "payment_orders", "payment_batches", ["batch_id"], ["id"]
    )
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("source", sa.String(), server_default=sa.text("'manual'"), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "currency", "rate_date"),
    )

    insert_format = sa.text(
        "INSERT INTO bank_formats (id, organization_id, bank_name, file_type, direction, encoding, layout, version) "
        "VALUES (:id, NULL, :bank, CAST(:ftype AS bank_file_type), :direction, :enc, CAST(:layout AS jsonb), 1)"
    )
    for direction, profiles in (("import_statement", IMPORT_PROFILES), ("export_payments", EXPORT_PROFILES)):
        for bank, ftype, enc, layout in profiles:
            bind.execute(
                insert_format,
                {"id": uuid.uuid4(), "bank": bank, "ftype": ftype, "direction": direction, "enc": enc,
                 "layout": json.dumps(layout)},
            )  # fmt: skip

    insert_rule = sa.text(
        "INSERT INTO posting_rules (id, document_type, operation, conditions, debit_account, credit_account, "
        "analytics, source_ref, valid_from, version, change_reason) VALUES (:id, 'month_close.fx', :operation, "
        "CAST(:conditions AS jsonb), :debit, :credit, CAST(:analytics AS jsonb), :source, :valid_from, 1, :reason)"
    )
    for operation, conditions, debit, credit, analytics, source in FX_RULES:
        bind.execute(
            insert_rule,
            {"id": uuid.uuid4(), "operation": operation, "conditions": json.dumps(conditions) if conditions else None,
             "debit": debit, "credit": credit, "analytics": json.dumps(analytics) if analytics else None,
             "source": source, "valid_from": date(2015, 1, 1), "reason": RULES_REASON},
        )  # fmt: skip

    # IBAN-urile existente se criptează cu cheia din .env
    from app.core.crypto import encrypt, is_encrypted, normalize_iban

    for row_id, iban in bind.execute(sa.text("SELECT id, iban_enc FROM bank_accounts")).all():
        if not is_encrypted(iban):
            bind.execute(
                sa.text("UPDATE bank_accounts SET iban_enc = :v WHERE id = :id"),
                {"v": encrypt(normalize_iban(iban)), "id": row_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    from app.core.crypto import decrypt

    for row_id, iban in bind.execute(sa.text("SELECT id, iban_enc FROM bank_accounts")).all():
        bind.execute(sa.text("UPDATE bank_accounts SET iban_enc = :v WHERE id = :id"), {"v": decrypt(iban), "id": row_id})
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(
            r=RULES_REASON
        )
    )
    op.drop_table("exchange_rates")
    op.drop_constraint("payment_orders_batch_id_fkey", "payment_orders", type_="foreignkey")
    op.drop_table("payment_batches")
    op.drop_table("bank_transactions")
    op.drop_table("bank_imports")
    op.drop_table("bank_formats")
    BANK_FILE_TYPE.drop(bind, checkfirst=True)
