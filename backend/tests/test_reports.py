from datetime import date
from decimal import Decimal

from app.core.enums import DocumentType
from app.documents.models import Document
from app.posting.engine import LineInput, post_document
from tests.conftest import auth_headers, make_accounts, make_org, make_user


def _post(db, org, user, acc, d, *pairs):
    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number="OM", doc_date=d)
    db.add(doc)
    db.flush()
    lines = [LineInput(debit_account_id=acc[a].id, credit_account_id=acc[b].id, amount=Decimal(s)) for a, b, s in pairs]
    post_document(db, organization_id=org.id, document_id=doc.id, lines=lines, user_id=user.id)


def test_balanta_de_verificare(client, db):
    user = make_user(db, "c@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "242", "521", "713")
    _post(db, org, user, acc, date(2026, 1, 10), ("713", "521", "1000"))
    _post(db, org, user, acc, date(2026, 2, 5), ("521", "242", "600"), ("713", "521", "200"))
    r = client.get(
        f"/organizations/{org.id}/reports/trial-balance",
        params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
        headers=auth_headers(user),
    )
    assert r.status_code == 200
    rows = {x["code"]: x for x in r.json()["rows"]}
    assert Decimal(rows["521"]["opening_credit"]) == 1000 and Decimal(rows["521"]["closing_credit"]) == 600
    assert Decimal(rows["242"]["closing_credit"]) == 600 and Decimal(rows["713"]["closing_debit"]) == 1200
    t = {k: Decimal(v) for k, v in r.json()["totals"].items()}
    # balanța e echilibrată pe fiecare pereche de coloane
    assert t["opening_debit"] == t["opening_credit"] and t["turnover_debit"] == t["turnover_credit"] == 800
    assert t["closing_debit"] == t["closing_credit"]
    intrus = make_user(db, "i@exemplu.md")
    make_org(db, intrus, "AO Beta")
    assert (
        client.get(
            f"/organizations/{org.id}/reports/trial-balance",
            params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
            headers=auth_headers(intrus),
        ).status_code
        == 404
    )
