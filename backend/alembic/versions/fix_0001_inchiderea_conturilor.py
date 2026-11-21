"""Închiderea conturilor de venituri și cheltuieli (clasele 6 și 7) la contul de rezultat 331.

Regulile sunt date: `month_close.account_closing` cu conturile 6xx/7xx alese la
calcul (contul închis vine din sold). Contul 331 se adaugă organizațiilor ONG
care nu au niciun cont 33x și șablonului „ngo”.

Revision ID: fix_0001
Revises: mrg_0007
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "fix_0001"
down_revision = "mrg_0007"
branch_labels = None
depends_on = None

REASON = "Închiderea conturilor de venituri și cheltuieli (ToR F2b.4)"
ACCOUNT = {"code": "331", "name": "Rezultatul exercițiului (venituri și cheltuieli închise)", "kind": "active_passive"}
RULES = [
    ("close_income", "616", "331", "ToR F2b.4; docs/11"),  # Dt venit (cont ales) — Kt 331
    ("close_expense", "331", "717", "ToR F2b.4; docs/11"),  # Dt 331 — Kt cheltuială (cont ales)
]


def upgrade() -> None:
    conn = op.get_bind()
    for operation, debit, credit, source in RULES:
        conn.execute(
            sa.text(
                "INSERT INTO posting_rules (id, organization_id, document_type, operation, debit_account, "
                "credit_account, source_ref, valid_from, version, change_reason) "
                "VALUES (:id, NULL, 'month_close.account_closing', :op, :dt, :kt, :src, :vf, 1, :why)"
            ),
            {"id": uuid.uuid4(), "op": operation, "dt": debit, "kt": credit, "src": source, "vf": date(2015, 1, 1), "why": REASON},
        )
    conn.execute(
        sa.text(
            "INSERT INTO accounts (organization_id, code, name, account_kind) "
            "SELECT o.id, :code, :name, 'active_passive' FROM organizations o "
            "WHERE EXISTS (SELECT 1 FROM accounts a WHERE a.organization_id = o.id AND a.code = '616') "
            "AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.organization_id = o.id AND a.code LIKE '33%')"
        ),
        {"code": ACCOUNT["code"], "name": ACCOUNT["name"]},
    )
    conn.execute(
        sa.text(
            "UPDATE coa_templates SET accounts = accounts || CAST(:acc AS jsonb) "
            "WHERE code = 'ngo' AND NOT (accounts @> CAST(:probe AS jsonb))"
        ),
        {"acc": json.dumps([ACCOUNT]), "probe": json.dumps([{"code": "331"}])},
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM posting_rules WHERE organization_id IS NULL AND change_reason = :r").bindparams(r=REASON)
    )
