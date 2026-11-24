"""Modulul de vânzări: facturi emise, TVA colectată, valută, stornare, anulare, încasări legate, sold clienți."""

from datetime import date
from decimal import Decimal

import pytest

from app.bank.models import BankAccount
from app.catalogs.models import Counterparty
from app.core.enums import UserRole
from app.posting.models import AccountingPeriod, EntryLine
from app.models import Organization
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def firm(db):
    user = make_user(db, "vanzari@exemplu.md")
    org = make_org(db, user, "AO Vânzări")
    org.vat_payer_from = date(2025, 1, 1)
    org.vat_code = "0612345"
    acc = make_accounts(db, org, "221", "241", "242", "243", "534.4", "617", "618")
    client_cp = Counterparty(organization_id=org.id, name="SRL Client", idno="1003600000001", vat_code="0600001")
    other = Counterparty(organization_id=org.id, name="SA Alt Client", idno="1003600000002")
    noidno = Counterparty(organization_id=org.id, name="Persoană fără IDNO")
    bank = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000225", currency="MDL", account_id=acc["242"].id)
    usd = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000226", currency="USD", account_id=acc["243"].id)
    db.add_all([client_cp, other, noidno, bank, usd])
    db.flush()
    return dict(user=user, org=org, acc=acc, client=client_cp, other=other, noidno=noidno, bank=bank, usd=usd)


class Api:
    def __init__(self, tc, firm):
        self.c, self.f = tc, firm
        self.h = auth_headers(firm["user"])
        self.base = f"/organizations/{firm['org'].id}/sales"
        self.org = f"/organizations/{firm['org'].id}"

    def invoice(self, lines=None, **kw):
        body = dict(doc_date="2026-11-05", counterparty_id=str(self.f["client"].id),
                    lines=lines or [dict(description="Servicii training", amount="1000.00", vat_rate="20")])
        body.update(kw)
        return self.c.post(f"{self.base}/invoices", json=body, headers=self.h)

    def posted(self, **kw):
        r = self.invoice(**kw)
        assert r.status_code == 201, r.text
        did = r.json()["document_id"]
        p = self.c.post(f"{self.base}/invoices/{did}/post", headers=self.h)
        assert p.status_code == 200, p.text
        return did

    def entries(self, did):
        rows = self.c.get(f"{self.base}/invoices/{did}/entries", headers=self.h).json()
        return [(r["debit_account"], r["credit_account"], r["amount"]) for r in rows]

    def get(self, did):
        return self.c.get(f"{self.base}/invoices/{did}", headers=self.h).json()

    def receipt(self, did, amount, kind="bank_receipt", post=True, link=True, **kw):
        inv = self.get(did)
        body = dict(kind=kind, operation="customer", doc_date="2026-11-20", amount=amount,
                    counterparty_id=inv["counterparty_id"])
        if kind == "bank_receipt":
            body["bank_account_id"] = str(self.f["bank"].id)
        body.update(kw)
        r = self.c.post(f"{self.org}/treasury/docs", json=body, headers=self.h)
        assert r.status_code == 201, r.text
        rid = r.json()["document_id"]
        if link:
            s = self.c.put(f"{self.base}/receipts/{rid}/settlements", json={"items": [{"invoice_id": inv["id"], "amount": amount}]}, headers=self.h)
            assert s.status_code == 200, s.text
        if post:
            p = self.c.post(f"{self.org}/treasury/docs/{rid}/post", headers=self.h)
            assert p.status_code == 200, p.text
        return rid


@pytest.fixture
def api(client, firm):
    return Api(client, firm)


def test_factura_cu_tva_se_inregistreaza_pe_221_618_534(api):
    r = api.invoice(lines=[dict(description="Training", amount="1000.00", vat_rate="20"),
                           dict(description="Taxă participare", amount="500.00", vat_rate="0", revenue_type="organization")])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["number"] == "000001" and Decimal(body["net"]) == 1500 and Decimal(body["vat"]) == 200
    assert Decimal(body["gross"]) == 1700 and body["seller"]["idno"] and body["client"]["idno"] == "1003600000001"
    did = body["document_id"]
    prev = api.c.post(f"{api.base}/invoices/{did}/preview", headers=api.h)
    assert prev.status_code == 200 and len(prev.json()) == 3
    api.c.post(f"{api.base}/invoices/{did}/post", headers=api.h)
    assert sorted(api.entries(did)) == sorted([("221", "618", "1000.00"), ("221", "534.4", "200.00"), ("221", "617", "500.00")])
    # modificarea unei facturi înregistrate e refuzată
    upd = api.c.put(f"{api.base}/invoices/{did}", json=dict(doc_date="2026-11-05", counterparty_id=body["counterparty_id"],
                                                          lines=[dict(description="x", amount="1.00")]), headers=api.h)
    assert upd.status_code == 409


def test_numerotare_automata_si_numar_dublat_refuzat(api):
    assert api.invoice().json()["number"] == "000001"
    assert api.invoice().json()["number"] == "000002"
    dup = api.invoice(number="000001")
    assert dup.status_code == 409 and "000001" in dup.json()["detail"]
    ok = api.invoice(number="000001", series="B")  # altă serie, același număr
    assert ok.status_code == 201 and ok.json()["series"] == "B"
    assert api.c.get(f"{api.base}/meta", headers=api.h).json()["next_number"] == "000003"


def test_validari_client_idno_tva_si_conturi(api, firm, db):
    r = api.invoice(counterparty_id=str(firm["noidno"].id))
    assert r.status_code == 422 and "IDNO" in r.json()["detail"]
    firm["org"].vat_payer_from = None
    db.flush()
    r = api.invoice()
    assert r.status_code == 422 and "plătitoare de TVA" in r.json()["detail"]
    zero = api.invoice(lines=[dict(description="x", amount="10.00", vat_rate="0")])
    assert zero.status_code == 201
    firm["org"].vat_payer_from = date(2025, 1, 1)
    db.flush()
    assert api.invoice(lines=[dict(description="x", amount="10.00", vat_rate="7")]).status_code == 422  # cotă inexistentă
    assert api.invoice(lines=[dict(description="x", amount="10.00", vat_rate="20", account_id=str(firm["acc"]["242"].id))]).status_code == 422
    custom = api.invoice(lines=[dict(description="x", quantity="3", unit_price="10.50", vat_rate="8", account_id=str(firm["acc"]["617"].id))])
    assert custom.status_code == 201 and Decimal(custom.json()["lines"][0]["amount"]) == Decimal("31.50")
    did = custom.json()["document_id"]
    api.c.post(f"{api.base}/invoices/{did}/post", headers=api.h)
    assert api.entries(did) == [("221", "617", "31.50"), ("221", "534.4", "2.52")]


def test_factura_in_valuta_cu_curs_bnm(api):
    assert api.invoice(currency="EUR").status_code == 422  # lipsește cursul
    did = api.posted(currency="EUR", exchange_rate="19.5000", lines=[dict(description="Consultanță", amount="100.00", vat_rate="20")])
    assert api.entries(did) == [("221", "618", "1950.00"), ("221", "534.4", "390.00")]
    inv = api.get(did)
    assert inv["currency"] == "EUR" and Decimal(inv["gross"]) == 120


def test_anularea_inregistrarii_si_perioada_inchisa(api, firm, db):
    did = api.posted()
    api.c.post(f"{api.base}/invoices/{did}/unpost", headers=api.h)
    assert api.entries(did) == [] and api.get(did)["is_posted"] is False
    db.add(AccountingPeriod(organization_id=firm["org"].id, year=2026, month=11, is_closed=True))
    db.flush()
    r = api.c.post(f"{api.base}/invoices/{did}/post", headers=api.h)
    assert r.status_code == 422 and "închisă" in r.json()["detail"]


def test_nota_de_stornare(api):
    did = api.posted()
    r = api.c.post(f"{api.base}/invoices/{did}/credit-note", json=dict(doc_date="2026-11-15", reason="retur"), headers=api.h)
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["kind"] == "credit_note" and Decimal(note["gross"]) == -1200 and note["storno_of_id"] == api.get(did)["id"]
    nid = note["document_id"]
    assert api.c.post(f"{api.base}/invoices/{nid}/post", headers=api.h).status_code == 200
    assert sorted(api.entries(nid)) == sorted([("618", "221", "1000.00"), ("534.4", "221", "200.00")])
    assert Decimal(api.get(did)["balance"]) == 0 and Decimal(api.get(did)["credited"]) == 1200
    # nu se poate storna mai mult decât valoarea facturii
    again = api.c.post(f"{api.base}/invoices/{did}/credit-note", json=dict(doc_date="2026-11-16"), headers=api.h)
    assert again.status_code == 422
    # factura de bază nu se poate anula cât are stornări înregistrate
    un = api.c.post(f"{api.base}/invoices/{did}/unpost", headers=api.h)
    assert un.status_code == 422 and "stornare" in un.json()["detail"]
    # nota nu se storna și nu se șterge după înregistrare
    assert api.c.post(f"{api.base}/invoices/{nid}/credit-note", json=dict(doc_date="2026-11-16"), headers=api.h).status_code == 422
    assert api.c.delete(f"{api.base}/invoices/{nid}", headers=api.h).status_code == 409


def test_nota_partiala(api):
    did = api.posted()
    r = api.c.post(f"{api.base}/invoices/{did}/credit-note", headers=api.h,
                   json=dict(doc_date="2026-11-15", lines=[dict(description="Retur parțial", amount="250.00", vat_rate="20")]))
    assert r.status_code == 201 and Decimal(r.json()["gross"]) == -300
    nid = r.json()["document_id"]
    api.c.post(f"{api.base}/invoices/{nid}/post", headers=api.h)
    assert Decimal(api.get(did)["balance"]) == 900


def test_anularea_facturii(api):
    draft = api.invoice().json()["document_id"]
    c = api.c.post(f"{api.base}/invoices/{draft}/cancel", json=dict(reason="greșită"), headers=api.h)
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    assert api.c.post(f"{api.base}/invoices/{draft}/post", headers=api.h).status_code == 422
    assert api.c.post(f"{api.base}/invoices/{draft}/cancel", json=dict(reason="încă o dată"), headers=api.h).status_code == 409
    did = api.posted()
    assert api.c.post(f"{api.base}/invoices/{did}/cancel", json=dict(reason="client renunțat"), headers=api.h).status_code == 200
    assert api.entries(did) == [] and api.get(did)["is_posted"] is False
    # numărul rămâne ocupat
    assert api.invoice(number=api.get(did)["number"]).status_code == 409
    # anulatele nu intră în TVA și nu se pot stinge
    vat = api.c.get(f"{api.org}/reports/vat", params=dict(date_from="2026-01-01", date_to="2026-12-31"), headers=api.h).json()
    assert vat["sales_rows"] == [] and Decimal(vat["collected_vat_total"]) == 0


def test_stergerea_doar_a_ciornelor(api):
    draft = api.invoice().json()["document_id"]
    assert api.c.delete(f"{api.base}/invoices/{draft}", headers=api.h).status_code == 204
    assert api.c.get(f"{api.base}/invoices/{draft}", headers=api.h).status_code == 404
    did = api.posted()
    assert api.c.delete(f"{api.base}/invoices/{did}", headers=api.h).status_code == 409


def test_incasare_legata_stinge_factura(api):
    did = api.posted()  # 1200 cu TVA
    partial = api.receipt(did, "500.00")
    inv = api.get(did)
    assert Decimal(inv["paid"]) == 500 and Decimal(inv["balance"]) == 700
    rows = api.c.get(f"{api.base}/invoices/{did}/receipts", headers=api.h).json()
    assert len(rows) == 1 and rows[0]["is_posted"] is True
    ent = api.c.get(f"{api.org}/treasury/docs/{partial}/entries", headers=api.h).json()
    assert [(e["debit_account"], e["credit_account"], e["amount"]) for e in ent] == [("242", "221", "500.00")]
    api.receipt(did, "700.00", kind="cash_receipt")  # numerar: Dt 241
    inv = api.get(did)
    assert Decimal(inv["balance"]) == 0 and Decimal(inv["paid"]) == 1200
    unpaid = api.c.get(f"{api.base}/invoices", params=dict(unpaid="true"), headers=api.h).json()
    assert unpaid == []
    # factura stinsă nu se mai poate anula / anula înregistrarea
    assert api.c.post(f"{api.base}/invoices/{did}/unpost", headers=api.h).status_code == 422
    assert api.c.post(f"{api.base}/invoices/{did}/cancel", json=dict(reason="test"), headers=api.h).status_code == 422


def test_legarea_incasarii_se_valideaza(api, firm):
    did = api.posted()
    inv = api.get(did)
    rid = api.receipt(did, "300.00", post=False, link=False)
    put = lambda items: api.c.put(f"{api.base}/receipts/{rid}/settlements", json={"items": items}, headers=api.h)  # noqa: E731
    assert put([{"invoice_id": inv["id"], "amount": "400.00"}]).status_code == 422  # peste suma încasării
    assert put([{"invoice_id": inv["id"], "amount": "100.00"}, {"invoice_id": inv["id"], "amount": "50.00"}]).status_code == 422
    other = api.posted(counterparty_id=str(firm["other"].id))
    assert put([{"invoice_id": api.get(other)["id"], "amount": "100.00"}]).status_code == 422  # alt client
    draft = api.invoice().json()
    assert put([{"invoice_id": draft["id"], "amount": "100.00"}]).status_code == 422  # neînregistrată
    ok = put([{"invoice_id": inv["id"], "amount": "300.00"}])
    assert ok.status_code == 200 and Decimal(ok.json()["unallocated"]) == 0
    # încasarea înregistrată nu mai poate fi relegată
    api.c.post(f"{api.org}/treasury/docs/{rid}/post", headers=api.h)
    assert put([]).status_code == 409
    # nu se poate încasa mai mult decât restul facturii
    big = api.receipt(did, "1000.00", post=False, link=False)
    r = api.c.put(f"{api.base}/receipts/{big}/settlements", json={"items": [{"invoice_id": inv["id"], "amount": "1000.00"}]}, headers=api.h)
    assert r.status_code == 422 and "900.00" in r.json()["detail"]
    # încasările de alt fel (ex. cotizații) nu se leagă de facturi
    mem = api.c.post(f"{api.org}/treasury/docs", json=dict(kind="bank_receipt", operation="membership", doc_date="2026-11-20",
                                                         amount="50.00", bank_account_id=str(firm["bank"].id)), headers=api.h)
    assert mem.status_code == 201, mem.text
    g = api.c.get(f"{api.base}/receipts/{mem.json()['document_id']}/settlements", headers=api.h)
    assert g.status_code == 404


def test_incasare_in_valuta(api, firm):
    did = api.posted(currency="USD", exchange_rate="17.0000", lines=[dict(description="Grant tehnic", amount="100.00", vat_rate="0")])
    rid = api.receipt(did, "100.00", bank_account_id=str(firm["usd"].id), exchange_rate="17.5000", link=False, post=False)
    r = api.c.put(f"{api.base}/receipts/{rid}/settlements", json={"items": [{"invoice_id": api.get(did)["id"], "amount": "100.00"}]}, headers=api.h)
    assert r.status_code == 200
    # încasarea în MDL pe o factură în USD nu se leagă
    mdl = api.receipt(did, "50.00", post=False, link=False)
    bad = api.c.put(f"{api.base}/receipts/{mdl}/settlements", json={"items": [{"invoice_id": api.get(did)["id"], "amount": "50.00"}]}, headers=api.h)
    assert bad.status_code == 422 and "USD" in bad.json()["detail"]


def test_sold_clienti_cu_vechime(api, firm):
    f1 = api.posted(doc_date="2026-08-01", due_date="2026-08-31", lines=[dict(description="a", amount="1000.00", vat_rate="0")])
    api.posted(doc_date="2026-10-20", due_date="2026-12-20", lines=[dict(description="b", amount="400.00", vat_rate="0")])
    api.posted(doc_date="2026-11-01", counterparty_id=str(firm["other"].id), lines=[dict(description="c", amount="250.00", vat_rate="0")])
    api.receipt(f1, "300.00")  # legată explicit de prima
    # încasare nelegată: stinge cea mai veche factură rămasă (FIFO)
    r = api.c.post(f"{api.org}/treasury/docs", json=dict(kind="bank_receipt", operation="customer", doc_date="2026-11-10", amount="200.00",
                                                       bank_account_id=str(firm["bank"].id), counterparty_id=str(firm["client"].id)), headers=api.h)
    api.c.post(f"{api.org}/treasury/docs/{r.json()['document_id']}/post", headers=api.h)
    rep = api.c.get(f"{api.base}/reports/customer-balances", params=dict(as_of="2026-11-24"), headers=api.h).json()
    rows = {x["name"]: x for x in rep["rows"]}
    c = rows["SRL Client"]
    assert Decimal(c["invoiced"]) == 1400 and Decimal(c["received"]) == 500 and Decimal(c["balance"]) == 900
    # 1000 − 300 (legat) − 200 (FIFO) = 500 din prima (115 zile, restantă), a doua intactă (35 zile, nescadentă)
    by_num = {i["number"]: i for i in c["invoices"]}
    assert Decimal(by_num["000001"]["open_mdl"]) == 500 and by_num["000001"]["overdue_days"] == 85
    assert Decimal(c["age_over_90"]) == 500 and Decimal(c["age_31_60"]) == 400 and Decimal(c["not_due"]) == 400
    assert Decimal(c["overdue"]) == 500
    assert Decimal(rows["SA Alt Client"]["balance"]) == 250 and Decimal(rep["total_balance"]) == 1150
    assert Decimal(rep["ledger_balance"]) == 1150  # coincide cu contul 221 din contabilitate
    # la o dată anterioară încasările nu contează
    old = api.c.get(f"{api.base}/reports/customer-balances", params=dict(as_of="2026-09-01"), headers=api.h).json()
    assert Decimal(old["total_balance"]) == 1000
    one = api.c.get(f"{api.base}/reports/customer-balances", params=dict(as_of="2026-11-24", counterparty_id=str(firm["other"].id)), headers=api.h).json()
    assert len(one["rows"]) == 1
    csv = api.c.get(f"{api.base}/reports/customer-balances.csv", params=dict(as_of="2026-11-24"), headers=api.h)
    assert csv.status_code == 200 and "SRL Client" in csv.text


def test_jurnalul_vanzarilor_si_decontul_tva_net(api, db, firm):
    from app.documents.models import Document, Invoice, InvoiceLine
    from app.core.enums import DocumentStatus, DocumentType

    api.posted(lines=[dict(description="a", amount="1000.00", vat_rate="20"), dict(description="b", amount="500.00", vat_rate="8")])
    api.posted(currency="EUR", exchange_rate="20.0000", lines=[dict(description="c", amount="100.00", vat_rate="20")])
    did = api.posted(doc_date="2026-11-10", lines=[dict(description="d", amount="200.00", vat_rate="20")])
    note = api.c.post(f"{api.base}/invoices/{did}/credit-note", json=dict(doc_date="2026-11-12"), headers=api.h).json()
    api.c.post(f"{api.base}/invoices/{note['document_id']}/post", headers=api.h)
    # o factură primită cu TVA dedusă 100 (500 × 20%)
    doc = Document(organization_id=firm["org"].id, type=DocumentType.invoice, doc_number="P-1", doc_date=date(2026, 11, 3),
                   counterparty_id=firm["other"].id, status=DocumentStatus.validated)
    db.add(doc)
    db.flush()
    inv = Invoice(document_id=doc.id)
    db.add(inv)
    db.flush()
    db.add(InvoiceLine(invoice_id=inv.id, description="x", amount=Decimal("500.00"), vat_rate=Decimal(20), position=0))
    db.flush()
    p = dict(date_from="2026-11-01", date_to="2026-11-30")
    j = api.c.get(f"{api.base}/reports/journal", params=p, headers=api.h).json()
    # 1000/20% + 500/8% + 100 EUR×20 = 2000/20% + 200/20% − storno 200/20%
    assert Decimal(j["vat_total"]) == Decimal("200") + Decimal("40") + Decimal("400") + Decimal("40") - Decimal("40")
    assert any(r["kind"] == "credit_note" and Decimal(r["vat"]) == -40 for r in j["rows"])
    rep = api.c.get(f"{api.org}/reports/vat", params=p, headers=api.h).json()
    assert Decimal(rep["collected_vat_total"]) == 640 and Decimal(rep["deductible_vat_total"]) == 100
    assert Decimal(rep["net_vat"]) == 540 and Decimal(rep["posted_net_vat"]) == 640  # factura primită nu e înregistrată
    rates = {Decimal(t["rate"]): t for t in rep["sales_by_rate"]}
    assert Decimal(rates[Decimal(20)]["vat"]) == 600 and Decimal(rates[Decimal(8)]["vat"]) == 40
    assert api.c.get(f"{api.org}/reports/vat.xlsx", params=p, headers=api.h).content[:2] == b"PK"
    assert api.c.get(f"{api.base}/reports/journal", params=dict(date_from="2026-12-01", date_to="2026-01-01"), headers=api.h).status_code == 422


def test_balanta_ramane_corecta_si_rulajele_coincid(api, db, firm):
    from app.posting.engine import turnover_differences

    did = api.posted(currency="EUR", exchange_rate="19.7500")
    api.receipt(api.posted(), "400.00")
    api.c.post(f"{api.base}/invoices/{did}/unpost", headers=api.h)
    assert turnover_differences(db, firm["org"].id) == []
    dt = sum(Decimal(e.amount) for e in db.query(EntryLine).filter_by(organization_id=firm["org"].id))
    assert dt == Decimal("1200.00") + Decimal("400.00")


def test_documentul_nu_se_inregistreaza_pe_ruta_generica(api):
    did = api.invoice().json()["document_id"]
    r = api.c.post(f"{api.org}/documents/{did}/unpost", headers=api.h)
    assert r.status_code == 409 and "sales/invoices" in r.json()["detail"]
    lines = [dict(debit_account_id=str(api.f["acc"]["221"].id), credit_account_id=str(api.f["acc"]["618"].id), amount="5.00")]
    r = api.c.post(f"{api.org}/documents/{did}/post", json={"lines": lines}, headers=api.h)
    assert r.status_code == 409 and "sales/invoices" in r.json()["detail"]


def test_izolarea_si_rolurile(client, api, firm, db):
    did = api.posted()
    intruder = make_user(db, "strain@exemplu.md")
    other_org = make_org(db, intruder, "AO Altă")
    h2 = auth_headers(intruder)
    foreign = f"/organizations/{other_org.id}/sales"
    assert client.get(f"{foreign}/invoices/{did}", headers=h2).status_code == 404
    assert client.get(f"{foreign}/invoices", headers=h2).json() == []
    assert client.post(f"{foreign}/invoices/{did}/post", headers=h2).status_code == 404
    assert client.post(f"{foreign}/invoices", headers=h2, json=dict(doc_date="2026-11-05", counterparty_id=str(firm["client"].id),
                                                                   lines=[dict(description="x", amount="1.00")])).status_code == 422
    assert client.get(f"{foreign}/reports/customer-balances", headers=h2).json()["rows"] == []
    # accesul la organizația altcuiva
    assert client.get(f"/organizations/{firm['org'].id}/sales/invoices", headers=h2).status_code in (403, 404)
    # auditorul vede, dar nu scrie
    aud = make_user(db, "auditor@exemplu.md")
    from app.auth.models import OrganizationMember

    db.add(OrganizationMember(organization_id=firm["org"].id, user_id=aud.id, role=UserRole.auditor))
    db.flush()
    ha = auth_headers(aud)
    assert client.get(f"{api.base}/invoices", headers=ha).status_code == 200
    assert client.post(f"{api.base}/invoices", headers=ha, json=dict(doc_date="2026-11-05", counterparty_id=str(firm["client"].id),
                                                                    lines=[dict(description="x", amount="1.00")])).status_code == 403
    assert client.post(f"{api.base}/invoices/{did}/unpost", headers=ha).status_code == 403
    # id-uri străine în corpul cererii
    leak = client.post(f"{api.base}/invoices", headers=api.h, json=dict(doc_date="2026-11-05", counterparty_id=str(db.query(Counterparty).filter_by(organization_id=other_org.id).first() or firm["client"].id),
                                                                       lines=[dict(description="x", amount="1.00", account_id="00000000-0000-0000-0000-000000000001")]))
    assert leak.status_code == 422
