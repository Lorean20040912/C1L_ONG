"""Amortizarea lunară și asistentul „Închiderea lunii”.

ToR, criteriul 11: mijlocul fix dintr-o factură apare în fișă și se amortizează
la închiderea lunii; pentru MF din grant Dt 3411 — Kt 124 (docs/11 §2.4).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalogs.models import Account, Counterparty
from app.core.enums import LineKind
from app.documents.posting import post_invoice
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, Grant
from app.month_close.depreciation import accumulated, plan
from app.month_close.service import get_run, revert_depreciation, run_depreciation
from app.posting.engine import PostingError, turnover_differences
from app.posting.models import AccountingPeriod, AccountingPolicy, EntryLine, PostingRule
from tests.conftest import auth_headers, make_accounts, make_org, make_user
from tests.test_invoice_payment import make_invoice


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "123", "124", "211", "234.4", "3411", "425", "521", "537", "616", "713", "716", "717")
    db.add(
        AccountingPolicy(
            organization_id=org.id, valid_from=date(2026, 1, 1), grant_receivable_account_id=acc["234.4"].id
        )
    )
    grant = Grant(
        organization_id=org.id,
        code="SOR",
        title="Proiect",
        funding_type="grant",
        currency="MDL",
        total_amount=Decimal(100000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    own = Grant(
        organization_id=org.id,
        code="COT",
        title="Cotizații",
        funding_type="cotizații",
        currency="MDL",
        total_amount=Decimal(10000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    db.add_all([grant, own])
    db.flush()
    lines = {
        "2.1": BudgetLine(grant_id=grant.id, code="2.1", name="Echipament", planned_amount=Decimal(50000)),
        "C": BudgetLine(grant_id=own.id, code="1", name="Administrare", planned_amount=Decimal(10000)),
    }
    supplier = Counterparty(organization_id=org.id, name="Furnizor")
    db.add_all([*lines.values(), supplier])
    db.flush()
    return user, org, acc, grant, lines, supplier


def buy_asset(db, org, user, supplier, line, amount="36000", life=36, doc_date=date(2026, 3, 10)):
    doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="Laptop", amount=Decimal(amount), line_kind=LineKind.fixed_asset, budget_line_id=line.id)],
        doc_date=doc_date,
    )
    post_invoice(db, org.id, doc.id, user.id)
    asset = db.scalar(select(FixedAsset).where(FixedAsset.document_id == doc.id))
    asset.useful_life_months = life
    db.flush()
    return asset


def codes(db, doc_id):
    code = dict(db.execute(select(Account.id, Account.code)).all())
    rows = db.scalars(select(EntryLine).where(EntryLine.document_id == doc_id).order_by(EntryLine.line_no))
    return [(code[e.debit_account_id], code[e.credit_account_id], e.amount) for e in rows]


def test_mf_din_factura_se_amortizeaza_pe_fond(db, ong):
    user, org, _, grant, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"])  # punere în funcțiune 10.03 → amortizare din aprilie
    assert plan(db, org.id, 2026, 3).rows == []
    run_depreciation(db, org.id, 2026, 4, user.id)
    run = get_run(db, org.id, 2026, 4)
    assert codes(db, run.document_id) == [("3411", "124", Decimal(1000))]
    line = db.scalar(select(EntryLine).where(EntryLine.document_id == run.document_id))
    assert line.grant_id == grant.id and line.entry_date == date(2026, 4, 30)
    assert accumulated(db, org.id, [asset.id]) == {asset.id: Decimal(1000)}
    assert run.status == "done" and run.steps[0]["entries"] == 1
    assert turnover_differences(db, org.id) == []


def test_repetarea_inlocuieste_si_anularea_sterge(db, ong):
    user, org, _, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"])
    run_depreciation(db, org.id, 2026, 4, user.id)
    run_depreciation(db, org.id, 2026, 4, user.id)  # a doua oară nu dublează
    assert accumulated(db, org.id, [asset.id])[asset.id] == Decimal(1000)
    revert_depreciation(db, org.id, 2026, 4, user.id)
    assert accumulated(db, org.id, [asset.id]) == {}
    assert get_run(db, org.id, 2026, 4).steps[0]["status"] == "reverted"
    with pytest.raises(PostingError, match="nu a fost executată"):
        revert_depreciation(db, org.id, 2026, 4, user.id)


def test_ultima_luna_ia_restul_rotunjirilor(db, ong):
    user, org, _, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"], amount="1000", life=3)  # 333,33 + 333,33 + 333,34
    for month in (4, 5, 6, 7):
        run_depreciation(db, org.id, 2026, month, user.id)
    amounts = [
        db.scalar(select(EntryLine.amount).where(EntryLine.document_id == get_run(db, org.id, 2026, m).document_id))
        for m in (4, 5, 6)
    ]
    assert amounts == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert accumulated(db, org.id, [asset.id])[asset.id] == Decimal(1000)
    # în iulie MF e amortizat integral — nimic de calculat
    assert get_run(db, org.id, 2026, 7).steps[0]["entries"] == 0


def test_valoarea_reziduala(db, ong):
    user, org, _, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"], amount="12000", life=10)
    asset.residual_value = Decimal(2000)
    db.flush()
    assert plan(db, org.id, 2026, 4).rows[0].amount == Decimal(1000)


def test_fara_durata_pasul_se_opreste_cu_eroare_clara(db, ong):
    user, org, _, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"])
    asset.useful_life_months = None
    db.flush()
    assert "durata" in plan(db, org.id, 2026, 4).errors[0]
    with pytest.raises(PostingError, match="durata"):
        run_depreciation(db, org.id, 2026, 4, user.id)


def test_mf_din_cotizatii_cere_regula_contabilului_sef(db, ong):
    """Pentru MF nepredestinate docs/11 nu dă contul; fără corecție pasul spune clar ce lipsește."""
    user, org, acc, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["C"], amount="12000", life=12)
    assert "Nu există regulă" in plan(db, org.id, 2026, 4).errors[0]
    db.add(
        PostingRule(
            organization_id=org.id,
            document_type="month_close.depreciation",
            operation="depreciation",
            conditions={"funding": "unrestricted"},
            debit_account="717",
            credit_account="124",
            source_ref="SEM",
            valid_from=date(2026, 1, 1),
        )
    )
    asset.expense_account_id = acc["713"].id  # contul de cheltuieli al fișei are prioritate
    db.flush()
    run_depreciation(db, org.id, 2026, 4, user.id)
    assert codes(db, get_run(db, org.id, 2026, 4).document_id) == [("713", "124", Decimal(1000))]


def test_perioada_inchisa_blocheaza_amortizarea(db, ong):
    user, org, _, _, bl, supplier = ong
    buy_asset(db, org, user, supplier, bl["2.1"])
    db.add(AccountingPeriod(organization_id=org.id, year=2026, month=4, is_closed=True))
    db.flush()
    with pytest.raises(PostingError, match="închisă"):
        run_depreciation(db, org.id, 2026, 4, user.id)


def test_api_inchiderea_lunii_si_fisele(client, db, ong):
    user, org, _, _, bl, supplier = ong
    asset = buy_asset(db, org, user, supplier, bl["2.1"], life=None)
    h = auth_headers(user)
    base = f"/organizations/{org.id}"

    state = client.get(f"{base}/month-close/2026/4", headers=h).json()
    assert state["status"] == "draft" and state["steps"][0]["step"] == "depreciation"
    assert [s["implemented"] for s in state["steps"]].count(True) == 1

    preview = client.post(f"{base}/month-close/2026/4/depreciation/preview", headers=h).json()
    assert preview["errors"] and preview["rows"][0]["error"]
    assert client.post(f"{base}/month-close/2026/4/depreciation/run", headers=h).status_code == 422

    # completarea fișei: durata
    r = client.patch(f"{base}/fixed-assets/{asset.id}", json={"useful_life_months": 36}, headers=h)
    assert r.status_code == 200 and r.json()["useful_life_months"] == 36
    preview = client.post(f"{base}/month-close/2026/4/depreciation/preview", headers=h).json()
    assert preview["errors"] == [] and preview["rows"][0]["debit_account"] == "3411"
    assert Decimal(preview["total"]) == 1000

    state = client.post(f"{base}/month-close/2026/4/depreciation/run", headers=h).json()
    assert state["status"] == "done" and state["steps"][0]["status"] == "done"
    assets = client.get(f"{base}/fixed-assets", headers=h).json()
    assert Decimal(assets[0]["accumulated"]) == 1000 and Decimal(assets[0]["book_value"]) == 35000

    # Dt/Kt al închiderii, prin documentul-registrator
    entries = client.get(f"{base}/documents/{state['document_id']}/entries", headers=h).json()
    assert len(entries) == 1

    assert (
        client.post(f"{base}/month-close/2026/4/depreciation/revert", headers=h).json()["steps"][0]["status"]
        == "reverted"
    )
    assert (
        client.patch(f"{base}/fixed-assets/{asset.id}", json={"residual_value": "40000"}, headers=h).status_code == 422
    )

    intrus = make_user(db, "intrus@exemplu.md")
    make_org(db, intrus, "AO Beta")
    assert client.get(f"{base}/fixed-assets", headers=auth_headers(intrus)).status_code == 404
