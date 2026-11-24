"""Documente de bancă și casă, decont de avans, acte de servicii, rapoarte de achiziții (fix7)."""

from datetime import date
from decimal import Decimal

import pytest

from app.bank.models import BankAccount
from app.catalogs.models import Counterparty
from app.documents.models import Document, Invoice, InvoiceLine
from app.core.enums import DocumentType, LineKind
from app.grants.models import BudgetLine, Grant
from app.payroll.models import Person
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def ong(db):
    user = make_user(db, "casier@exemplu.md")
    org = make_org(db, user, "AO Beta")
    acc = make_accounts(db, org, "211", "226", "234", "241", "242", "243", "521", "531", "533", "534", "537", "616", "716")
    grant = Grant(
        organization_id=org.id, code="SOR", title="Proiect", funding_type="grant", currency="MDL",
        total_amount=Decimal(100000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )
    db.add(grant)
    db.flush()
    line = BudgetLine(grant_id=grant.id, code="3.2", name="Comunicații", planned_amount=Decimal(5000))
    supplier = Counterparty(organization_id=org.id, name="Moldtelecom SA", idno="1002600000002", vat_code="0100001")
    person = Person(organization_id=org.id, full_name="Ion Popescu", idnp_enc="x")
    bank = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000225", currency="MDL", account_id=acc["242"].id)
    usd = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000226", currency="USD", account_id=acc["243"].id)
    db.add_all([line, supplier, person, bank, usd])
    db.flush()
    return dict(user=user, org=org, acc=acc, grant=grant, line=line, supplier=supplier, person=person, bank=bank, usd=usd)


class Api:
    def __init__(self, client, ong):
        self.c, self.o = client, ong
        self.h = auth_headers(ong["user"])
        self.base = f"/organizations/{ong['org'].id}/treasury"

    def create(self, **body):
        body.setdefault("doc_date", "2026-11-05")
        return self.c.post(f"{self.base}/docs", json=body, headers=self.h)

    def post(self, doc_id):
        return self.c.post(f"{self.base}/docs/{doc_id}/post", headers=self.h)

    def unpost(self, doc_id):
        return self.c.post(f"{self.base}/docs/{doc_id}/unpost", headers=self.h)

    def entries(self, doc_id):
        rows = self.c.get(f"{self.base}/docs/{doc_id}/entries", headers=self.h).json()
        return [(r["debit_account"], r["credit_account"], r["amount"]) for r in rows]

    def make_posted(self, **body):
        r = self.create(**body)
        assert r.status_code == 201, r.text
        doc_id = r.json()["document_id"]
        assert self.post(doc_id).status_code == 200
        return doc_id


@pytest.fixture
def api(client, ong):
    return Api(client, ong)


def test_meta_si_numerotare_automata(api):
    meta = api.c.get(f"{api.base}/meta", headers=api.h).json()
    assert [k["kind"] for k in meta] == ["bank_receipt", "bank_payment", "cash_receipt", "cash_payment", "advance_report", "service_act"]
    ops = {o["code"] for k in meta if k["kind"] == "bank_payment" for o in k["operations"]}
    assert {"supplier", "cash_withdrawal", "salary", "other"} <= ops
    bank = str(api.o["bank"].id)
    first = api.create(kind="bank_receipt", operation="membership", amount="100.00", bank_account_id=bank).json()
    second = api.create(kind="bank_receipt", operation="membership", amount="50.00", bank_account_id=bank).json()
    assert first["doc_number"] == "ÎC-2026-00001" and second["doc_number"] == "ÎC-2026-00002"


def test_incasari_pe_cont(api, ong):
    bank = str(ong["bank"].id)
    d = api.make_posted(kind="bank_receipt", operation="membership", amount="300.00", bank_account_id=bank)
    assert api.entries(d) == [("242", "234", "300.00")]
    d = api.make_posted(kind="bank_receipt", operation="cash_deposit", amount="40.00", bank_account_id=bank)
    assert api.entries(d) == [("242", "241", "40.00")]
    d = api.make_posted(kind="bank_receipt", operation="supplier_refund", amount="25.00", bank_account_id=bank,
                        counterparty_id=str(ong["supplier"].id))
    assert api.entries(d) == [("242", "521", "25.00")]
    d = api.make_posted(kind="bank_receipt", operation="other", amount="10.00", bank_account_id=bank,
                        account_id=str(ong["acc"]["534"].id))
    assert api.entries(d) == [("242", "534", "10.00")]
    listed = api.c.get(f"{api.base}/docs?kind=bank_receipt&posted=true", headers=api.h).json()
    assert len(listed) == 4


def test_plati_din_cont(api, ong):
    bank = str(ong["bank"].id)
    sup = str(ong["supplier"].id)
    assert api.entries(api.make_posted(kind="bank_payment", operation="supplier", amount="500.00", bank_account_id=bank,
                                       counterparty_id=sup)) == [("521", "242", "500.00")]
    assert api.entries(api.make_posted(kind="bank_payment", operation="cash_withdrawal", amount="200.00",
                                       bank_account_id=bank)) == [("241", "242", "200.00")]
    assert api.entries(api.make_posted(kind="bank_payment", operation="salary", amount="900.00", bank_account_id=bank,
                                       person_id=str(ong["person"].id))) == [("531", "242", "900.00")]
    assert api.entries(api.make_posted(kind="bank_payment", operation="budget", amount="90.00",
                                       bank_account_id=bank)) == [("534", "242", "90.00")]
    assert api.entries(api.make_posted(kind="bank_payment", operation="other", amount="15.00", bank_account_id=bank,
                                       account_id=str(ong["acc"]["211"].id))) == [("211", "242", "15.00")]


def test_validari(api, ong):
    bank = str(ong["bank"].id)
    r = api.create(kind="bank_payment", operation="supplier", amount="10.00", bank_account_id=bank)
    assert r.status_code == 422 and "contrapartida" in r.json()["detail"]
    r = api.create(kind="bank_payment", operation="supplier", amount="10.00", counterparty_id=str(ong["supplier"].id))
    assert r.status_code == 422 and "contul bancar" in r.json()["detail"]
    r = api.create(kind="bank_receipt", operation="membership", bank_account_id=bank)
    assert r.status_code == 422 and "suma" in r.json()["detail"].lower()
    r = api.create(kind="bank_receipt", operation="membership", amount="10.00", bank_account_id=str(ong["usd"].id))
    assert r.status_code == 422 and "curs" in r.json()["detail"].lower()
    r = api.create(kind="bank_receipt", operation="nu_exista", amount="10.00", bank_account_id=bank)
    assert r.status_code == 422
    assert api.create(kind="altceva", amount="1.00").status_code == 422
    r = api.create(kind="advance_report", lines=[], person_id=str(ong["person"].id))
    assert r.status_code == 422
    r = api.create(kind="service_act", lines=[{"description": "Mijloc fix", "amount": "10.00", "line_kind": "fixed_asset"}],
                   counterparty_id=str(ong["supplier"].id))
    assert r.status_code == 422 and "factur" in r.json()["detail"]
    # plata cu valută: cursul se aplică la suma în MDL
    r = api.create(kind="bank_receipt", operation="membership", amount="10.00", bank_account_id=str(ong["usd"].id),
                   exchange_rate="17.5000")
    assert r.status_code == 201
    assert api.post(r.json()["document_id"]).status_code == 200


def test_modificare_anulare_stergere(api, ong):
    bank = str(ong["bank"].id)
    doc = api.create(kind="bank_receipt", operation="membership", amount="10.00", bank_account_id=bank).json()
    doc_id = doc["document_id"]
    body = {"kind": "bank_receipt", "operation": "membership", "amount": "20.00", "bank_account_id": bank,
            "doc_date": "2026-11-05", "doc_number": doc["doc_number"], "version": doc["version"]}
    r = api.c.put(f"{api.base}/docs/{doc_id}", json=body, headers=api.h)
    assert r.status_code == 200 and r.json()["amount"] == "20.00"
    assert api.c.put(f"{api.base}/docs/{doc_id}", json=body, headers=api.h).status_code == 409  # versiune veche
    assert api.post(doc_id).status_code == 200
    body["version"] = r.json()["version"]
    assert api.c.put(f"{api.base}/docs/{doc_id}", json=body, headers=api.h).status_code == 409  # înregistrat
    assert api.c.delete(f"{api.base}/docs/{doc_id}", headers=api.h).status_code == 409
    # ruta generică trimite la ruta documentului
    r = api.c.post(f"/organizations/{ong['org'].id}/documents/{doc_id}/unpost", headers=api.h)
    assert r.status_code == 409 and "treasury/docs" in r.json()["detail"]
    assert api.unpost(doc_id).status_code == 204
    assert api.entries(doc_id) == []
    assert api.c.delete(f"{api.base}/docs/{doc_id}", headers=api.h).status_code == 204
    assert api.c.get(f"{api.base}/docs/{doc_id}", headers=api.h).status_code == 404


def test_casa_si_soldul(api, ong):
    sup = str(ong["supplier"].id)
    r = api.create(kind="cash_payment", operation="supplier", amount="100.00", counterparty_id=sup)
    doc = r.json()["document_id"]
    r = api.post(doc)
    assert r.status_code == 422 and "casei" in r.json()["detail"]  # casa nu poate fi pe minus
    bank = str(ong["bank"].id)
    api.make_posted(kind="cash_receipt", operation="from_bank", amount="300.00", bank_account_id=bank)
    assert api.c.get(f"{api.base}/cash-balance?on_date=2026-11-30", headers=api.h).json()["balance"] == "300.00"
    assert api.post(doc).status_code == 200
    assert api.entries(doc) == [("521", "241", "100.00")]
    assert api.c.get(f"{api.base}/cash-balance?on_date=2026-11-30", headers=api.h).json()["balance"] == "200.00"
    # depunere în bancă din casă
    d = api.make_posted(kind="cash_payment", operation="to_bank", amount="150.00", bank_account_id=bank)
    assert api.entries(d) == [("242", "241", "150.00")]
    r = api.create(kind="cash_payment", operation="to_bank", amount="999.00", bank_account_id=bank)
    assert api.post(r.json()["document_id"]).status_code == 422
    assert api.entries(api.make_posted(kind="cash_receipt", operation="membership", amount="20.00")) == [("241", "234", "20.00")]
    assert api.entries(api.make_posted(kind="cash_payment", operation="salary", amount="30.00")) == [("531", "241", "30.00")]
    r = api.create(kind="cash_receipt", operation="from_bank", amount="5.00")
    assert r.status_code == 422  # fără cont bancar


def test_avans_si_decont(api, ong):
    person, advance = str(ong["person"].id), str(ong["acc"]["226"].id)
    api.make_posted(kind="cash_receipt", operation="other", amount="1000.00", account_id=str(ong["acc"]["234"].id))
    r = api.create(kind="cash_payment", operation="advance_issue", amount="400.00", person_id=person, account_id=advance)
    assert r.status_code == 201
    assert api.post(r.json()["document_id"]).status_code == 200
    bal = api.c.get(f"{api.base}/advance-balance?person_id={person}&account_id={advance}&on_date=2026-11-30", headers=api.h)
    assert bal.json()["balance"] == "400.00"
    report = api.create(
        kind="advance_report", person_id=person, account_id=advance, purpose="Deplasare",
        lines=[{"description": "Internet", "amount": "150.00", "budget_line_id": str(ong["line"].id)},
               {"description": "Servicii poștale", "amount": "50.00", "budget_line_id": str(ong["line"].id)}],
    )
    assert report.status_code == 201, report.text
    assert report.json()["amount"] == "200.00"
    doc = report.json()["document_id"]
    pre = api.c.post(f"{api.base}/docs/{doc}/preview", headers=api.h).json()
    assert [(p["debit_account"], p["credit_account"]) for p in pre] == [("716", "226"), ("537", "616"), ("716", "226"), ("537", "616")]
    res = api.post(doc)
    assert res.status_code == 200 and res.json()["warnings"] == []
    bal = api.c.get(f"{api.base}/advance-balance?person_id={person}&account_id={advance}&on_date=2026-11-30", headers=api.h)
    assert bal.json()["balance"] == "200.00"  # 400 primit − 200 justificat
    # fără linie de buget decontul nu se poate înregistra (cheltuiala se ține pe proiecte)
    bad = api.create(kind="advance_report", person_id=person, account_id=advance,
                     lines=[{"description": "Fără proiect", "amount": "10.00"}]).json()["document_id"]
    r = api.post(bad)
    assert r.status_code == 422 and "linia de buget" in r.json()["detail"]
    # depășirea bugetului nu blochează, dar avertizează
    big = api.create(kind="advance_report", person_id=person, account_id=advance,
                     lines=[{"description": "Mult", "amount": "6000.00", "budget_line_id": str(ong["line"].id)}]).json()["document_id"]
    res = api.post(big)
    assert res.status_code == 200 and res.json()["warnings"]
    assert api.unpost(doc).status_code == 204


def test_acte_si_datorii_furnizori(api, ong, db):
    sup = str(ong["supplier"].id)
    bank = str(ong["bank"].id)
    act = api.create(
        kind="service_act", counterparty_id=sup, doc_number="A-17", doc_date="2026-08-01", purpose="Consultanță",
        lines=[{"description": "Consultanță", "amount": "1000.00", "budget_line_id": str(ong["line"].id)}],
    )
    assert act.status_code == 201, act.text
    doc = act.json()["document_id"]
    assert api.post(doc).status_code == 200
    assert api.entries(doc) == [("716", "521", "1000.00"), ("537", "616", "1000.00")]
    # ruta generică nu înregistrează actul (are ruta lui)
    r = api.c.post(f"/organizations/{ong['org'].id}/documents/{doc}/unpost", headers=api.h)
    assert r.status_code == 409 and "treasury/docs" in r.json()["detail"]
    # a doua datorie, mai recentă, și o plată parțială
    api.make_posted(kind="service_act", counterparty_id=sup, doc_date="2026-10-20",
                    lines=[{"description": "Alt serviciu", "amount": "500.00", "budget_line_id": str(ong["line"].id)}])
    api.make_posted(kind="bank_payment", operation="supplier", amount="1200.00", bank_account_id=bank,
                    counterparty_id=sup, doc_date="2026-10-25")
    rep = f"/organizations/{ong['org'].id}/treasury/reports"
    r = api.c.get(f"{rep}/supplier-debts?date_from=2026-10-01&date_to=2026-11-30", headers=api.h)
    assert r.status_code == 200, r.text
    data = r.json()
    row = data["rows"][0]
    assert row["name"] == "Moldtelecom SA"
    assert (row["opening"], row["debit"], row["credit"], row["closing"]) == ("1000.00", "1200.00", "500.00", "300.00")
    # plata a stins întâi factura veche; rămân 300 din cea din 20.10 (41 zile → 31-60)
    assert [Decimal(row[k]) for k in ("age_0_30", "age_31_60", "age_61_90", "age_over_90")] == [0, 300, 0, 0]
    assert data["total_closing"] == "300.00"
    moves = api.c.get(f"{rep}/supplier-debts/moves?date_from=2026-10-01&date_to=2026-11-30&counterparty_id={sup}",
                      headers=api.h).json()
    assert [(Decimal(m["debit"]), Decimal(m["credit"])) for m in moves] == [(0, 500), (1200, 0)]
    assert api.c.get(f"{rep}/supplier-debts?date_from=2026-12-01&date_to=2026-11-01", headers=api.h).status_code == 422
    only = api.c.get(f"{rep}/supplier-debts?date_from=2026-10-01&date_to=2026-11-30&counterparty_id={ong['person'].id}",
                     headers=api.h).json()
    assert only["rows"] == []


def test_jurnalul_facturilor_primite(api, ong, db):
    org, supplier = ong["org"], ong["supplier"]
    doc = Document(organization_id=org.id, type=DocumentType.invoice, doc_number="117", doc_date=date(2026, 11, 3),
                   counterparty_id=supplier.id, total_amount=Decimal("1200.00"), is_posted=False)
    db.add(doc)
    db.flush()
    inv = Invoice(document_id=doc.id, series="EF", e_invoice_id="E-1")
    inv.lines = [
        InvoiceLine(description="Cu TVA 20%", amount=Decimal("1200.00"), vat_rate=Decimal("20"), line_kind=LineKind.service),
    ]
    db.add(inv)
    db.flush()
    rep = f"/organizations/{org.id}/treasury/reports/received-invoices"
    data = api.c.get(f"{rep}?date_from=2026-11-01&date_to=2026-11-30", headers=api.h).json()
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert (row["total"], row["net"], row["vat"]) == ("1200.00", "1000.00", "200.00")
    assert row["vat_code"] == "0100001" and row["series"] == "EF"
    assert data["by_rate"] == [{"vat_rate": "20.00", "base": "1000.00", "vat": "200.00"}]
    assert api.c.get(f"{rep}?posted=true", headers=api.h).json()["rows"] == []
    assert len(api.c.get(f"{rep}?posted=false&q=moldtele", headers=api.h).json()["rows"]) == 1
    assert api.c.get(f"{rep}?date_from=2026-12-01", headers=api.h).json()["rows"] == []


def test_alta_organizatie_nu_vede_documentele(client, api, ong, db):
    d = api.make_posted(kind="bank_receipt", operation="membership", amount="10.00", bank_account_id=str(ong["bank"].id))
    other = make_user(db, "altul@exemplu.md")
    org2 = make_org(db, other, "AO Gama")
    h2 = auth_headers(other)
    assert client.get(f"/organizations/{org2.id}/treasury/docs/{d}", headers=h2).status_code == 404
    assert client.get(f"/organizations/{ong['org'].id}/treasury/docs?kind=bank_receipt", headers=h2).status_code == 404
