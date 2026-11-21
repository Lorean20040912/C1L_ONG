"""Profiluri de funcționalitate, șabloane de plan de conturi, partida simplă (docs/13).

Revision ID: prf_0001
Revises: 0005
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "prf_0001"
down_revision = "0005"
branch_labels = None
depends_on = None

A, P, AP = "active", "passive", "active_passive"

# (cod, denumire, tip) — conturile folosite de regulile standard ONG (docs/11)
NGO_ACCOUNTS = [
    ("123", "Mijloace fixe", A),
    ("124", "Amortizarea mijloacelor fixe", P),
    ("211", "Materiale", A),
    ("224", "Creanțe comerciale pe termen scurt", A),
    ("234", "Creanțe curente privind alte operațiuni", A),
    ("234.4", "Creanțe privind mijloacele cu destinație specială", A),
    ("241", "Casa", A),
    ("242", "Conturi curente în monedă națională", A),
    ("243", "Conturi curente în valută străină", A),
    ("3411", "Fonduri de active imobilizate", P),
    ("3412", "Fonduri de autofinanțare", P),
    ("425", "Finanțări și încasări cu destinație specială pe termen lung", P),
    ("521", "Datorii comerciale curente", P),
    ("531", "Datorii față de personal", P),
    ("533", "Datorii privind asigurările", P),
    ("534", "Datorii față de buget", P),
    ("535", "Venituri anticipate curente", P),
    ("537", "Finanțări și încasări cu destinație specială curente", P),
    ("544", "Alte datorii curente", P),
    ("616", "Venituri aferente mijloacelor cu destinație specială", P),
    ("617", "Venituri ale organizației", P),
    ("618", "Venituri din activitatea economică", P),
    ("713", "Cheltuieli administrative", A),
    ("716", "Cheltuieli aferente mijloacelor cu destinație specială", A),
    ("717", "Cheltuieli ale organizației", A),
    ("718", "Cheltuieli din activitatea economică", A),
]

GENERAL_ACCOUNTS = [
    ("111", "Imobilizări necorporale", A),
    ("113", "Mijloace fixe", A),
    ("114", "Amortizarea mijloacelor fixe", P),
    ("211", "Materiale", A),
    ("217", "Mărfuri", A),
    ("221", "Creanțe comerciale pe termen scurt", A),
    ("224", "Avansuri acordate", A),
    ("226", "Creanțe ale bugetului", A),
    ("241", "Casa", A),
    ("242", "Conturi curente în monedă națională", A),
    ("243", "Conturi curente în valută străină", A),
    ("311", "Capital social", P),
    ("333", "Profit nerepartizat", AP),
    ("521", "Datorii comerciale pe termen scurt", P),
    ("522", "Avansuri primite", P),
    ("531", "Datorii față de personal", P),
    ("532", "Datorii privind asigurările sociale și medicale", P),
    ("534", "Datorii față de buget", P),
    ("535", "Datorii privind TVA", P),
    ("611", "Venituri din vânzări", P),
    ("711", "Costul vânzărilor", A),
    ("712", "Cheltuieli comerciale", A),
    ("713", "Cheltuieli generale și administrative", A),
    ("731", "Cheltuieli privind impozitul pe venit", A),
]

TEMPLATES = {"ngo": NGO_ACCOUNTS, "general": GENERAL_ACCOUNTS, "ii_single_entry": []}

NGO_TYPES = ["ngo_association", "ngo_foundation", "ngo_other"]
DOUBLE_TYPES = ["srl", "sa", "other", *NGO_TYPES]

# modules.sections = secțiunile din bara din stânga; modules.screens = linkurile din panouri
FEATURES = [
    ("ngo_grants", "Granturi și activitate necomercială",
     {"sections": ["ngo"], "screens": ["Execuția bugetului", "ONG17", "5-CON", "Proiecte / granturi", "Linii de buget",
                                        "Articole de cheltuieli", "Date pentru rapoarte"]},
     {"entity_types": NGO_TYPES}),
    ("double_entry", "Partidă dublă",
     {"sections": ["ops"], "screens": ["Operațiune manuală", "Balanța de verificare (OSV)", "Fișa contului",
                                        "Analiza contului", "Planul de conturi", "Politica contabilă",
                                        "Reguli de înregistrare", "Închiderea lunii"]},
     {"entity_types": DOUBLE_TYPES}),
    ("single_entry", "Partidă simplă (registru-jurnal)",
     {"sections": [], "screens": ["Registru-jurnal (partidă simplă)"]},
     {"entity_types": ["ii", "gt"]}),
    ("vat", "TVA", {"sections": [], "screens": ["TVA"]}, {"vat": True}),
    ("retail", "Comerț cu amănuntul", {"sections": ["stock"], "screens": []}, {"activities": ["retail"]}),
    ("wholesale", "Comerț cu ridicata", {"sections": ["stock"], "screens": []}, {"activities": ["wholesale"]}),
    ("catering", "Alimentație publică / fast-food", {"sections": ["stock"], "screens": []}, {"activities": ["catering"]}),
    ("production", "Producție", {"sections": ["stock"], "screens": []}, {"activities": ["production"]}),
    ("accommodation", "Cazare / turism", {"sections": [], "screens": []}, {"activities": ["accommodation"]}),
    ("agriculture", "Agricultură", {"sections": [], "screens": []}, {"activities": ["agriculture"]}),
    ("payroll", "Salarii și personal",
     {"sections": ["pay"], "screens": ["IPC21"]}, {"employees": True}),
    ("fixed_assets", "Mijloace fixe", {"sections": ["fa"], "screens": ["Fișa mijloacelor fixe"]}, {"always": True}),
]


def upgrade() -> None:
    op.create_table(
        "features",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("modules", pg.JSONB(), nullable=False),
        sa.Column("default_for", pg.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "organization_features",
        sa.Column("id", pg.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("feature_code", sa.String(), nullable=False),
        sa.Column("enabled_from", sa.Date(), nullable=False),
        sa.Column("enabled_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["feature_code"], ["features.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "feature_code", "enabled_from"),
    )
    op.create_table(
        "organization_tax_regimes",
        sa.Column("id", pg.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("regime_code", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("basis", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "valid_from"),
    )
    op.create_table(
        "coa_templates",
        sa.Column("id", pg.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("accounts", pg.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version"),
    )
    op.create_table(
        "simple_ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("document_id", pg.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("is_deductible", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_simple_ledger_entries_organization_id_entry_date", "simple_ledger_entries", ["organization_id", "entry_date"]
    )

    conn = op.get_bind()
    for code, name, modules, default_for in FEATURES:
        conn.execute(
            sa.text("INSERT INTO features (code, name, modules, default_for) VALUES (:c, :n, CAST(:m AS jsonb), CAST(:d AS jsonb))"),
            {"c": code, "n": name, "m": json.dumps(modules), "d": json.dumps(default_for)},
        )
    for code, accounts in TEMPLATES.items():
        payload = [{"code": c, "name": n, "kind": k} for c, n, k in accounts]
        conn.execute(
            sa.text(
                "INSERT INTO coa_templates (id, code, version, valid_from, accounts) "
                "VALUES (:id, :c, 1, :vf, CAST(:a AS jsonb))"
            ),
            {"id": uuid.uuid4(), "c": code, "vf": date(2015, 1, 1), "a": json.dumps(payload)},
        )

    # bazele existente păstrează ecranele de acum: pornim funcționalitățile potrivite tipului lor
    conn.execute(
        sa.text(
            "INSERT INTO organization_features (organization_id, feature_code, enabled_from) "
            "SELECT o.id, f.code, DATE '2015-01-01' FROM organizations o, features f "
            "WHERE f.code IN ('double_entry', 'payroll', 'fixed_assets') AND o.accounting_method = 'double_entry' "
            "UNION ALL SELECT o.id, 'ngo_grants', DATE '2015-01-01' FROM organizations o "
            "WHERE o.entity_type IN ('ngo_association', 'ngo_foundation', 'ngo_other') "
            "UNION ALL SELECT o.id, 'single_entry', DATE '2015-01-01' FROM organizations o "
            "WHERE o.accounting_method = 'single_entry'"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_simple_ledger_entries_organization_id_entry_date", table_name="simple_ledger_entries")
    for t in ("simple_ledger_entries", "coa_templates", "organization_tax_regimes", "organization_features", "features"):
        op.drop_table(t)
