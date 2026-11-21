from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.auth.models import OrganizationMember
from app.core.enums import DocumentType, UserRole
from app.documents.models import Document
from app.grants.models import Grant
from app.posting.engine import LineInput, PostingError, post_document, turnover_differences, unpost_document
from app.posting.models import AccountingPeriod, AccountTurnover, EntryLine
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def setup(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, "211", "242", "521", "713")
    return user, org, acc


def new_doc(db, org, doc_date=date(2026, 11, 3)) -> Document:
    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number="AA1", doc_date=doc_date)
    db.add(doc)
    db.flush()
    return doc


def lines(acc, *pairs) -> list[LineInput]:
    return [LineInput(debit_account_id=acc[d].id, credit_account_id=acc[k].id, amount=Decimal(s)) for d, k, s in pairs]


def turnover(db, org, account, period=date(2026, 11, 1)) -> tuple[Decimal, Decimal]:
    t = db.scalar(
        select(AccountTurnover).where(
            AccountTurnover.organization_id == org.id,
            AccountTurnover.account_id == account.id,
            AccountTurnover.period == period,
        )
    )
    return (t.debit, t.credit) if t else (Decimal(0), Decimal(0))


# ───────────── Dt = Kt ─────────────


def test_inregistrarea_creeaza_randuri_si_rulaje_echilibrate(db, setup):
    user, org, acc = setup
    doc = new_doc(db, org)
    post_document(
        db,
        organization_id=org.id,
        document_id=doc.id,
        lines=lines(acc, ("211", "521", "1000.00"), ("713", "521", "250.50")),
        user_id=user.id,
    )
    assert doc.is_posted
    assert db.scalar(select(func.count()).where(EntryLine.document_id == doc.id)) == 2
    assert turnover(db, org, acc["521"]) == (Decimal(0), Decimal("1250.50"))
    assert turnover(db, org, acc["211"]) == (Decimal("1000.00"), Decimal(0))
    total_dt, total_kt = db.execute(
        select(func.sum(AccountTurnover.debit), func.sum(AccountTurnover.credit)).where(
            AccountTurnover.organization_id == org.id
        )
    ).one()
    assert total_dt == total_kt == Decimal("1250.50")


@pytest.mark.parametrize("amount", ["0", "-5", "10.001"])
def test_suma_invalida_e_respinsa(db, setup, amount):
    user, org, acc = setup
    doc = new_doc(db, org)
    with pytest.raises(PostingError):
        post_document(
            db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", amount)), user_id=user.id
        )
    assert db.scalar(select(func.count()).select_from(EntryLine)) == 0


def test_document_fara_randuri_e_respins(db, setup):
    user, org, _ = setup
    doc = new_doc(db, org)
    with pytest.raises(PostingError):
        post_document(db, organization_id=org.id, document_id=doc.id, lines=[], user_id=user.id)


def test_cont_sintetic_nu_primeste_inregistrari(db, setup):
    user, org, acc = setup
    acc["211"].is_group = True
    db.flush()
    doc = new_doc(db, org)
    with pytest.raises(PostingError, match="sintetic"):
        post_document(
            db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "5")), user_id=user.id
        )


# ───────────── perioada închisă ─────────────


def test_perioada_inchisa_blocheaza_inregistrarea(db, setup):
    user, org, acc = setup
    db.add(AccountingPeriod(organization_id=org.id, year=2026, month=11, is_closed=True))
    db.flush()
    doc = new_doc(db, org)
    with pytest.raises(PostingError, match="închisă"):
        post_document(
            db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "10")), user_id=user.id
        )
    assert not doc.is_posted
    assert db.scalar(select(func.count()).select_from(AccountTurnover)) == 0


def test_perioada_inchisa_blocheaza_anularea(db, setup):
    user, org, acc = setup
    doc = new_doc(db, org)
    post_document(
        db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "10")), user_id=user.id
    )
    db.add(AccountingPeriod(organization_id=org.id, year=2026, month=11, is_closed=True))
    db.flush()
    with pytest.raises(PostingError, match="închisă"):
        unpost_document(db, organization_id=org.id, document_id=doc.id, user_id=user.id)
    assert doc.is_posted


def test_alta_luna_inchisa_nu_deranjeaza(db, setup):
    user, org, acc = setup
    db.add(AccountingPeriod(organization_id=org.id, year=2026, month=10, is_closed=True))
    db.flush()
    doc = new_doc(db, org)
    post_document(
        db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "10")), user_id=user.id
    )
    assert doc.is_posted


# ───────────── totaluri = suma înregistrărilor ─────────────


def test_totalurile_egale_cu_suma_inregistrarilor(db, setup):
    user, org, acc = setup
    grant = Grant(
        organization_id=org.id,
        code="SOR-1",
        title="Proiect",
        currency="MDL",
        total_amount=Decimal(100000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    db.add(grant)
    db.flush()
    docs = []
    for i, d in enumerate([date(2026, 10, 15), date(2026, 11, 3), date(2026, 11, 20), date(2027, 1, 5)]):
        doc = new_doc(db, org, d)
        ls = lines(acc, ("211", "521", f"{100 + i}.25"), ("713", "242", "40"))
        ls[1].grant_id = grant.id
        post_document(db, organization_id=org.id, document_id=doc.id, lines=ls, user_id=user.id)
        docs.append(doc)
    assert turnover_differences(db, org.id) == []

    # reînregistrare cu alte sume și anulare: totalurile rămân exacte
    post_document(
        db, organization_id=org.id, document_id=docs[1].id, lines=lines(acc, ("713", "521", "999.99")), user_id=user.id
    )
    unpost_document(db, organization_id=org.id, document_id=docs[2].id, user_id=user.id)
    assert turnover_differences(db, org.id) == []
    assert db.scalar(select(func.count()).where(EntryLine.document_id == docs[1].id)) == 1


def test_anularea_sterge_inregistrarile_si_rulajele(db, setup):
    user, org, acc = setup
    doc = new_doc(db, org)
    post_document(
        db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "10")), user_id=user.id
    )
    unpost_document(db, organization_id=org.id, document_id=doc.id, user_id=user.id)
    assert not doc.is_posted
    assert db.scalar(select(func.count()).select_from(EntryLine)) == 0
    assert db.scalar(select(func.count()).select_from(AccountTurnover)) == 0


def test_inregistrarile_merg_in_partitia_anului(db, setup):
    user, org, acc = setup
    doc = new_doc(db, org, date(2026, 5, 1))
    post_document(
        db, organization_id=org.id, document_id=doc.id, lines=lines(acc, ("211", "521", "10")), user_id=user.id
    )
    part = db.scalar(text("SELECT tableoid::regclass::text FROM entry_lines WHERE document_id = :d"), {"d": doc.id})
    assert part == "entry_lines_2026"


# ───────────── izolarea între organizații ─────────────


def test_contul_altei_organizatii_e_respins(db, setup):
    user, org, acc = setup
    other = make_org(db, user, "AO Beta")
    other_acc = make_accounts(db, other, "211")
    doc = new_doc(db, org)
    bad = [LineInput(debit_account_id=other_acc["211"].id, credit_account_id=acc["521"].id, amount=Decimal(5))]
    with pytest.raises(PostingError, match="nu aparține"):
        post_document(db, organization_id=org.id, document_id=doc.id, lines=bad, user_id=user.id)


def test_documentul_altei_organizatii_nu_se_gaseste(db, setup):
    user, org, acc = setup
    other = make_org(db, user, "AO Beta")
    doc = new_doc(db, org)
    with pytest.raises(PostingError, match="nu a fost găsit"):
        post_document(
            db, organization_id=other.id, document_id=doc.id, lines=lines(acc, ("211", "521", "5")), user_id=user.id
        )


def test_api_izolare_intre_organizatii(client, db, setup):
    user, org, acc = setup
    intrus = make_user(db, "intrus@exemplu.md")
    make_org(db, intrus, "AO Intrus")
    doc = new_doc(db, org)
    body = {
        "lines": [{"debit_account_id": str(acc["211"].id), "credit_account_id": str(acc["521"].id), "amount": "15"}]
    }
    base = f"/organizations/{org.id}/documents/{doc.id}"
    # utilizatorul altei organizații nu vede și nu înregistrează
    assert client.post(f"{base}/post", json=body, headers=auth_headers(intrus)).status_code == 404
    assert client.get(f"{base}/entries", headers=auth_headers(intrus)).status_code == 404
    assert client.get(f"/organizations/{org.id}/documents", headers=auth_headers(intrus)).status_code == 404
    # proprietarul da
    r = client.post(f"{base}/post", json=body, headers=auth_headers(user))
    assert r.status_code == 200, r.text
    assert len(client.get(f"{base}/entries", headers=auth_headers(user)).json()) == 1


def test_api_auditorul_nu_poate_inregistra(client, db, setup):
    _, org, acc = setup
    auditor = make_user(db, "auditor@exemplu.md")
    db.add(OrganizationMember(organization_id=org.id, user_id=auditor.id, role=UserRole.auditor))
    db.flush()
    doc = new_doc(db, org)
    body = {
        "lines": [{"debit_account_id": str(acc["211"].id), "credit_account_id": str(acc["521"].id), "amount": "15"}]
    }
    r = client.post(f"/organizations/{org.id}/documents/{doc.id}/post", json=body, headers=auth_headers(auditor))
    assert r.status_code == 403
    assert (
        client.get(f"/organizations/{org.id}/documents/{doc.id}/entries", headers=auth_headers(auditor)).status_code
        == 200
    )


def test_api_inchiderea_perioadei(client, db, setup):
    user, org, acc = setup
    doc = new_doc(db, org)
    h = auth_headers(user)
    assert client.post(f"/organizations/{org.id}/periods/2026/11/close", headers=h).status_code == 200
    body = {
        "lines": [{"debit_account_id": str(acc["211"].id), "credit_account_id": str(acc["521"].id), "amount": "15"}]
    }
    r = client.post(f"/organizations/{org.id}/documents/{doc.id}/post", json=body, headers=h)
    assert r.status_code == 422
    assert "închisă" in r.json()["detail"]
