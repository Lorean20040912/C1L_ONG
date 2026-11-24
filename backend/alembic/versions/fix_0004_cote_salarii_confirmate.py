"""Cotele de salarizare confirmate: dispare marcajul „de verificat” din `legal_basis`.

Valorile nu se schimbă; se actualizează doar temeiul legal al cotelor confirmate
(12% impozit, CNAM 9%, CNAS 24%, scutirile 29700 / 30000 / 9900 / 30000, reținerea 7%).
Cotele neconfirmate încă (PLs, DON pf, DOB, ROY) rămân marcate.

Revision ID: fix_0004
Revises: mrg_0008
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "fix_0004"
down_revision = "mrg_0008"
branch_labels = None
depends_on = None

CHECK = " — de verificat de contabilul-șef"

# (code, applies_to) — cotele din sal_0002 confirmate de utilizator
CONFIRMED = [
    ("INCOME_TAX", "cim"),
    ("INCOME_TAX", "civil"),
    ("CNAM_EMPLOYEE", None),
    ("CNAS_EMPLOYER", None),
    ("PERSONAL_EXEMPTION_YEAR", "cim"),
    ("MAJOR_PERSONAL_EXEMPTION_YEAR", "cim"),
    ("DEPENDENT_EXEMPTION_YEAR", "cim"),
    ("DISABLED_DEPENDENT_EXEMPTION_YEAR", "cim"),
    ("WITHHOLDING_FOL", None),
    ("WITHHOLDING_PL", None),
]

WHERE = (
    "WHERE code = :code AND applies_to IS NOT DISTINCT FROM CAST(:applies AS contract_type) "
    "AND legal_basis {cond} :suffix"
)


def upgrade() -> None:
    for code, applies in CONFIRMED:
        op.execute(
            sa.text(
                "UPDATE tax_rates SET legal_basis = left(legal_basis, length(legal_basis) - length(:suffix)) "
                + WHERE.format(cond="LIKE '%' ||")
            ).bindparams(code=code, applies=applies, suffix=CHECK)
        )


def downgrade() -> None:
    for code, applies in CONFIRMED:
        op.execute(
            sa.text(
                "UPDATE tax_rates SET legal_basis = legal_basis || :suffix "
                "WHERE code = :code AND applies_to IS NOT DISTINCT FROM CAST(:applies AS contract_type) "
                "AND legal_basis NOT LIKE '%' || :suffix"
            ).bindparams(code=code, applies=applies, suffix=CHECK)
        )
