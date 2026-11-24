"""Stingerea facturilor primite: legarea plăților, sold rămas, starea „achitată / parțial”, rapoarte."""

from decimal import Decimal

import pytest

from app.catalogs.models import Counterparty
from tests.conftest import auth_headers
from tests.test_treasury import Api, ong  # noqa: F401  (fixture refolosită)


@pytest.fixture
def api(client, ong):  # noqa: F811
    return Api(client, ong)


def make_invoice(api, ong, number, amount, day="2026-10-05", post=True):
    body = {"doc_number": number, "doc_date": day, "counterparty_id": str(ong["supplier"].id),
            "lines": [{"description": "Servicii", "amount": amount, "line_kind": "service", "budget_line_id": str(ong["line"].id)}]}  # fmt: skip
    r = api.c.post(f"/organizations/{ong['org'].id}/invoices", json=body, headers=api.h)
    assert r.status_code == 201, r.text
    doc_id = r.json()["document_id"]
    if post:
        p = api.c.post(f"/organizations/{ong['org'].id}/invoices/{doc_id}/post", headers=api.h)
        assert p.status_code == 200, p.text
    return doc_id


def pay(api, ong, amount, day="2026-10-20"):
    return api.make_posted(kind="bank_payment", operation="supplier", amount=amount, bank_account_id=str(ong["bank"].id),
                           counterparty_id=str(ong["supplier"].id), doc_date=day)  # fmt: skip


def journal(api, ong, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return api.c.get(f"{api.base}/reports/received-invoices?{qs}", headers=api.h).json()


def test_plata_stinge_factura_partial_si_total(api, ong):
    f1 = make_invoice(api, ong, "F-1", "1000.00")
    p1 = pay(api, ong, "400.00")
    url = f"{api.base}/payments/{p1}/settlements"
    r = api.c.put(url, json={"items": [{"invoice_document_id": f1, "amount": "400.00"}]}, headers=api.h)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["allocated"]) == 400 and Decimal(r.json()["free"]) == 0
    row = journal(api, ong)["rows"][0]
    assert (row["paid"], row["remaining"], row["payment_status"]) == ("400.00", "600.00", "partial")
    pays = api.c.get(f"{api.base}/settlements/payments?counterparty_id={ong['supplier'].id}", headers=api.h).json()
    assert [(x["amount"], x["allocated"], x["free"]) for x in pays] == [("400.00", "400.00", "0.00")]
    opens = api.c.get(f"{api.base}/settlements/open-invoices?counterparty_id={ong['supplier'].id}", headers=api.h).json()
    assert [(o["doc_number"], o["remaining"], o["payment_status"]) for o in opens] == [("F-1", "600.00", "partial")]
    inv = api.c.get(f"{api.base}/invoices/{f1}/settlements", headers=api.h).json()
    assert inv["payment_status"] == "partial" and [p["amount"] for p in inv["payments"]] == ["400.00"]

    p2 = pay(api, ong, "600.00", day="2026-10-25")
    assert api.c.put(f"{api.base}/payments/{p2}/settlements", json={"items": [{"invoice_document_id": f1, "amount": "600.00"}]},
                     headers=api.h).status_code == 200  # fmt: skip
    data = journal(api, ong)
    assert (data["rows"][0]["payment_status"], data["paid"], data["remaining"]) == ("paid", "1000.00", "0.00")
    assert journal(api, ong, payment_status="paid")["rows"] and not journal(api, ong, payment_status="unpaid")["rows"]
    assert api.c.get(f"{api.base}/reports/received-invoices?payment_status=nu", headers=api.h).status_code == 422

    # plata anulată nu mai stinge factura (rămâne legată, dar nu se numără)
    assert api.unpost(p2).status_code == 204
    row = journal(api, ong)["rows"][0]
    assert (row["paid"], row["payment_status"]) == ("400.00", "partial")
    assert api.post(p2).status_code == 200
    assert journal(api, ong)["rows"][0]["payment_status"] == "paid"


def test_validari_la_legare(api, ong, db):
    f1 = make_invoice(api, ong, "F-1", "1000.00")
    other = Counterparty(organization_id=ong["org"].id, name="Alt furnizor", idno="1002600000009")
    db.add(other)
    db.flush()
    p1 = pay(api, ong, "500.00")
    put = lambda pid, items: api.c.put(f"{api.base}/payments/{pid}/settlements", json={"items": items}, headers=api.h)  # noqa: E731
    r = put(p1, [{"invoice_document_id": f1, "amount": "600.00"}])
    assert r.status_code == 422 and "depășește suma plății" in r.json()["detail"]
    assert put(p1, [{"invoice_document_id": f1, "amount": "300.00"}, {"invoice_document_id": f1, "amount": "100.00"}]).status_code == 422
    assert put(p1, [{"invoice_document_id": f1, "amount": "500.00"}]).status_code == 200
    p2 = pay(api, ong, "700.00", day="2026-10-26")
    r = put(p2, [{"invoice_document_id": f1, "amount": "600.00"}])  # restul facturii e 500
    assert r.status_code == 422 and "restul de achitat" in r.json()["detail"] and "500,00" in r.json()["detail"]
    # plata altui furnizor / plată care nu e către furnizor
    foreign = api.make_posted(kind="bank_payment", operation="supplier", amount="100.00", bank_account_id=str(ong["bank"].id),
                              counterparty_id=str(other.id), doc_date="2026-10-27")  # fmt: skip
    assert "altui furnizor" in put(foreign, [{"invoice_document_id": f1, "amount": "100.00"}]).json()["detail"]
    salary = api.make_posted(kind="bank_payment", operation="budget", amount="50.00", bank_account_id=str(ong["bank"].id), doc_date="2026-10-28")
    assert put(salary, []).status_code == 422
    # dezlegarea cu listă goală
    assert put(p1, []).status_code == 200
    assert journal(api, ong)["rows"][0]["payment_status"] == "unpaid"
    # alt utilizator din altă organizație nu vede plata
    from tests.conftest import make_org, make_user

    intruder = make_user(db, "intrus@test.md")
    make_org(db, intruder, "AO Intrus")
    r = api.c.get(f"{api.base}/payments/{p1}/settlements", headers=auth_headers(intruder))
    assert r.status_code in (403, 404)


def test_stingere_automata_cele_mai_vechi_intai(api, ong):
    f1 = make_invoice(api, ong, "F-1", "1000.00", day="2026-09-01")
    f2 = make_invoice(api, ong, "F-2", "500.00", day="2026-10-01")
    pay(api, ong, "1200.00", day="2026-10-10")
    r = api.c.post(f"{api.base}/settlements/auto", json={}, headers=api.h)
    assert r.status_code == 200 and Decimal(r.json()["amount"]) == 1200 and r.json()["invoices"] == 2
    rows = {x["doc_number"]: x for x in journal(api, ong)["rows"]}
    assert (rows["F-1"]["payment_status"], rows["F-2"]["payment_status"], rows["F-2"]["remaining"]) == ("paid", "partial", "300.00")
    again = api.c.post(f"{api.base}/settlements/auto", json={}, headers=api.h).json()
    assert Decimal(again["amount"]) == 0  # nimic nou de stins
    assert f1 and f2


def test_datorii_furnizori_cu_starea_facturilor(api, ong):
    f1 = make_invoice(api, ong, "F-1", "1000.00", day="2026-10-01")
    make_invoice(api, ong, "F-2", "500.00", day="2026-10-02")
    make_invoice(api, ong, "F-3", "200.00", day="2026-10-03")
    p = pay(api, ong, "1000.00", day="2026-10-20")
    api.c.put(f"{api.base}/payments/{p}/settlements", json={"items": [{"invoice_document_id": f1, "amount": "1000.00"}]}, headers=api.h)
    p2 = pay(api, ong, "100.00", day="2026-10-21")
    inv2 = [r for r in journal(api, ong)["rows"] if r["doc_number"] == "F-2"][0]["document_id"]
    api.c.put(f"{api.base}/payments/{p2}/settlements", json={"items": [{"invoice_document_id": inv2, "amount": "100.00"}]}, headers=api.h)
    rep = f"{api.base}/reports"
    data = api.c.get(f"{rep}/supplier-debts?date_from=2026-10-01&date_to=2026-11-30", headers=api.h).json()
    row = data["rows"][0]
    assert (row["count_paid"], row["count_partial"], row["count_unpaid"]) == (1, 1, 1)
    assert (row["invoices_total"], row["invoices_paid"], row["invoices_remaining"]) == ("1700.00", "1100.00", "600.00")
    sup = str(ong["supplier"].id)
    moves = api.c.get(f"{rep}/supplier-debts/moves?date_from=2026-10-01&date_to=2026-11-30&counterparty_id={sup}", headers=api.h).json()
    by_doc = {m["doc_number"]: m for m in moves if Decimal(m["credit"]) > 0}
    assert by_doc["F-1"]["payment_status"] == "paid" and by_doc["F-2"]["invoice_remaining"] == "400.00"
    assert by_doc["F-3"]["payment_status"] == "unpaid"
    assert sorted(Decimal(m["allocated"]) for m in moves if Decimal(m["debit"]) > 0) == [100, 1000]


def test_ordinul_de_plata_cu_factura_indicata_o_stinge(api, ong):
    f1 = make_invoice(api, ong, "F-9", "612.40")
    body = {"doc_number": "OP-1", "doc_date": "2026-10-30", "direction": "outgoing", "amount": "612.40", "bank_account_id": str(ong["bank"].id),
            "counterparty_id": str(ong["supplier"].id), "invoice_document_id": f1, "purpose": "F-9"}  # fmt: skip
    r = api.c.post(f"/organizations/{ong['org'].id}/payment-orders", json=body, headers=api.h)
    assert r.status_code == 201, r.text
    oid = r.json()["document_id"]
    assert journal(api, ong)["rows"][0]["payment_status"] == "unpaid"  # ciorna nu stinge încă
    assert api.c.post(f"/organizations/{ong['org'].id}/payment-orders/{oid}/post", headers=api.h).status_code == 200
    row = journal(api, ong)["rows"][0]
    assert (row["payment_status"], row["remaining"]) == ("paid", "0.00")
