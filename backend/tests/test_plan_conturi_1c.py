"""Planul de conturi și regulile de postare față de configurația 1C „Бухгалтерия для Молдовы + НКО” (v3.0.63.11).

`tests/data/plan_conturi_1c.json` = codurile și tipul (activ/pasiv/bifuncțional) din `ChartOfAccounts.Хозрасчетный`
(date predefinite ale configurației); aici verificăm că șabloanele de plan, regulile standard și cotele TVA nu se abat.
"""

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.features.models import CoaTemplate
from app.posting.models import PostingRule
from app.taxes.models import TaxRate

PLAN_1C: dict[str, str] = json.loads((Path(__file__).parent / "data" / "plan_conturi_1c.json").read_text())

# 331 (închiderea anului, fix_0001) e bifuncțional în aplicație: primește și pierderea, și profitul anului
TIP_DIFERIT_ADMIS = {"331"}


def _latest(db, code):
    return db.scalar(select(CoaTemplate).where(CoaTemplate.code == code).order_by(CoaTemplate.version.desc()))


def test_sabloanele_de_plan_au_conturi_si_tipuri_din_1c(db):
    for tpl_code in ("ngo", "general"):
        tpl = _latest(db, tpl_code)
        assert tpl.version >= 2, tpl_code
        codes = [a["code"] for a in tpl.accounts]
        assert len(codes) == len(set(codes)), f"{tpl_code}: coduri duplicate"
        for acc in tpl.accounts:
            assert acc["code"] in PLAN_1C, f"{tpl_code}: contul {acc['code']} nu există în planul 1C"
            if acc["code"] not in TIP_DIFERIT_ADMIS:
                assert acc["kind"] == PLAN_1C[acc["code"]], f"{tpl_code}: {acc['code']} are tipul {acc['kind']}"


def test_fondurile_ong_sunt_subconturile_341_2_si_341_3(db):
    ngo = {a["code"]: a for a in _latest(db, "ngo").accounts}
    assert {"341.1", "341.2", "341.3", "341.4"} <= set(ngo)
    assert not {"3411", "3412"} & set(ngo)
    general = {a["code"] for a in _latest(db, "general").accounts}
    assert {"123", "124", "112", "113", "225", "226", "523", "533", "534.4"} <= general
    assert not {"111", "114", "522", "532", "535"} & general  # codurile greșite din prima versiune


def test_regulile_standard_folosesc_doar_conturi_din_planul_1c(db):
    rules = db.scalars(select(PostingRule).where(PostingRule.organization_id.is_(None))).all()
    assert rules
    for rule in rules:
        for code in (rule.debit_account, rule.credit_account):
            if code.startswith("{"):  # cont ales în politica contabilă
                continue
            assert code in PLAN_1C, f"{rule.document_type}/{rule.operation}: contul {code} nu există în planul 1C"
    used = {c for r in rules for c in (r.debit_account, r.credit_account)}
    assert {"341.2", "341.3"} <= used and not {"3411", "3412"} & used


def test_reguli_cheie_ong_dupa_1c(db):
    def pairs(doc_type, operation):
        rows = db.scalars(
            select(PostingRule).where(
                PostingRule.organization_id.is_(None), PostingRule.document_type == doc_type, PostingRule.operation == operation
            )
        ).all()
        return {(r.debit_account, r.credit_account) for r in rows}

    assert ("341.2", "124") in pairs("month_close.depreciation", "depreciation")
    assert {("537", "341.2"), ("425", "341.2")} <= pairs("invoice", "fixed_asset_fund")
    assert {("537", "341.3"), ("425", "341.3")} <= pairs("grant_close", "unused_to_own_funds")
    assert ("537", "535") in pairs("invoice", "deferred_income")


def test_cotele_tva_din_1c(db):
    rates = {r.code: r.value for r in db.scalars(select(TaxRate).where(TaxRate.code.like("VAT_%")))}
    assert rates == {"VAT_STANDARD": Decimal(20), "VAT_REDUCED": Decimal(8), "VAT_ZERO": Decimal(0)}


def test_conturile_organizatiilor_nu_pastreaza_codurile_vechi(db):
    assert db.scalar(text("SELECT count(*) FROM accounts WHERE code IN ('3411', '3412')")) == 0
