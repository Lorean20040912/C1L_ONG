"""Regulile din posting_rules: fiecare situație din docs/11 ca test (§6 p.4).

Documentul de test → operațiunile lui → înregistrările așteptate (Dt, Kt, sumă).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalogs.models import Account
from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants.models import Grant
from app.posting.engine import PostingError, post_document, turnover_differences
from app.posting.models import AccountingPolicy, EntryLine, PostingRule
from app.posting.rules import OperationInput, build_lines
from tests.conftest import make_accounts, make_org, make_user

CHART = (
    "123", "124", "211", "234", "234.4", "242", "3411", "3412", "425",
    "521", "535", "537", "616", "617", "713", "716", "717", "718",
)  # fmt: skip

D = date(2026, 3, 10)


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, *CHART)
    grant = Grant(
        organization_id=org.id,
        code="SOR-2026-01",
        title="Proiect",
        currency="MDL",
        total_amount=Decimal(120000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    db.add(grant)
    db.add(
        AccountingPolicy(
            organization_id=org.id,
            valid_from=date(2026, 1, 1),
            grant_receivable_account_id=acc["234.4"].id,
            grant_recognition="on_signing",
        )
    )
    db.flush()
    return user, org, acc, grant


def codes(db, lines):
    names = dict(db.execute(select(Account.id, Account.code)).all())
    return [(names[g.line.debit_account_id], names[g.line.credit_account_id], g.line.amount) for g in lines]


def build(db, org, document_type, *ops, doc_date=D):
    return build_lines(db, organization_id=org.id, document_type=document_type, doc_date=doc_date, operations=list(ops))


def op(operation, amount, grant=None, **attributes):
    return OperationInput(operation=operation, amount=Decimal(amount), attributes=attributes, grant_id=grant)


# ───────────── situațiile din docs/11 ─────────────


def test_recunoasterea_grantului_la_semnare(db, ong):
    _, org, _, grant = ong
    lines = build(
        db,
        org,
        "grant_income",
        op("recognition", "100000", grant.id, term="long"),
        op("recognition", "20000", grant.id, term="current"),
    )
    assert codes(db, lines) == [("234.4", "425", Decimal(100000)), ("234.4", "537", Decimal(20000))]
    assert lines[0].rule.source_ref == "IM188; ART sit.1"


def test_transa_la_semnare_stinge_creanta(db, ong):
    _, org, _, grant = ong
    lines = build(db, org, "grant_income", op("tranche_received", "40000", grant.id))
    assert codes(db, lines) == [("242", "234.4", Decimal(40000))]


def test_transa_cand_contractul_nu_e_autentificat(db, ong):
    """Varianta B [SEM]: politica „on_receipt” schimbă formula fără alt cod."""
    _, org, _, grant = ong
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.organization_id == org.id))
    policy.grant_recognition = "on_receipt"
    db.flush()
    lines = build(db, org, "grant_income", op("tranche_received", "40000", grant.id))
    assert codes(db, lines) == [("242", "537", Decimal(40000))]


def test_cheltuiala_din_grant_recunoaste_si_venitul(db, ong):
    _, org, _, grant = ong
    lines = build(
        db,
        org,
        "invoice",
        op("expense", "612.40", grant.id, funding="special_purpose"),
        op("income_recognition", "612.40", grant.id, funding="special_purpose"),
    )
    assert codes(db, lines) == [("716", "521", Decimal("612.40")), ("537", "616", Decimal("612.40"))]
    assert all(g.line.activity_type == "special_purpose" for g in lines)


def test_cheltuiala_nepredestinata_si_economica(db, ong):
    _, org, _, grant = ong
    lines = build(
        db,
        org,
        "invoice",
        op("expense", "100", grant.id, funding="unrestricted"),
        op("expense", "50", funding="economic"),
    )
    assert codes(db, lines) == [("717", "521", Decimal(100)), ("718", "521", Decimal(50))]
    assert lines[1].line.activity_type == "economic"


def test_stocuri_distribuite_partial(db, ong):
    """[ART sit.2]: intrare 211, distribuire 716/537→616, restul la 535, apoi 535→616."""
    _, org, _, grant = ong
    receipt = build(
        db,
        org,
        "invoice",
        op("stock_receipt", "1000"),
        op("deferred_income", "400", grant.id, funding="special_purpose"),
    )
    assert codes(db, receipt) == [("211", "521", Decimal(1000)), ("537", "535", Decimal(400))]
    distribution = build(
        db,
        org,
        "stock_distribution",
        op("expense", "600", grant.id, funding="special_purpose"),
        op("income_recognition", "600", grant.id, funding="special_purpose"),
        op("expense", "400", grant.id, funding="special_purpose"),
        op("income_recognition", "400", grant.id, funding="special_purpose", income_from="deferred"),
    )
    assert codes(db, distribution) == [
        ("716", "211", Decimal(600)),
        ("537", "616", Decimal(600)),
        ("716", "211", Decimal(400)),
        ("535", "616", Decimal(400)),
    ]


def test_mijloc_fix_din_grant_si_amortizarea_pe_fond(db, ong):
    """[ART sit.3]: fondul 3411 se formează la intrare, amortizarea îl diminuează (nu merge pe 713/716)."""
    _, org, _, grant = ong
    lines = build(
        db,
        org,
        "invoice",
        op("fixed_asset_receipt", "36000"),
        op("fixed_asset_fund", "36000", grant.id, funding="special_purpose", term="current"),
    )
    assert codes(db, lines) == [("123", "521", Decimal(36000)), ("537", "3411", Decimal(36000))]
    depreciation = build(
        db, org, "month_close.depreciation", op("depreciation", "600", grant.id, funding="special_purpose")
    )
    assert codes(db, depreciation) == [("3411", "124", Decimal(600))]


def test_diferente_de_curs_si_mijloace_neutilizate(db, ong):
    _, org, _, grant = ong
    fx = build(
        db,
        org,
        "fx_difference",
        op("grant_receipt_unfavorable", "120", grant.id),
        op("payment_favorable", "30", grant.id),
    )
    assert codes(db, fx) == [("537", "234.4", Decimal(120)), ("521", "537", Decimal(30))]
    close = build(db, org, "grant_close", op("unused_to_own_funds", "250", grant.id, term="current"))
    assert codes(db, close) == [("537", "3412", Decimal(250))]
    refund = build(db, org, "payment_order", op("grant_refund", "250", grant.id))
    assert codes(db, refund) == [("537", "242", Decimal(250))]


def test_cotizatii(db, ong):
    _, org, _, _ = ong
    lines = build(
        db,
        org,
        "membership_fee",
        op("accrual", "200"),
        op("receipt", "150"),
        op("write_off", "50"),
    )
    assert codes(db, lines) == [("234", "617", Decimal(200)), ("242", "234", Decimal(150)), ("717", "234", Decimal(50))]


# ───────────── alegerea regulii ─────────────


def test_corectia_organizatiei_are_prioritate(db, ong):
    user, org, _, grant = ong
    db.add(
        PostingRule(
            organization_id=org.id,
            document_type="invoice",
            operation="expense",
            conditions={"funding": "unrestricted"},
            debit_account="713",
            credit_account="521",
            source_ref="SEM",
            valid_from=date(2026, 1, 1),
            changed_by=user.id,
            change_reason="cheltuieli administrative pe 713",
        )
    )
    db.flush()
    lines = build(db, org, "invoice", op("expense", "10", grant.id, funding="unrestricted"))
    assert codes(db, lines) == [("713", "521", Decimal(10))]
    # altă organizație folosește în continuare regula standard
    other_user = make_user(db, "b@exemplu.md")
    other = make_org(db, other_user, "AO Beta")
    make_accounts(db, other, "717", "521")
    other_grant = Grant(
        organization_id=other.id,
        code="G",
        title="G",
        currency="MDL",
        total_amount=Decimal(1),
        start_date=D,
        end_date=D,
    )
    db.add(other_grant)
    db.flush()
    assert codes(db, build(db, other, "invoice", op("expense", "10", other_grant.id, funding="unrestricted"))) == [
        ("717", "521", Decimal(10))
    ]


def test_valabilitatea_si_beta(db, ong):
    user, org, _, grant = ong
    common = dict(
        organization_id=org.id,
        document_type="membership_fee",
        operation="accrual",
        credit_account="617",
        source_ref="SEM",
        changed_by=user.id,
    )
    # regulă viitoare și regulă beta: niciuna nu se aplică la data D
    db.add(PostingRule(**common, debit_account="234.4", valid_from=date(2027, 1, 1)))
    db.add(PostingRule(**common, debit_account="242", valid_from=date(2026, 1, 1), release_id=uuid.uuid4()))
    db.flush()
    assert codes(db, build(db, org, "membership_fee", op("accrual", "1"))) == [("234", "617", Decimal(1))]
    assert codes(db, build(db, org, "membership_fee", op("accrual", "1"), doc_date=date(2027, 2, 1))) == [
        ("234.4", "617", Decimal(1))
    ]


def test_reguli_ambigue(db, ong):
    user, org, _, _ = ong
    for debit in ("713", "717"):
        db.add(
            PostingRule(
                organization_id=org.id,
                document_type="invoice",
                operation="stock_receipt",
                debit_account=debit,
                credit_account="521",
                source_ref="SEM",
                valid_from=date(2026, 1, 1),
                changed_by=user.id,
            )
        )
    db.flush()
    with pytest.raises(PostingError, match="ambigue"):
        build(db, org, "invoice", op("stock_receipt", "1"))


def test_erori_clare(db, ong):
    _, org, acc, grant = ong
    with pytest.raises(PostingError, match="Nu există regulă"):
        build(db, org, "invoice", op("expense", "1", grant.id))  # lipsește sursa de finanțare
    with pytest.raises(PostingError, match="lipsește grant"):
        build(db, org, "invoice", op("expense", "1", funding="special_purpose"))
    db.delete(acc["716"])
    db.flush()
    with pytest.raises(PostingError, match="Contul 716 lipsește"):
        build(db, org, "invoice", op("expense", "1", grant.id, funding="special_purpose"))


def test_fara_politica_contabila_nu_se_ghiceste_contul_creantei(db, ong):
    _, org, _, grant = ong
    db.delete(db.scalar(select(AccountingPolicy).where(AccountingPolicy.organization_id == org.id)))
    db.flush()
    with pytest.raises(PostingError, match="Politica contabilă"):
        build(db, org, "grant_income", op("recognition", "1", grant.id, term="long", grant_recognition="on_signing"))


# ───────────── de la reguli la înregistrare ─────────────


def test_regulile_se_inregistreaza_prin_motor(db, ong):
    user, org, _, grant = ong
    doc = Document(organization_id=org.id, type=DocumentType.invoice, doc_number="EF1", doc_date=D)
    db.add(doc)
    db.flush()
    generated = build(
        db,
        org,
        "invoice",
        op("expense", "612.40", grant.id, funding="special_purpose"),
        op("income_recognition", "612.40", grant.id, funding="special_purpose"),
    )
    post_document(db, organization_id=org.id, document_id=doc.id, lines=[g.line for g in generated], user_id=user.id)
    entries = db.scalars(select(EntryLine).where(EntryLine.document_id == doc.id)).all()
    assert len(entries) == 2
    assert all(e.grant_id == grant.id for e in entries)
    assert turnover_differences(db, org.id) == []
