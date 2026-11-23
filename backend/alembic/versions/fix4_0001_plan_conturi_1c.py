"""Planul de conturi aliniat cu configurația 1C „Бухгалтерия для Молдовы + НКО” (v3.0.63.11).

Corecturi confirmate de planul de conturi din configurația 1C (`ChartOfAccounts.Хозрасчетный`):
- fondurile ONG sunt subconturile 341.2 (active imobilizate) și 341.3 (autofinanțare), nu „3411/3412”;
  se redenumesc în regulile standard, în conturile organizațiilor și în șabloane;
- șablonul `general` avea coduri greșite (111/113/114 → 112/123/124, 226 → 225, 522 → 523, 532 → 533,
  TVA 535 → 534.4, 333 pasiv); versiunea 2 a șabloanelor `ngo` și `general` le corectează;
- cotele TVA (20% / 8% / 0%) intră în `tax_rates`, ca date cu temei legal.

Revision ID: fix4_0001
Revises: mrg_0009
Create Date: 2026-11-23
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "fix4_0001"
down_revision = "mrg_0009"
branch_labels = None
depends_on = None

A, P = "active", "passive"
CHECK = " — de verificat de contabilul-șef"

# (cod vechi, cod nou, denumire nouă, tip nou) — fondurile ONG
FUND_RENAMES = [
    ("3411", "341.2", "Fonduri de active imobilizate", P),
    ("3412", "341.3", "Fonduri de autofinanțare", P),
]

# (cod vechi, denumire veche, cod nou, denumire nouă, tip nou) — șablonul `general`
GENERAL_FIXES = [
    ("111", "Imobilizări necorporale", "112", "Imobilizări necorporale în exploatare", A),
    ("113", "Mijloace fixe", "123", "Mijloace fixe", A),
    ("114", "Amortizarea mijloacelor fixe", "124", "Amortizarea mijloacelor fixe", P),
    ("226", "Creanțe ale bugetului", "225", "Creanțe ale bugetului", A),
    ("333", "Profit nerepartizat", "333", "Profit nerepartizat", P),
    ("522", "Avansuri primite", "523", "Avansuri primite curente", P),
    ("532", "Datorii privind asigurările sociale și medicale", "533", "Datorii privind asigurările sociale și medicale", P),
    ("535", "Datorii privind TVA", "534.4", "Datorii privind TVA", P),
]
GENERAL_ADD = [
    ("113", "Amortizarea imobilizărilor necorporale", P),
    ("226", "Creanțe ale personalului", A),
]
NGO_ADD = [
    ("112", "Imobilizări necorporale în exploatare", A),
    ("113", "Amortizarea imobilizărilor necorporale", P),
    ("341.1", "Contribuții inițiale ale fondatorilor", P),
    ("341.4", "Alte fonduri", P),
]

VAT_BASIS = "Codul fiscal, Titlul III (TVA), art. 96; enumerarea СтавкиНДС din configurația 1C" + CHECK
VAT_RATES = [
    ("VAT_STANDARD", 20, "Cota standard TVA 20%. " + VAT_BASIS),
    ("VAT_REDUCED", 8, "Cota redusă TVA 8%. " + VAT_BASIS),
    ("VAT_ZERO", 0, "Cota 0% (export, livrări scutite cu drept de deducere). " + VAT_BASIS),
]
VALID_FROM = date(2015, 1, 1)


def _new_template(code: str, accounts: list[dict]) -> list[dict]:
    by_code = {a["code"]: dict(a) for a in accounts}
    if code == "ngo":
        for old, new, name, kind in FUND_RENAMES:
            if old in by_code:
                by_code.pop(old)
                by_code[new] = {"code": new, "name": name, "kind": kind}
        if "224" in by_code:
            by_code["224"]["name"] = "Avansuri acordate curente"
        for c, n, k in NGO_ADD:
            by_code.setdefault(c, {"code": c, "name": n, "kind": k})
    elif code == "general":
        for old, old_name, new, name, kind in GENERAL_FIXES:
            if old in by_code and by_code[old]["name"] == old_name:
                by_code.pop(old)
                by_code[new] = {"code": new, "name": name, "kind": kind}
        for c, n, k in GENERAL_ADD:
            by_code.setdefault(c, {"code": c, "name": n, "kind": k})
    return list(by_code.values())


def upgrade() -> None:
    conn = op.get_bind()

    for old, new, name, _kind in FUND_RENAMES:
        for column in ("debit_account", "credit_account"):
            conn.execute(sa.text(f"UPDATE posting_rules SET {column} = :new WHERE {column} = :old"), {"old": old, "new": new})
        conn.execute(
            sa.text(
                "UPDATE accounts a SET code = :new, name = :name WHERE a.code = :old AND NOT EXISTS "
                "(SELECT 1 FROM accounts b WHERE b.organization_id = a.organization_id AND b.code = :new)"
            ),
            {"old": old, "new": new, "name": name},
        )

    for old, old_name, new, name, kind in GENERAL_FIXES:
        conn.execute(
            sa.text(
                "UPDATE accounts a SET code = :new, name = :name, account_kind = CAST(:kind AS account_kind) "
                "WHERE a.code = :old AND a.name = :old_name AND (a.code = :new OR NOT EXISTS "
                "(SELECT 1 FROM accounts b WHERE b.organization_id = a.organization_id AND b.code = :new))"
            ),
            {"old": old, "old_name": old_name, "new": new, "name": name, "kind": kind},
        )

    for code in ("ngo", "general"):
        row = conn.execute(
            sa.text("SELECT version, accounts FROM coa_templates WHERE code = :c ORDER BY version DESC LIMIT 1"), {"c": code}
        ).first()
        if row is None:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO coa_templates (id, code, version, valid_from, accounts) "
                "VALUES (:id, :c, :v, :vf, CAST(:a AS jsonb))"
            ),
            {"id": uuid.uuid4(), "c": code, "v": row.version + 1, "vf": date(2026, 11, 23), "a": json.dumps(_new_template(code, row.accounts))},
        )

    for code, value, basis in VAT_RATES:
        conn.execute(
            sa.text(
                "INSERT INTO tax_rates (id, code, applies_to, value, is_percent, valid_from, legal_basis) "
                "VALUES (:id, :code, NULL, :value, true, :vf, :basis) ON CONFLICT DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "value": value, "vf": VALID_FROM, "basis": basis},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM tax_rates WHERE code IN ('VAT_STANDARD', 'VAT_REDUCED', 'VAT_ZERO') AND valid_from = :vf"), {"vf": VALID_FROM})
    conn.execute(sa.text("DELETE FROM coa_templates WHERE code IN ('ngo', 'general') AND version > 1 AND valid_from = :vf"), {"vf": date(2026, 11, 23)})
    for old, new, _name, _kind in FUND_RENAMES:
        for column in ("debit_account", "credit_account"):
            conn.execute(sa.text(f"UPDATE posting_rules SET {column} = :old WHERE {column} = :new"), {"old": old, "new": new})
        conn.execute(sa.text("UPDATE accounts SET code = :old WHERE code = :new"), {"old": old, "new": new})
