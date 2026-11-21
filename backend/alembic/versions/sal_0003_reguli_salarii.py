"""Regulile standard de înregistrare pentru salarii, plățile către persoane fizice
și plata cumulată a impozitelor (docs/11 §2.2, §4; docs/09 §3).

Cheltuiala salarială urmează sursa de finanțare a contractului (contract_funding):
mijloace cu destinație specială → 716 + recunoașterea venitului 537/616,
nepredestinate → 717, activitatea economică → 718. Reținerile (CNAM, impozitul)
și contribuția CNAS poartă grantul, ca plata cumulată să stingă datoria pe proiect.

Revision ID: sal_0003
Revises: sal_0002
Create Date: 2026-11-21
"""

import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "sal_0003"
down_revision = "sal_0002"
branch_labels = None
depends_on = None

VALID_FROM = date(2015, 1, 1)
REASON = "Regulile standard pentru salarii și IPC21 (modulul salarii)"

SP = {"funding": "special_purpose"}
OWN = {"funding": "unrestricted"}
ECO = {"funding": "economic"}
GRANT = {"required": ["grant"]}
GRANT_SP = {"required": ["grant"], "activity_type": "special_purpose"}
MIRROR = {"required": ["grant"], "activity_type": "special_purpose", "budget_line": "drop"}
DROP = {"budget_line": "drop"}

# (document_type, operation, conditions, Dt, Kt, analytics, source_ref)
RULES = [
    # calculul salariului (pasul „payroll” al închiderii lunii)
    ("payroll", "salary_expense", SP, "716", "531", GRANT_SP, "IM188; ART sit.2; CM"),
    ("payroll", "salary_expense", OWN, "717", "531", GRANT, "IM188; SEM"),
    ("payroll", "salary_expense", ECO, "718", "531", {"activity_type": "economic"}, "IM188"),
    ("payroll", "employer_contribution", SP, "716", "533", GRANT_SP, "IM188; ART sit.2"),
    ("payroll", "employer_contribution", OWN, "717", "533", GRANT, "IM188; SEM"),
    ("payroll", "employer_contribution", ECO, "718", "533", {"activity_type": "economic"}, "IM188"),
    ("payroll", "income_recognition", SP, "537", "616", MIRROR, "IM188; ART sit.2"),
    ("payroll", "cnam_withholding", {}, "531", "533", DROP, "docs/05 Tabelul 1 col.6"),
    ("payroll", "income_tax_withholding", {}, "531", "534", DROP, "docs/05 Tabelul 1 col.5"),
    # „Plată către persoană fizică” (chirie, arendă, servicii, donație...)
    ("individual_payment", "expense", SP, "716", "544", GRANT_SP, "IM188; ART sit.2; docs/05 §2"),
    ("individual_payment", "expense", OWN, "717", "544", GRANT, "IM188; SEM; docs/05 §2"),
    ("individual_payment", "expense", ECO, "718", "544", {"activity_type": "economic"}, "IM188; docs/05 §2"),
    ("individual_payment", "income_recognition", SP, "537", "616", MIRROR, "IM188; ART sit.2"),
    ("individual_payment", "income_tax_withholding", {}, "544", "534", DROP, "docs/05 §2"),
    # plata cumulată (payment_orders.kind = grouped_tax): contul bancar vine din ordin
    ("payment_order", "tax_payment", {"tax_kind": "income_tax"}, "534", "242", DROP, "docs/09 §3"),
    ("payment_order", "tax_payment", {"tax_kind": ["cnas", "cnam"]}, "533", "242", DROP, "docs/09 §3"),
    ("payment_order", "tax_payment", {"tax_kind": "net_salary"}, "531", "242", DROP, "docs/09 §3"),
]

posting_rules = sa.table(
    "posting_rules",
    sa.column("id", sa.UUID),
    sa.column("organization_id", sa.UUID),
    sa.column("document_type", sa.String),
    sa.column("operation", sa.String),
    sa.column("conditions", postgresql.JSONB),
    sa.column("debit_account", sa.String),
    sa.column("credit_account", sa.String),
    sa.column("analytics", postgresql.JSONB),
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
