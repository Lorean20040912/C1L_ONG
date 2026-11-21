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
    assert run.steps[0]["status"] == "done" and run.steps[0]["entries"] == 1
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
    assert [s["implemented"] for s in state["steps"]].count(True) == 7

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
    assert state["steps"][0]["status"] == "done"
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


# ───────────── venituri din mijloace cu destinație specială, verificări ─────────────


def _manual_expense(db, org, acc, grant, user, amount="500", doc_date=date(2026, 4, 15)):
    from app.core.enums import DocumentType
    from app.documents.models import Document
    from app.posting.engine import LineInput, post_document

    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number="OM-1", doc_date=doc_date)
    db.add(doc)
    db.flush()
    line = LineInput(
        debit_account_id=acc["716"].id, credit_account_id=acc["521"].id, amount=Decimal(amount), grant_id=grant.id
    )
    post_document(db, organization_id=org.id, document_id=doc.id, lines=[line], user_id=user.id)
    return doc


def test_veniturile_acopera_cheltuielile_lunii(db, ong):
    from app.month_close.service import preview_step, revert_step, run_step

    user, org, acc, grant, bl, supplier = ong
    _manual_expense(db, org, acc, grant, user)  # operațiune manuală: 716 fără 537/616
    result = run_step(db, org.id, 2026, 4, "special_purpose_income", user.id)
    assert result.total == Decimal(500)
    step = next(s for s in get_run(db, org.id, 2026, 4).steps if s["step"] == "special_purpose_income")
    assert codes(db, step["document_id"]) == [("537", "616", Decimal(500))]
    # repetarea nu dublează, iar previzualizarea ulterioară nu mai găsește diferențe
    run_step(db, org.id, 2026, 4, "special_purpose_income", user.id)
    assert codes(db, step["document_id"]) == [("537", "616", Decimal(500))]
    assert preview_step(db, org.id, 2026, 5, "special_purpose_income").rows == []
    revert_step(db, org.id, 2026, 4, "special_purpose_income", user.id)
    assert codes(db, step["document_id"]) == []
    assert turnover_differences(db, org.id) == []


def test_factura_din_grant_nu_cere_venit_suplimentar(db, ong):
    from app.month_close.service import preview_step

    user, org, _, _, bl, supplier = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="Internet", amount=Decimal(300), line_kind=LineKind.service, budget_line_id=bl["2.1"].id)],
        doc_date=date(2026, 4, 2),
    )
    post_invoice(db, org.id, doc.id, user.id)
    assert preview_step(db, org.id, 2026, 4, "special_purpose_income").total == 0


def test_verificarile_lunii(client, db, ong):
    from app.core.enums import DocumentType
    from app.documents.models import Document

    user, org, acc, grant, bl, supplier = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}/month-close/2026/4/steps/checks"
    db.add(Document(organization_id=org.id, type=DocumentType.other, doc_number="NEINREG", doc_date=date(2026, 4, 20)))
    db.flush()
    preview = client.post(f"{base}/preview", headers=h).json()
    assert any("NEINREG" in e for e in preview["errors"])
    state = client.post(f"{base}/run", headers=h).json()
    step = next(s for s in state["steps"] if s["step"] == "checks")
    assert step["status"] == "error" and step["issues"]
    # 716/521: 521 (pasiv) are sold creditor — corect, deci nu e semnalat
    _manual_expense(db, org, acc, grant, user)
    assert not any("Contul 521" in e for e in client.post(f"{base}/preview", headers=h).json()["errors"])
    assert (
        client.post(f"/organizations/{org.id}/month-close/2026/4/steps/nu_exista/preview", headers=h).status_code == 404
    )


def test_verificarile_trec_pe_o_luna_curata(db, ong):
    from app.month_close.service import run_step

    user, org, _, _, bl, supplier = ong
    result = run_step(db, org.id, 2026, 6, "checks", user.id)
    assert result.errors == [] and result.rows[0].label == "Toate verificările au trecut"


def test_inchiderea_conturilor_6_7_la_331(db, ong):
    from app.month_close.service import preview_step, revert_step, run_step
    from app.posting.models import EntryLine
    from tests.conftest import make_accounts

    user, org, acc, grant, bl, supplier = ong
    assert run_step_error(db, org, user)  # fără 331 pasul se oprește cu mesaj clar
    make_accounts(db, org, "331")
    _manual_expense(db, org, acc, grant, user, amount="500")  # Dt 716 / Kt 521, fără venit
    run_step(db, org.id, 2026, 4, "special_purpose_income", user.id)  # Dt 537 / Kt 616 = 500
    result = preview_step(db, org.id, 2026, 4, "account_closing")
    pairs = {(r.debit_account, r.credit_account, r.amount) for r in result.rows}
    assert pairs == {("616", "331", Decimal(500)), ("331", "716", Decimal(500))}
    run_step(db, org.id, 2026, 4, "account_closing", user.id)
    # după închidere conturile 6/7 sunt pe zero, iar o nouă previzualizare dă același plan (pasul se exclude)
    assert {(r.debit_account, r.credit_account) for r in preview_step(db, org.id, 2026, 4, "account_closing").rows} == {
        ("616", "331"),
        ("331", "716"),
    }
    step = next(s for s in get_run(db, org.id, 2026, 4).steps if s["step"] == "account_closing")
    revert_step(db, org.id, 2026, 4, "account_closing", user.id)
    assert codes(db, step["document_id"]) == []


def run_step_error(db, org, user):
    from app.month_close.service import preview_step

    return any("331" in e for e in preview_step(db, org.id, 2026, 4, "account_closing").errors)
