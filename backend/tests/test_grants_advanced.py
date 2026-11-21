"""Granturi avansat: donatori, versiuni de buget, tranșe, distribuirea stocurilor, repartizarea pe granturi."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalogs.models import Account, Counterparty
from app.core.enums import LineKind, UserRole
from app.documents.posting import post_invoice
from app.grants.budget import check_amounts, execution
from app.grants.models import Allocation, BudgetLine, Grant
from app.month_close.service import get_run, revert_step, run_step
from app.posting.models import AccountingPolicy, EntryLine
from tests.conftest import auth_headers, make_accounts, make_org, make_user
from tests.test_invoice_payment import make_invoice

D = date(2026, 4, 10)


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "211", "234.4", "242", "425", "521", "535", "537", "616", "716", "717")
    db.add(
        AccountingPolicy(
            organization_id=org.id, valid_from=date(2026, 1, 1), grant_receivable_account_id=acc["234.4"].id
        )
    )
    grant = Grant(
        organization_id=org.id, code="SOR", title="Proiect", funding_type="grant", currency="MDL",
        total_amount=Decimal(100000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )  # fmt: skip
    other = Grant(
        organization_id=org.id, code="UE", title="Alt proiect", funding_type="grant", currency="MDL",
        total_amount=Decimal(50000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )  # fmt: skip
    db.add_all([grant, other])
    db.flush()
    lines = {
        "2.1": BudgetLine(grant_id=grant.id, code="2.1", name="Echipament", planned_amount=Decimal(20000)),
        "3.2": BudgetLine(grant_id=grant.id, code="3.2", name="Comunicații", planned_amount=Decimal(1000)),
        "9.1": BudgetLine(grant_id=other.id, code="9.1", name="Chirie", planned_amount=Decimal(5000)),
    }
    supplier = Counterparty(organization_id=org.id, name="Furnizor")
    db.add_all([*lines.values(), supplier])
    db.flush()
    return user, org, acc, grant, other, lines, supplier


def codes(db, document_id):
    names = dict(db.execute(select(Account.id, Account.code)).all())
    rows = db.scalars(select(EntryLine).where(EntryLine.document_id == document_id).order_by(EntryLine.line_no))
    return [(names[e.debit_account_id], names[e.credit_account_id], e.amount, e.budget_line_id) for e in rows]


def buy_stock(db, org, user, supplier, line, amount="3000"):
    doc = make_invoice(
        db, org, supplier,
        [dict(description="Mobilier", amount=Decimal(amount), line_kind=LineKind.material, budget_line_id=line.id)],
        doc_date=D,
    )  # fmt: skip
    post_invoice(db, org.id, doc.id, user.id)
    return doc


# ───────────────────────── donatori ─────────────────────────


def test_donatori_si_donatorii_grantului(client, db, ong):
    user, org, _, grant, _, _, _ = ong
    h, base = auth_headers(user), f"/organizations/{org.id}"
    d = client.post(f"{base}/donors", json={"name": "Fundația X", "country": "MD"}, headers=h)
    assert d.status_code == 201
    assert client.post(f"{base}/donors", json={"name": "fundația x"}, headers=h).status_code == 409
    donor_id = d.json()["id"]
    r = client.put(
        f"{base}/grants/{grant.id}/donors",
        json=[{"donor_id": donor_id, "share_percent": "80", "amount": "80000"}],
        headers=h,
    )
    assert r.status_code == 200 and r.json()[0]["donor_name"] == "Fundația X"
    assert client.get(f"{base}/donors", headers=h).json()[0]["grants_count"] == 1
    assert client.delete(f"{base}/donors/{donor_id}", headers=h).status_code == 409
    too_much = [{"donor_id": donor_id, "amount": "100001"}]
    assert client.put(f"{base}/grants/{grant.id}/donors", json=too_much, headers=h).status_code == 422
    assert client.put(f"{base}/grants/{grant.id}/donors", json=[], headers=h).status_code == 200
    assert client.delete(f"{base}/donors/{donor_id}", headers=h).status_code == 204


def test_izolarea_pe_organizatii(client, db, ong):
    user, org, _, grant, _, bl, _ = ong
    stranger = make_user(db, "altul@exemplu.md")
    other_org = make_org(db, stranger, "AO Beta")
    h, base = auth_headers(stranger), f"/organizations/{other_org.id}"
    mine = f"/organizations/{org.id}"
    donor_id = client.post(f"{mine}/donors", json={"name": "Donator"}, headers=auth_headers(user)).json()["id"]
    assert client.get(f"/organizations/{org.id}/donors", headers=h).status_code == 404  # nu e membru
    assert client.put(f"{base}/donors/{donor_id}", json={"name": "Furat"}, headers=h).status_code == 404
    assert client.get(f"{base}/grants/{grant.id}/budget-versions", headers=h).status_code == 404
    assert client.get(f"{base}/grants/{grant.id}/tranches", headers=h).status_code == 404
    assert client.put(f"{base}/grants/{grant.id}/donors", json=[], headers=h).status_code == 404
    assert client.put(f"{base}/tranches/{grant.id}", json={"amount": "1"}, headers=h).status_code == 404
    # un donator străin nu se poate lega de grantul propriu
    own_grant = Grant(
        organization_id=other_org.id, code="X", title="X", currency="MDL", total_amount=Decimal(10),
        start_date=D, end_date=D,
    )  # fmt: skip
    db.add(own_grant)
    db.flush()
    r = client.put(f"{base}/grants/{own_grant.id}/donors", json=[{"donor_id": donor_id}], headers=h)
    assert r.status_code == 404
    assert client.post(f"{base}/stock-distributions/preview", headers=h, json={
        "doc_date": "2026-04-20", "grant_id": str(grant.id), "amount": "10", "description": "x"}).status_code == 404  # fmt: skip


def test_auditorul_nu_scrie(client, db, ong):
    user, org, *_ = ong
    auditor = make_user(db, "auditor@exemplu.md")
    from app.auth.models import OrganizationMember

    db.add(OrganizationMember(organization_id=org.id, user_id=auditor.id, role=UserRole.auditor))
    db.flush()
    base = f"/organizations/{org.id}"
    h = auth_headers(auditor)
    assert client.get(f"{base}/donors", headers=h).status_code == 200
    assert client.post(f"{base}/donors", json={"name": "X"}, headers=h).status_code == 403


# ──────────────────── versiuni de buget ────────────────────


def test_versiune_noua_pastreaza_istoricul_si_compara_cu_versiunea_in_vigoare(client, db, ong):
    user, org, _, grant, _, bl, supplier = ong
    h, base = auth_headers(user), f"/organizations/{org.id}"
    # cheltuială din aprilie pe linia 3.2 (plan 1000), înainte de modificare
    doc = make_invoice(
        db, org, supplier,
        [dict(description="Internet", amount=Decimal(800), line_kind=LineKind.service, budget_line_id=bl["3.2"].id)],
        doc_date=D,
    )  # fmt: skip
    post_invoice(db, org.id, doc.id, user.id)

    r = client.post(
        f"{base}/grants/{grant.id}/budget-versions",
        json={"valid_from": "2026-06-01", "changes": {"3.2": "3000"}},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["version"] == 2 and r.json()["is_current"]
    versions = client.get(f"{base}/grants/{grant.id}/budget-versions", headers=h).json()
    assert [(v["version"], v["is_current"]) for v in versions] == [(1, False), (2, True)]
    assert Decimal(versions[0]["total_planned"]) == 21000 and Decimal(versions[1]["total_planned"]) == 23000

    # execuția: azi (versiunea curentă) vs. la 30.05 (versiunea 1); cheltuiala se adună pe cod
    now = {r.code: r for r in execution(db, org.id, grant.id)}
    assert now["3.2"].planned == 3000 and now["3.2"].spent == 800
    before = {r.code: r for r in execution(db, org.id, grant.id, date_to=date(2026, 5, 30))}
    assert before["3.2"].planned == 1000 and before["3.2"].spent == 800 and before["3.2"].budget_line_id == bl["3.2"].id
    # avertismentul pe linia nouă ține cont de cheltuiala veche
    new_line = db.scalar(select(BudgetLine).where(BudgetLine.grant_id == grant.id, BudgetLine.code == "3.2",
                                                    BudgetLine.id != bl["3.2"].id))  # fmt: skip
    assert check_amounts(db, org.id, {new_line.id: Decimal(2000)}) == []
    assert check_amounts(db, org.id, {new_line.id: Decimal(2300)})[0].over == Decimal(100)

    # listele arată doar versiunea curentă; versiunea veche nu se modifică
    lines = client.get(f"{base}/grants/{grant.id}/budget-lines", headers=h).json()
    assert {ln["code"]: Decimal(ln["planned_amount"]) for ln in lines}["3.2"] == 3000
    catalog = client.get(f"{base}/grants", headers=h).json()
    assert len([g for g in catalog if g["code"] == "SOR"][0]["budget_lines"]) == 2
    old_put = client.put(
        f"{base}/budget-lines/{bl['3.2'].id}", json={"code": "3.2", "name": "X", "planned_amount": "1"}, headers=h
    )
    assert old_put.status_code == 409
    # linie nouă în versiunea curentă; același cod în versiunea veche nu blochează
    created = client.post(
        f"{base}/grants/{grant.id}/budget-lines", json={"code": "4.1", "name": "Altele", "planned_amount": "10"}, headers=h
    )
    assert created.status_code == 201 and created.json()["budget_version_id"] == versions[1]["id"]


def test_versiune_noua_validari(client, db, ong):
    user, org, _, grant, _, _, _ = ong
    h, base = auth_headers(user), f"/organizations/{org.id}/grants/{grant.id}/budget-versions"
    assert client.post(base, json={"valid_from": "2026-06-01", "changes": {"9.9": "1"}}, headers=h).status_code == 422
    assert client.post(base, json={"valid_from": "2026-06-01"}, headers=h).status_code == 201
    # data trebuie să fie după versiunea curentă
    assert client.post(base, json={"valid_from": "2026-05-01"}, headers=h).status_code == 422


# ───────────────────────────── tranșe ─────────────────────────────


def test_transe_verificari_recunoastere_si_incasare(client, db, ong):
    user, org, acc, grant, _, _, _ = ong
    h, base = auth_headers(user), f"/organizations/{org.id}"
    t = client.post(f"{base}/grants/{grant.id}/tranches", json={"amount": "60000", "planned_date": "2026-02-01"}, headers=h)
    assert t.status_code == 201 and t.json()["number"] == 1 and t.json()["status"] == "planned"
    assert client.post(f"{base}/grants/{grant.id}/tranches", json={"amount": "40001"}, headers=h).status_code == 422
    assert client.post(f"{base}/grants/{grant.id}/tranches", json={"amount": "10", "currency": "EUR"}, headers=h).status_code == 422
    t2 = client.post(f"{base}/grants/{grant.id}/tranches", json={"amount": "40000"}, headers=h).json()
    assert t2["number"] == 2

    rec = client.post(f"{base}/tranches/{t.json()['id']}/recognize", json={}, headers=h)
    assert rec.status_code == 200 and rec.json()["status"] == "recognized"
    doc_id = rec.json()["recognition_document_id"]
    # contract de peste un an? termenul se calculează din data recunoașterii (2026-02-01 → 11 luni: curent, 537)
    assert [(d, c, a) for d, c, a, _ in codes(db, doc_id)] == [("234.4", "537", Decimal(60000))]
    assert client.put(f"{base}/tranches/{t.json()['id']}", json={"amount": "1"}, headers=h).status_code == 409
    assert client.delete(f"{base}/tranches/{t.json()['id']}", headers=h).status_code == 409

    # încasarea tranșei: ordin de plată de intrare pe grant
    from app.bank.models import BankAccount
    from app.core.enums import DocumentType, PaymentDirection
    from app.documents.models import Document, PaymentOrder
    from app.documents.posting import post_payment

    bank = BankAccount(organization_id=org.id, iban_enc="MD00AA", currency="MDL", account_id=acc["242"].id, grant_id=grant.id)
    db.add(bank)
    db.flush()
    pay = Document(organization_id=org.id, type=DocumentType.payment_order, doc_number="P1", doc_date=date(2026, 2, 5), total_amount=Decimal(60000), currency="MDL")
    db.add(pay)
    db.flush()
    db.add(PaymentOrder(document_id=pay.id, direction=PaymentDirection.incoming, bank_account_id=bank.id))
    db.flush()
    post_payment(db, org.id, pay.id, user.id)
    got = client.post(f"{base}/tranches/{t.json()['id']}/receive", json={"document_id": str(pay.id)}, headers=h)
    assert got.status_code == 200 and got.json()["status"] == "received"
    assert client.post(f"{base}/tranches/{t2['id']}/receive", json={"document_id": str(pay.id)}, headers=h).status_code == 409


def test_recunoasterea_tranșei_refuzata_cu_politica_la_incasare(client, db, ong):
    user, org, *_, grant, _, _, _ = (*ong[:3], *ong[3:])
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.organization_id == org.id))
    policy.grant_recognition = "on_receipt"
    db.flush()
    h, base = auth_headers(user), f"/organizations/{org.id}"
    t = client.post(f"{base}/grants/{ong[3].id}/tranches", json={"amount": "100"}, headers=h).json()
    r = client.post(f"{base}/tranches/{t['id']}/recognize", json={"recognition_date": "2026-03-01"}, headers=h)
    assert r.status_code == 422


def test_anularea_recunoasterii(client, db, ong):
    user, org, _, grant, _, _, _ = ong
    h, base = auth_headers(user), f"/organizations/{org.id}"
    t = client.post(f"{base}/grants/{grant.id}/tranches", json={"amount": "500"}, headers=h).json()
    client.post(f"{base}/tranches/{t['id']}/recognize", json={"recognition_date": "2026-03-01"}, headers=h)
    r = client.post(f"{base}/tranches/{t['id']}/unrecognize", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "planned" and r.json()["recognition_document_id"] is None
    assert db.scalar(select(EntryLine.id).where(EntryLine.grant_id == grant.id)) is None


# ─────────────────── distribuirea stocurilor ───────────────────


def test_distribuirea_stocului_nu_dubleaza_linia_de_buget(client, db, ong):
    user, org, _, grant, _, bl, supplier = ong
    buy_stock(db, org, user, supplier, bl["2.1"], "3000")
    h, base = auth_headers(user), f"/organizations/{org.id}"
    body = {"doc_date": "2026-04-20", "grant_id": str(grant.id), "amount": "1200", "description": "Mobilier către beneficiari"}
    preview = client.post(f"{base}/stock-distributions/preview", json=body, headers=h).json()
    assert [(p["debit_account"], p["credit_account"]) for p in preview] == [("716", "211"), ("537", "616")]
    assert all(p["budget_line_id"] is None for p in preview)

    r = client.post(f"{base}/stock-distributions", json=body, headers=h)
    assert r.status_code == 201 and r.json()["doc_number"] == "DS-2026-001"
    # execuția: doar achiziția (3000) pe linie, distribuirea nu adaugă nimic
    assert {x.code: x.spent for x in execution(db, org.id, grant.id)}["2.1"] == Decimal(3000)
    assert len(client.get(f"{base}/stock-distributions", headers=h).json()) == 1

    # peste soldul 211 (3000 − 1200 = 1800)
    too_much = client.post(f"{base}/stock-distributions", json={**body, "amount": "1801"}, headers=h)
    assert too_much.status_code == 422 and "211" in too_much.json()["detail"]
    assert client.post(f"{base}/stock-distributions", json={**body, "amount": "1800"}, headers=h).status_code == 201

    # anulare → rândurile dispar, lista nu o mai arată
    doc_id = r.json()["document_id"]
    assert client.delete(f"{base}/stock-distributions/{doc_id}", headers=h).status_code == 204
    assert db.scalar(select(EntryLine.id).where(EntryLine.document_id == doc_id)) is None
    assert len(client.get(f"{base}/stock-distributions", headers=h).json()) == 1


def test_distribuire_din_venituri_anticipate(client, db, ong):
    user, org, _, grant, _, bl, supplier = ong
    buy_stock(db, org, user, supplier, bl["2.1"])
    h, base = auth_headers(user), f"/organizations/{org.id}"
    body = {"doc_date": "2026-04-20", "grant_id": str(grant.id), "amount": "500", "description": "x", "from_deferred": True}
    preview = client.post(f"{base}/stock-distributions/preview", json=body, headers=h).json()
    assert [(p["debit_account"], p["credit_account"]) for p in preview] == [("716", "211"), ("535", "616")]


# ─────────────── repartizarea pe granturi (închiderea lunii) ───────────────


def common_cost(db, org, acc, user, amount="1000"):
    from app.core.enums import DocumentType
    from app.documents.models import Document
    from app.posting.engine import LineInput, post_document

    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number="CH-1", doc_date=date(2026, 4, 12))
    db.add(doc)
    db.flush()
    line = LineInput(debit_account_id=acc["717"].id, credit_account_id=acc["521"].id, amount=Decimal(amount))
    post_document(db, organization_id=org.id, document_id=doc.id, lines=[line], user_id=user.id)


def test_repartizarea_pe_granturi(db, ong):
    user, org, acc, grant, other, bl, _ = ong
    common_cost(db, org, acc, user, "1000.01")
    params = {
        "source_account_id": str(acc["717"].id),
        "lines": [
            {"budget_line_id": str(bl["3.2"].id), "coefficient": "2"},
            {"budget_line_id": str(bl["9.1"].id), "coefficient": "1"},
        ],
    }
    result = run_step(db, org.id, 2026, 4, "grant_allocation", user.id, params)
    assert [r.amount for r in result.rows] == [Decimal("666.67"), Decimal("333.34")]  # suma rămâne exactă
    step = next(s for s in get_run(db, org.id, 2026, 4).steps if s["step"] == "grant_allocation")
    assert [(d, c, a) for d, c, a, _ in codes(db, step["document_id"])] == [
        ("716", "717", Decimal("666.67")),
        ("716", "717", Decimal("333.34")),
    ]
    assert {r.code: r.spent for r in execution(db, org.id, other.id)}["9.1"] == Decimal("333.34")
    allocs = db.scalars(select(Allocation).where(Allocation.document_id == step["document_id"])).all()
    assert sum(a.amount for a in allocs) == Decimal("1000.01")
    # repetarea nu dublează; venitul 537/616 îl completează pasul următor
    run_step(db, org.id, 2026, 4, "grant_allocation", user.id)
    assert {r.code: r.spent for r in execution(db, org.id, other.id)}["9.1"] == Decimal("333.34")
    income = run_step(db, org.id, 2026, 4, "special_purpose_income", user.id)
    assert income.total == Decimal("1000.01")
    revert_step(db, org.id, 2026, 4, "grant_allocation", user.id)
    assert db.scalar(select(Allocation.id).where(Allocation.document_id == step["document_id"])) is None
    assert {r.code: r.spent for r in execution(db, org.id, other.id)}["9.1"] == 0


def test_repartizare_api_validari(client, db, ong):
    user, org, acc, grant, other, bl, _ = ong
    common_cost(db, org, acc, user, "100")
    h, base = auth_headers(user), f"/organizations/{org.id}/month-close/2026/4"
    ok = {"source_account_id": str(acc["717"].id), "lines": [{"budget_line_id": str(bl["3.2"].id), "coefficient": "1"}]}
    assert client.post(f"{base}/allocation/preview", json={**ok, "amount": "101"}, headers=h).status_code == 422
    foreign = make_user(db, "x@exemplu.md")
    other_org = make_org(db, foreign, "AO Beta")
    assert client.post(f"/organizations/{other_org.id}/month-close/2026/4/allocation/preview", json=ok,
                       headers=auth_headers(foreign)).status_code == 422  # contul și linia nu sunt ale organizației  # fmt: skip
    preview = client.post(f"{base}/allocation/preview", json=ok, headers=h)
    assert preview.status_code == 200 and Decimal(preview.json()["total"]) == 100
    run = client.post(f"{base}/allocation/run", json=ok, headers=h)
    assert run.status_code == 200
    step = next(s for s in run.json()["steps"] if s["step"] == "grant_allocation")
    assert step["status"] == "done" and Decimal(step["total"]) == 100
    assert client.post(f"{base}/steps/grant_allocation/revert", headers=h).status_code == 200
