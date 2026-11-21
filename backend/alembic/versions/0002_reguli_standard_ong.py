"""Regulile standard de înregistrare pentru ONG (docs/11-reguli-contabile-ong.md).

Regulile standard au organization_id gol; organizația le poate corecta cu
reguli proprii, care au prioritate. Fiecare regulă citează sursa.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""

import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

VALID_FROM = date(2015, 1, 1)  # IM188 (Ordinul MF nr. 188 din 30.12.2014)
REASON = "Regulile standard ONG, docs/11-reguli-contabile-ong.md"

SP = {"funding": "special_purpose"}
GRANT = {"required": ["grant"]}
GRANT_SP = {"required": ["grant"], "activity_type": "special_purpose"}

# (document_type, operation, conditions, Dt, Kt, analytics, source_ref)
RULES = [
    # 2.1 Recunoașterea grantului și tranșele
    ("grant_income", "recognition", {"grant_recognition": "on_signing", "term": "long"},
     "{grant_receivable}", "425", GRANT, "IM188; ART sit.1"),
    ("grant_income", "recognition", {"grant_recognition": "on_signing", "term": "current"},
     "{grant_receivable}", "537", GRANT, "IM188; ART sit.1"),
    ("grant_income", "tranche_received", {"grant_recognition": "on_signing"},
     "242", "{grant_receivable}", GRANT, "ART sit.1; SEM"),
    ("grant_income", "tranche_received", {"grant_recognition": "on_receipt"},
     "242", "537", GRANT, "SEM"),
    # 2.6 Dobânzi pe soldurile grantului
    ("grant_income", "interest", {}, "{grant_receivable}", "537", GRANT, "IM188; ART"),
    # 2.2 Cheltuieli curente din grant; 2.8 / 3 cheltuieli nepredestinate
    ("invoice", "expense", SP, "716", "521", GRANT_SP, "IM188; ART sit.2"),
    ("invoice", "income_recognition", SP, "537", "616", GRANT_SP, "IM188; ART sit.2"),
    ("invoice", "expense", {"funding": "unrestricted"}, "717", "521", GRANT, "IM188; SEM"),
    ("invoice", "expense", {"funding": "economic"}, "718", "521", {"activity_type": "economic"}, "IM188"),
    # 2.3 Stocuri cumpărate din grant
    ("invoice", "stock_receipt", {}, "211", "521", {}, "ART sit.2"),
    ("invoice", "deferred_income", SP, "537", "535", GRANT, "ART sit.2"),
    ("stock_distribution", "expense", SP, "716", "211", GRANT_SP, "ART sit.2"),
    ("stock_distribution", "income_recognition", SP, "537", "616", GRANT_SP, "ART sit.2"),
    ("stock_distribution", "income_recognition", {**SP, "income_from": "deferred"},
     "535", "616", GRANT_SP, "ART sit.2"),
    # 2.4 Mijloace fixe din grant
    ("invoice", "fixed_asset_receipt", {}, "123", "521", {}, "ART sit.3"),
    ("invoice", "fixed_asset_fund", {**SP, "term": "current"}, "537", "3411", GRANT, "IM188; ART sit.3"),
    ("invoice", "fixed_asset_fund", {**SP, "term": "long"}, "425", "3411", GRANT, "IM188; ART sit.3"),
    ("month_close.depreciation", "depreciation", SP, "3411", "124", GRANT, "IM188; ART sit.3; SEM"),
    # plata furnizorului; 2.7 restituirea mijloacelor neutilizate
    ("payment_order", "supplier_payment", {}, "521", "242", {}, "ART sit.2"),
    ("payment_order", "grant_refund", {}, "537", "242", GRANT, "IM188; ART"),
    # 2.7 Mijloace rămase la dispoziția ONG
    ("grant_close", "unused_to_own_funds", {"term": "current"}, "537", "3412", GRANT, "IM188; ART"),
    ("grant_close", "unused_to_own_funds", {"term": "long"}, "425", "3412", GRANT, "IM188; ART"),
    # 2.5 Diferențe de curs pe mijloacele cu destinație specială
    ("fx_difference", "grant_receipt_unfavorable", {}, "537", "{grant_receivable}", GRANT, "IM188; ART sit.4"),
    ("fx_difference", "payment_unfavorable", {}, "537", "521", GRANT, "IM188; ART sit.4"),
    ("fx_difference", "payment_favorable", {}, "521", "537", GRANT, "IM188; ART sit.4"),
    # 3.1 Cotizații de membru
    ("membership_fee", "accrual", {}, "234", "617", {}, "SEM"),
    ("membership_fee", "receipt", {}, "242", "234", {}, "SEM"),
    ("membership_fee", "write_off", {}, "717", "234", {}, "SEM"),
]

posting_rules = sa.table(
    "posting_rules",
    sa.column("id", sa.UUID),
    sa.column("organization_id", sa.UUID),
    sa.column("document_type", sa.String),
    sa.column("operation", sa.String),
    sa.column("conditions", sa.dialects.postgresql.JSONB),
    sa.column("debit_account", sa.String),
    sa.column("credit_account", sa.String),
    sa.column("analytics", sa.dialects.postgresql.JSONB),
    sa.column("source_ref", sa.String),
    sa.column("valid_from", sa.Date),
    sa.column("version", sa.Integer),
    sa.column("change_reason", sa.Text),
)


def upgrade() -> None:
    op.bulk_insert(
        posting_rules,
        [
            {
                "id": uuid.uuid4(),
                "organization_id": None,
                "document_type": doc_type,
                "operation": operation,
                "conditions": conditions or None,
                "debit_account": debit,
                "credit_account": credit,
                "analytics": analytics or None,
                "source_ref": source,
                "valid_from": VALID_FROM,
                "version": 1,
                "change_reason": REASON,
            }
            for doc_type, operation, conditions, debit, credit, analytics, source in RULES
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )

