"""Factura primită și ordinul de plată: de la rânduri la înregistrări.

ToR, criteriul 11: o factură cu un mijloc fix, OMVSD și materiale se introduce o
singură dată; mijlocul fix apare în fișa mijloacelor fixe.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.bank.models import BankAccount
from app.catalogs.models import Account, Counterparty
from app.core.enums import DocumentType, LineKind, PaymentDirection, SubcontoType
from app.documents.models import Document, Invoice, InvoiceLine, PaymentOrder, PaymentOrderLine
from app.documents.posting import post_invoice, post_payment, preview_invoice, unpost_invoice
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, Grant
from app.posting.engine import PostingError, turnover_differences
from app.posting.models import AccountingPolicy, EntryLine, EntryLineAnalytics
from tests.conftest import make_accounts, make_org, make_user

CHART = (
    "123", "124", "211", "213", "234.4", "242", "243", "3411", "425",
    "521", "535", "537", "616", "617", "716", "717", "718",
)  # fmt: skip
D = date(2026, 11, 3)


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, *CHART)
    db.add(
        AccountingPolicy(
            organization_id=org.id,
            valid_from=date(2026, 1, 1),
            grant_receivable_account_id=acc["234.4"].id,
            grant_recognition="on_signing",
        )
    )
    project = Grant(
        organization_id=org.id,
        code="SOR-2026-01",
        title="Proiect Soros",
        funding_type="grant",
        currency="MDL",
        total_amount=Decimal(200000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    own = Grant(
        organization_id=org.id,
        code="COT",
        title="Cotizații membri",
        funding_type="cotizații",
        currency="MDL",
        total_amount=Decimal(10000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    db.add_all([project, own])
    db.flush()
    lines = {
        "2.1": BudgetLine(grant_id=project.id, code="2.1", name="Echipament", planned_amount=Decimal(50000)),
        "4.2": BudgetLine(grant_id=project.id, code="4.2", name="Rechizite", planned_amount=Decimal(5000)),
        "3.2": BudgetLine(grant_id=project.id, code="3.2", name="Comunicații", planned_amount=Decimal(3000)),
        "C1": BudgetLine(grant_id=own.id, code="1", name="Administrare", planned_amount=Decimal(10000)),
    }
    supplier = Counterparty(organization_id=org.id, name="„Birotica Plus” SRL", idno="1003600000001")
    bank = BankAccount(
        organization_id=org.id, iban_enc="MD00AG000000022510000000", currency="MDL", account_id=acc["242"].id
    )
    db.add_all([*lines.values(), supplier, bank])
    db.flush()
    return user, org, acc, project, lines, supplier, bank


def make_invoice(db, org, supplier, rows, doc_date=D) -> Document:
    doc = Document(
        organization_id=org.id,
        type=DocumentType.invoice,
        doc_number="AA0001234",
        doc_date=doc_date,
        counterparty_id=supplier.id,
        total_amount=sum(Decimal(r["amount"]) for r in rows),
    )
    db.add(doc)
    db.flush()
    invoice = Invoice(document_id=doc.id, series="AA")
    invoice.lines = [InvoiceLine(position=i, **r) for i, r in enumerate(rows)]
    db.add(invoice)
    db.flush()
    return doc


def entries(db, doc):
    code = dict(db.execute(select(Account.id, Account.code)).all())
    rows = db.scalars(select(EntryLine).where(EntryLine.document_id == doc.id).order_by(EntryLine.line_no))
    return [(code[e.debit_account_id], code[e.credit_account_id], e.amount) for e in rows]


def test_factura_cu_randuri_de_tipuri_diferite(db, ong):
    user, org, _, project, bl, supplier, _ = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [
            dict(
                description="Laptop Dell",
                amount=Decimal(15000),
                line_kind=LineKind.fixed_asset,
                budget_line_id=bl["2.1"].id,
            ),
            dict(
                description="Scaun birou",
                amount=Decimal(900),
                line_kind=LineKind.low_value_item,
                budget_line_id=bl["4.2"].id,
            ),
            dict(
                description="Hârtie A4", amount=Decimal(570), line_kind=LineKind.material, budget_line_id=bl["4.2"].id
            ),
            dict(
                description="Internet",
                amount=Decimal("612.40"),
                line_kind=LineKind.service,
                budget_line_id=bl["3.2"].id,
            ),
        ],
    )
    post_invoice(db, org.id, doc.id, user.id)
    assert entries(db, doc) == [
        ("123", "521", Decimal(15000)),  # mijlocul fix
        ("537", "3411", Decimal(15000)),  # fondul de active imobilizate (proiect până la 31.12 → 537)
        ("716", "521", Decimal(900)),  # OMVSD dat în exploatare
        ("537", "616", Decimal(900)),
        ("211", "521", Decimal(570)),  # materialele intră în stoc
        ("716", "521", Decimal("612.40")),  # serviciul
        ("537", "616", Decimal("612.40")),
    ]
    assert turnover_differences(db, org.id) == []

    # fișa mijlocului fix creată automat, legată de rând, grant și factură
    asset = db.scalar(select(FixedAsset).where(FixedAsset.document_id == doc.id))
    assert asset.name == "Laptop Dell" and asset.initial_cost == Decimal(15000)
    assert asset.grant_id == project.id and asset.inventory_no == "MF-00001"
    assert asset.commissioning_date == D and asset.depreciation_start == date(2026, 12, 1)
    line = db.scalar(select(InvoiceLine).where(InvoiceLine.line_kind == LineKind.fixed_asset))
    assert line.fixed_asset_id == asset.id

    # furnizorul ca analitică pe 521
    refs = db.scalars(
        select(EntryLineAnalytics.ref_id).where(EntryLineAnalytics.subconto_type == SubcontoType.counterparty)
    )
    assert set(refs) == {supplier.id}


def test_reinregistrarea_si_anularea_refac_fisa_mf(db, ong):
    user, org, _, _, bl, supplier, _ = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [
            dict(
                description="Laptop", amount=Decimal(15000), line_kind=LineKind.fixed_asset, budget_line_id=bl["2.1"].id
            )
        ],
    )
    post_invoice(db, org.id, doc.id, user.id)
    post_invoice(db, org.id, doc.id, user.id)
    assert len(db.scalars(select(FixedAsset).where(FixedAsset.document_id == doc.id)).all()) == 1
    unpost_invoice(db, org.id, doc.id, user.id)
    assert db.scalars(select(FixedAsset).where(FixedAsset.document_id == doc.id)).all() == []
    assert entries(db, doc) == []


def test_cheltuiala_din_cotizatii_merge_pe_717(db, ong):
    user, org, _, _, bl, supplier, _ = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="Cafea", amount=Decimal(120), line_kind=LineKind.service, budget_line_id=bl["C1"].id)],
    )
    post_invoice(db, org.id, doc.id, user.id)
    assert entries(db, doc) == [("717", "521", Decimal(120))]


def test_contul_ales_pe_rand_si_mf_nepredestinat(db, ong):
    user, org, acc, _, bl, supplier, _ = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [
            dict(
                description="Scaun în depozit",
                amount=Decimal(900),
                line_kind=LineKind.low_value_item,
                put_into_use=False,
                account_id=acc["213"].id,
            ),
            dict(
                description="Imprimantă",
                amount=Decimal(4000),
                line_kind=LineKind.fixed_asset,
                budget_line_id=bl["C1"].id,
                put_into_use=False,
            ),
        ],
    )
    post_invoice(db, org.id, doc.id, user.id)
    # OMVSD care nu se dă în exploatare intră în stoc pe contul ales; MF din cotizații nu formează fond 3411
    assert entries(db, doc) == [("213", "521", Decimal(900)), ("123", "521", Decimal(4000))]
    asset = db.scalar(select(FixedAsset).where(FixedAsset.document_id == doc.id))
    assert asset.status == "suspended" and asset.depreciation_start is None


def test_serviciul_fara_linie_de_buget_e_respins(db, ong):
    user, org, _, _, _, supplier, _ = ong
    doc = make_invoice(db, org, supplier, [dict(description="Taxi", amount=Decimal(350), line_kind=LineKind.service)])
    with pytest.raises(PostingError, match="linia de buget"):
        post_invoice(db, org.id, doc.id, user.id)


def test_politica_stocuri_integral_la_535(db, ong):
    user, org, _, _, bl, supplier, _ = ong
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.organization_id == org.id))
    policy.stock_to_deferred_income = "all"
    db.flush()
    doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="Hârtie", amount=Decimal(570), line_kind=LineKind.material, budget_line_id=bl["4.2"].id)],
    )
    assert [g.rule.operation for g in preview_invoice(db, org.id, doc.id)] == ["stock_receipt", "deferred_income"]


def test_linia_de_buget_a_altei_organizatii(db, ong):
    user, org, _, _, _, supplier, _ = ong
    other_user = make_user(db, "b@exemplu.md")
    other = make_org(db, other_user, "AO Beta")
    foreign = Grant(
        organization_id=other.id, code="X", title="X", currency="MDL", total_amount=Decimal(1), start_date=D, end_date=D
    )
    db.add(foreign)
    db.flush()
    foreign_line = BudgetLine(grant_id=foreign.id, code="1", name="X", planned_amount=Decimal(1))
    db.add(foreign_line)
    db.flush()
    doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="X", amount=Decimal(1), line_kind=LineKind.service, budget_line_id=foreign_line.id)],
    )
    with pytest.raises(PostingError, match="nu aparține"):
        post_invoice(db, org.id, doc.id, user.id)


# ───────────────────────── ordinul de plată ─────────────────────────


def make_payment(db, org, bank, amount, direction=PaymentDirection.outgoing, counterparty=None, **kw) -> Document:
    doc = Document(
        organization_id=org.id,
        type=DocumentType.payment_order,
        doc_number="15",
        doc_date=D,
        total_amount=Decimal(amount),
        currency=kw.pop("currency", None),
        counterparty_id=counterparty.id if counterparty else None,
    )
    db.add(doc)
    db.flush()
    lines = kw.pop("lines", [])
    order = PaymentOrder(
        document_id=doc.id, direction=direction, bank_account_id=bank.id, purpose="Plata facturii", **kw
    )
    order.lines = lines
    db.add(order)
    db.flush()
    return doc


def test_plata_furnizorului(db, ong):
    user, org, _, _, bl, supplier, bank = ong
    invoice_doc = make_invoice(
        db,
        org,
        supplier,
        [dict(description="Internet", amount=Decimal(600), line_kind=LineKind.service, budget_line_id=bl["3.2"].id)],
    )
    invoice = db.scalar(select(Invoice).where(Invoice.document_id == invoice_doc.id))
    doc = make_payment(db, org, bank, "600", invoice_id=invoice.id)
    post_payment(db, org.id, doc.id, user.id)
    assert entries(db, doc) == [("521", "242", Decimal(600))]
    # contrapartida luată din factura achitată
    ref = db.scalar(
        select(EntryLineAnalytics.ref_id)
        .join(EntryLine, EntryLine.id == EntryLineAnalytics.entry_line_id)
        .where(EntryLine.document_id == doc.id)
    )
    assert ref == supplier.id


def test_plata_in_valuta_din_contul_243(db, ong):
    user, org, acc, _, _, supplier, _ = ong
    eur = BankAccount(organization_id=org.id, iban_enc="MD00EUR", currency="EUR", account_id=acc["243"].id)
    db.add(eur)
    db.flush()
    doc = make_payment(db, org, eur, "100", counterparty=supplier, currency="EUR", exchange_rate=Decimal("19.5432"))
    post_payment(db, org.id, doc.id, user.id)
    assert entries(db, doc) == [("521", "243", Decimal("1954.32"))]
    line = db.scalar(select(EntryLine).where(EntryLine.document_id == doc.id))
    assert line.currency == "EUR" and line.currency_amount == Decimal(100)
    assert turnover_differences(db, org.id) == []


def test_plata_in_valuta_fara_curs(db, ong):
    user, org, acc, _, _, supplier, _ = ong
    eur = BankAccount(organization_id=org.id, iban_enc="MD00EUR", currency="EUR", account_id=acc["243"].id)
    db.add(eur)
    db.flush()
    doc = make_payment(db, org, eur, "100", counterparty=supplier, currency="EUR")
    with pytest.raises(PostingError, match="cursul BNM"):
        post_payment(db, org.id, doc.id, user.id)


def test_incasarea_transei_grantului(db, ong):
    user, org, _, project, _, _, bank = ong
    doc = make_payment(
        db,
        org,
        bank,
        "40000",
        direction=PaymentDirection.incoming,
        lines=[PaymentOrderLine(grant_id=project.id, amount=Decimal(40000))],
    )
    post_payment(db, org.id, doc.id, user.id)
    assert entries(db, doc) == [("242", "234.4", Decimal(40000))]


def test_incasare_fara_grant_si_plata_cumulata(db, ong):
    user, org, _, _, _, _, bank = ong
    doc = make_payment(db, org, bank, "10", direction=PaymentDirection.incoming)
    with pytest.raises(PostingError, match="fără grant"):
        post_payment(db, org.id, doc.id, user.id)
    tax = make_payment(db, org, bank, "10", kind="grouped_tax")
    with pytest.raises(PostingError, match="modulul salarii"):
        post_payment(db, org.id, tax.id, user.id)
