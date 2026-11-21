"""Execuția bugetului și avertismentul la depășire (ToR F6.2, docs/11 §2.8)."""

from datetime import date
from decimal import Decimal

import pytest

from app.catalogs.models import Counterparty
from app.core.enums import LineKind
from app.documents.posting import post_invoice, unpost_invoice
from app.grants.budget import check_document, execution
from app.grants.models import BudgetLine, Grant
from app.posting.models import AccountingPolicy
from tests.conftest import auth_headers, make_accounts, make_org, make_user
from tests.test_invoice_payment import make_invoice


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "123", "211", "234.4", "3411", "521", "537", "616", "716")
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
    db.add(grant)
    db.flush()
    lines = {
        "2.1": BudgetLine(grant_id=grant.id, code="2.1", name="Echipament", planned_amount=Decimal(20000)),
        "3.2": BudgetLine(grant_id=grant.id, code="3.2", name="Comunicații", planned_amount=Decimal(1000)),
    }
    supplier = Counterparty(organization_id=org.id, name="Furnizor")
    db.add_all([*lines.values(), supplier])
    db.flush()
    return user, org, grant, lines, supplier


def service(line, amount):
    return dict(description="Internet", amount=Decimal(amount), line_kind=LineKind.service, budget_line_id=line.id)


def test_executia_numara_fiecare_cheltuiala_o_singura_data(db, ong):
    """Serviciul generează 716/521 și 537/616; mijlocul fix 123/521 și 537/3411 — pe linie se numără doar cheltuiala."""
    user, org, grant, bl, supplier = ong
    doc = make_invoice(
        db,
        org,
        supplier,
        [
            dict(
                description="Laptop", amount=Decimal(15000), line_kind=LineKind.fixed_asset, budget_line_id=bl["2.1"].id
            ),
            service(bl["3.2"], "600"),
        ],
    )
    post_invoice(db, org.id, doc.id, user.id)
    rows = {r.code: r for r in execution(db, org.id, grant.id)}
    assert rows["2.1"].spent == Decimal(15000) and rows["2.1"].remaining == Decimal(5000)
    assert rows["3.2"].spent == Decimal(600) and rows["3.2"].over == Decimal(0)


def test_depasirea_da_avertisment_nu_blocheaza(db, ong):
    user, org, grant, bl, supplier = ong
    first = make_invoice(db, org, supplier, [service(bl["3.2"], "800")])
    post_invoice(db, org.id, first.id, user.id)
    assert check_document(db, org.id, first.id) == []
    second = make_invoice(db, org, supplier, [service(bl["3.2"], "350")])
    post_invoice(db, org.id, second.id, user.id)
    warnings = check_document(db, org.id, second.id)
    assert len(warnings) == 1
    assert warnings[0].spent == Decimal(1150) and warnings[0].over == Decimal(150)
    assert "SOR / 3.2" in warnings[0].message
    assert {r.code: r.over for r in execution(db, org.id)}["3.2"] == Decimal(150)
    # după anulare, depășirea dispare
    unpost_invoice(db, org.id, second.id, user.id)
    assert {r.code: r.over for r in execution(db, org.id)}["3.2"] == Decimal(0)


def test_executia_pana_la_data(db, ong):
    user, org, grant, bl, supplier = ong
    post_invoice(
        db, org.id, make_invoice(db, org, supplier, [service(bl["3.2"], "100")], doc_date=date(2026, 3, 1)).id, user.id
    )
    post_invoice(
        db, org.id, make_invoice(db, org, supplier, [service(bl["3.2"], "200")], doc_date=date(2026, 9, 1)).id, user.id
    )
    assert {r.code: r.spent for r in execution(db, org.id, date_to=date(2026, 6, 30))}["3.2"] == Decimal(100)


def test_api_executie_si_verificare_inainte_de_inregistrare(client, db, ong):
    user, org, grant, bl, supplier = ong
    h = auth_headers(user)
    body = {
        "doc_number": "1",
        "doc_date": "2026-11-05",
        "counterparty_id": str(supplier.id),
        "lines": [
            {"description": "Internet", "amount": "1200", "line_kind": "service", "budget_line_id": str(bl["3.2"].id)}
        ],
    }
    doc_id = client.post(f"/organizations/{org.id}/invoices", json=body, headers=h).json()["document_id"]
    # înainte de înregistrare: avertismentul se vede deja
    before = client.get(f"/organizations/{org.id}/invoices/{doc_id}/budget-check", headers=h).json()
    assert Decimal(before[0]["over"]) == 200
    r = client.post(f"/organizations/{org.id}/invoices/{doc_id}/post", headers=h)
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 2 and Decimal(r.json()["warnings"][0]["over"]) == 200
    rows = client.get(f"/organizations/{org.id}/budget-execution", params={"grant_id": str(grant.id)}, headers=h).json()
    line = next(x for x in rows if x["code"] == "3.2")
    assert [Decimal(line[k]) for k in ("planned", "spent", "remaining")] == [1000, 1200, -200]
    # izolarea: altă organizație nu vede execuția
    intrus = make_user(db, "intrus@exemplu.md")
    make_org(db, intrus, "AO Beta")
    assert client.get(f"/organizations/{org.id}/budget-execution", headers=auth_headers(intrus)).status_code == 404
