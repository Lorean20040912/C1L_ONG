"""Cotele pentru salarii și reținerile la sursă (tax_rates), ca date cu temei legal.

Calculul ia cota valabilă la data operațiunii (ToR F4.1–F4.2); o cotă nouă =
un rând nou cu `valid_from`, cel vechi primește `valid_to`. Cotele marcate
„de verificat” în `legal_basis` trebuie confirmate de contabilul-șef
(nimic nu se aplică automat din surse externe — ToR F4.3).

Revision ID: sal_0002
Revises: sal_0001
Create Date: 2026-11-21
"""

import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "sal_0002"
down_revision = "sal_0001"
branch_labels = None
depends_on = None

CHECK = " — de verificat de contabilul-șef"

# (code, applies_to, value, is_percent, valid_from, legal_basis)
RATES = [
    ("INCOME_TAX", "cim", "12", True, date(2018, 1, 1), "Codul fiscal art. 15 lit. a) — salarii (cod SAL)"),
    (
        "INCOME_TAX",
        "civil",
        "12",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90 alin.(3¹) — plăți către persoane fizice (cod PL)" + CHECK,
    ),
    (
        "CNAM_EMPLOYEE",
        None,
        "9",
        True,
        date(2019, 1, 1),
        "Legea nr. 1593/2002 privind primele de asigurare obligatorie de asistență medicală — 9% reținută din salariu și alte recompense"
        + CHECK,
    ),
    (
        "CNAS_EMPLOYER",
        None,
        "24",
        True,
        date(2021, 1, 1),
        "Legea bugetului asigurărilor sociale de stat, anexa nr. 1 — contribuția angajatorului 24%" + CHECK,
    ),
    (
        "PERSONAL_EXEMPTION_YEAR",
        "cim",
        "29700",
        False,
        date(2024, 1, 1),
        "Codul fiscal art. 33 alin.(1) — scutirea personală anuală" + CHECK,
    ),
    (
        "MAJOR_PERSONAL_EXEMPTION_YEAR",
        "cim",
        "30000",
        False,
        date(2024, 1, 1),
        "Codul fiscal art. 34 — scutirea personală majoră anuală" + CHECK,
    ),
    (
        "DEPENDENT_EXEMPTION_YEAR",
        "cim",
        "9900",
        False,
        date(2024, 1, 1),
        "Codul fiscal art. 35 alin.(1) — scutirea pentru fiecare persoană întreținută" + CHECK,
    ),
    (
        "DISABLED_DEPENDENT_EXEMPTION_YEAR",
        "cim",
        "30000",
        False,
        date(2024, 1, 1),
        "Codul fiscal art. 35 alin.(2) — persoană întreținută cu dizabilitate" + CHECK,
    ),
    # reținerea la sursă pentru plățile către persoane fizice (documentul „Plată către persoană fizică”)
    (
        "WITHHOLDING_FOL",
        None,
        "7",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90¹ alin.(3) — locațiune / uzufruct (cod FOL)" + CHECK,
    ),
    (
        "WITHHOLDING_PLS",
        None,
        "0",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90 — venituri scutite de reținerea prealabilă, arenda terenurilor agricole (cod PLs)"
        + CHECK,
    ),
    (
        "WITHHOLDING_PL",
        None,
        "12",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90 alin.(3¹) — servicii prestate de persoane fizice (cod PL)" + CHECK,
    ),
    (
        "WITHHOLDING_DON_PF",
        None,
        "6",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90¹ alin.(3¹) — donații către persoane fizice (cod DON pf); [SEM] menționează 6%" + CHECK,
    ),
    (
        "WITHHOLDING_DOB",
        None,
        "3",
        True,
        date(2021, 1, 1),
        "Codul fiscal art. 90¹ alin.(3⁷) — dobânzi către persoane fizice rezidente (cod DOB)" + CHECK,
    ),
    (
        "WITHHOLDING_ROY",
        None,
        "12",
        True,
        date(2018, 1, 1),
        "Codul fiscal art. 90¹ alin.(3) — royalty către persoane fizice (cod ROY)" + CHECK,
    ),
]

tax_rates = sa.table(
    "tax_rates",
    sa.column("id", sa.UUID),
    sa.column("code", sa.String),
    sa.column("applies_to", postgresql.ENUM("cim", "civil", name="contract_type", create_type=False)),
    sa.column("value", sa.Numeric),
    sa.column("is_percent", sa.Boolean),
    sa.column("valid_from", sa.Date),
    sa.column("legal_basis", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(
        tax_rates,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "applies_to": applies_to,
                "value": value,
                "is_percent": is_percent,
                "valid_from": valid_from,
                "legal_basis": basis,
            }
            for code, applies_to, value, is_percent, valid_from, basis in RATES
        ],
    )


def downgrade() -> None:
    for code, applies_to, _, _, valid_from, _ in RATES:
        op.execute(
            sa.text(
                "DELETE FROM tax_rates WHERE code = :code AND valid_from = :vf "
                "AND applies_to IS NOT DISTINCT FROM CAST(:applies AS contract_type)"
            ).bindparams(code=code, vf=valid_from, applies=applies_to)
        )
