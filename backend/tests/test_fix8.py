from datetime import date
from decimal import Decimal

from app.catalogs.models import Counterparty
from app.core.enums import AccountKind, DocumentStatus, DocumentType
from app.documents.models import Document, Invoice, InvoiceLine
from app.posting.engine import LineInput, post_document
from tests.conftest import auth_headers, make_accounts, make_org, make_user


def _setup(db):
    user = make_user(db, "f8@exemplu.md")
    org = make_org(db, user, "AO Fix8")
    return user, org, auth_headers(user)


def _invoice(db, org, d, number, *lines):
    cp = db.query(Counterparty).filter_by(organization_id=org.id, idno="1002600000001").first()
    if cp is None:
        cp = Counterparty(organization_id=org.id, name="SRL Furnizor", idno="1002600000001", vat_code="0601234")
        db.add(cp)
        db.flush()
    doc = Document(organization_id=org.id, type=DocumentType.invoice, doc_number=number, doc_date=d,
                   counterparty_id=cp.id, status=DocumentStatus.validated)  # fmt: skip
    db.add(doc)
    db.flush()
    inv = Invoice(document_id=doc.id)
    db.add(inv)
    db.flush()
    for i, (amount, rate) in enumerate(lines):
        db.add(InvoiceLine(invoice_id=inv.id, description="x", amount=Decimal(amount), vat_rate=Decimal(rate), position=i))
    db.flush()
    return doc


def _post(db, org, user, acc, d, a, b, s, number="OM"):
    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number=number, doc_date=d)
    db.add(doc)
    db.flush()
    line = LineInput(debit_account_id=acc[a].id, credit_account_id=acc[b].id, amount=Decimal(s))
    post_document(db, organization_id=org.id, document_id=doc.id, lines=[line], user_id=user.id)
    return doc


def test_jurnalul_si_decontul_tva(client, db):
    user, org, h = _setup(db)
    _invoice(db, org, date(2026, 3, 10), "F-1", ("1000.00", "20"), ("500.00", "8"))
    _invoice(db, org, date(2026, 4, 2), "F-2", ("200.00", "20"))
    _invoice(db, org, date(2025, 12, 31), "F-0", ("999.00", "20"))  # în afara perioadei
    p = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    r = client.get(f"/organizations/{org.id}/reports/vat", params=p, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 3
    rates = {Decimal(t["rate"]): t for t in body["by_rate"]}
    assert Decimal(rates[Decimal(20)]["base"]) == 1200 and Decimal(rates[Decimal(20)]["vat"]) == 240
    assert Decimal(rates[Decimal(8)]["vat"]) == 40
    assert Decimal(body["vat_total"]) == 280 and len(body["by_month"]) == 2
    only8 = client.get(f"/organizations/{org.id}/reports/vat", params={**p, "rate": "8"}, headers=h).json()
    assert len(only8["rows"]) == 1
    x = client.get(f"/organizations/{org.id}/reports/vat.xlsx", params=p, headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    bad = client.get(f"/organizations/{org.id}/reports/vat", params={"date_from": "2026-05-01", "date_to": "2026-01-01"}, headers=h)
    assert bad.status_code == 422


def test_cartea_mare(client, db):
    user, org, h = _setup(db)
    acc = make_accounts(db, org, "242", "521", "713")
    _post(db, org, user, acc, date(2026, 1, 10), "713", "521", "1000")
    _post(db, org, user, acc, date(2026, 2, 5), "521", "242", "600")
    p = {"date_from": "2026-02-01", "date_to": "2026-02-28"}
    r = client.get(f"/organizations/{org.id}/reports/general-ledger", params=p, headers=h)
    assert r.status_code == 200
    rows = {a["code"]: a for a in r.json()["accounts"]}
    assert Decimal(rows["521"]["opening"]) == -1000 and Decimal(rows["521"]["closing"]) == -400
    assert Decimal(rows["521"]["turnover_debit"]) == 600 and len(rows["521"]["months"]) == 1
    assert "713" in rows and Decimal(r.json()["total_debit"]) == Decimal(r.json()["total_credit"]) == 600
    one = client.get(f"/organizations/{org.id}/reports/general-ledger", params={**p, "account_id": str(acc["242"].id)}, headers=h)
    assert [a["code"] for a in one.json()["accounts"]] == ["242"]
    x = client.get(f"/organizations/{org.id}/reports/general-ledger.xlsx", params=p, headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_verificarea_contabilitatii(client, db):
    user, org, h = _setup(db)
    acc = make_accounts(db, org, "242", "521", "713")
    acc["242"].account_kind = AccountKind.active
    db.flush()
    p = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    ok = client.get(f"/organizations/{org.id}/reports/accounting-check", params=p, headers=h).json()
    assert ok["ok"] is True and {c["code"] for c in ok["checks"]} == {"balance", "correspondence", "unposted", "abnormal"}

    _post(db, org, user, acc, date(2026, 2, 5), "521", "242", "600")  # 242 (activ) rămâne în credit
    unposted = _invoice(db, org, date(2026, 3, 1), "F-9", ("100.00", "20"))
    r = client.get(f"/organizations/{org.id}/reports/accounting-check", params=p, headers=h).json()
    checks = {c["code"]: c for c in r["checks"]}
    assert r["ok"] is False
    assert checks["abnormal"]["count"] == 1 and checks["abnormal"]["items"][0]["account_id"] == str(acc["242"].id)
    assert checks["unposted"]["count"] == 1 and checks["unposted"]["items"][0]["document_id"] == str(unposted.id)
    assert checks["balance"]["severity"] == "ok"
