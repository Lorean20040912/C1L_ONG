from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.models import OrganizationMember
from app.core.enums import DocumentType, UserRole
from app.documents.models import Document
from app.grants.models import Grant
from app.posting.models import PostingRule
from tests.conftest import auth_headers, make_accounts, make_org, make_user


@pytest.fixture
def ong(db):
    user = make_user(db, "sef@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    make_accounts(db, org, "211", "242", "521", "537", "616", "713", "716", "717")
    grant = Grant(
        organization_id=org.id,
        code="SOR-1",
        title="Proiect",
        currency="MDL",
        total_amount=Decimal(1000),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number="EF7", doc_date=date(2026, 3, 5))
    db.add_all([grant, doc])
    db.flush()
    return user, org, grant, doc


def grant_expense(grant, amount="612.40"):
    attrs = {"funding": "special_purpose"}
    return [
        {"operation": "expense", "amount": amount, "grant_id": str(grant.id), "attributes": attrs},
        {"operation": "income_recognition", "amount": amount, "grant_id": str(grant.id), "attributes": attrs},
    ]


def test_previzualizarea_nu_inregistreaza(client, db, ong):
    user, org, grant, doc = ong
    r = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/preview",
        json={"document_type": "invoice", "operations": grant_expense(grant)},
        headers=auth_headers(user),
    )
    assert r.status_code == 200, r.text
    assert [(x["debit_account"], x["credit_account"], x["source_ref"]) for x in r.json()] == [
        ("716", "521", "IM188; ART sit.2"),
        ("537", "616", "IM188; ART sit.2"),
    ]
    assert not db.get(Document, doc.id).is_posted


def test_inregistrarea_dupa_reguli_si_auditul(client, db, ong):
    user, org, grant, doc = ong
    r = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/post",
        json={"document_type": "invoice", "operations": grant_expense(grant)},
        headers=auth_headers(user),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2
    audit = db.scalar(select(AuditLog).where(AuditLog.entity_id == doc.id, AuditLog.action == "post"))
    assert len(audit.new_values["rules"]) == 2
    assert "ART sit.2" in audit.new_values["rules"][0]


def test_cerere_cu_operatiuni_si_randuri_e_respinsa(client, ong):
    user, org, grant, doc = ong
    line = {"debit_account_id": str(grant.id), "credit_account_id": str(grant.id), "amount": "1"}
    r = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/post",
        json={"document_type": "invoice", "operations": grant_expense(grant), "lines": [line]},
        headers=auth_headers(user),
    )
    assert r.status_code == 422


def test_regula_lipsa_da_mesaj_clar(client, ong):
    user, org, grant, doc = ong
    r = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/post",
        json={"document_type": "invoice", "operations": [{"operation": "inexistenta", "amount": "1"}]},
        headers=auth_headers(user),
    )
    assert r.status_code == 422
    assert "Nu există regulă" in r.json()["detail"]


def test_corectia_contabilului_sef_cu_versiuni(client, db, ong):
    user, org, grant, doc = ong
    base = f"/organizations/{org.id}/posting-rules"
    rule = {
        "document_type": "invoice",
        "operation": "expense",
        "conditions": {"funding": "unrestricted"},
        "debit_account": "713",
        "credit_account": "521",
        "source_ref": "SEM",
        "valid_from": "2026-01-01",
        "change_reason": "cheltuielile administrative se țin pe 713",
    }
    r1 = client.post(base, json=rule, headers=auth_headers(user))
    assert r1.status_code == 201, r1.text
    assert r1.json()["version"] == 1
    r2 = client.post(
        base, json={**rule, "debit_account": "717", "valid_from": "2026-06-01"}, headers=auth_headers(user)
    )
    assert r2.json()["version"] == 2
    first = db.get(PostingRule, r1.json()["id"])
    db.refresh(first)
    assert first.valid_to == date(2026, 5, 31)

    # în martie se aplică versiunea 1 (713), din iunie versiunea 2 (717)
    ops = [
        {"operation": "expense", "amount": "10", "grant_id": str(grant.id), "attributes": {"funding": "unrestricted"}}
    ]
    march = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/preview",
        json={"document_type": "invoice", "operations": ops},
        headers=auth_headers(user),
    )
    assert march.json()[0]["debit_account"] == "713"
    june = client.post(
        f"/organizations/{org.id}/documents/{doc.id}/preview",
        json={"document_type": "invoice", "operations": [{**ops[0], "entry_date": "2026-06-15"}]},
        headers=auth_headers(user),
    )
    assert june.json()[0]["debit_account"] == "717"

    # o versiune retroactivă peste una existentă e refuzată
    assert client.post(base, json={**rule, "valid_from": "2026-02-01"}, headers=auth_headers(user)).status_code == 409

    listed = client.get(base, params={"on_date": "2026-03-01"}, headers=auth_headers(user)).json()
    own = [x for x in listed if x["organization_id"] == str(org.id)]
    assert [x["debit_account"] for x in own] == ["713"]
    assert any(x["organization_id"] is None for x in listed)


def test_corectia_cere_cont_existent_si_rol(client, db, ong):
    user, org, _, _ = ong
    base = f"/organizations/{org.id}/posting-rules"
    rule = {
        "document_type": "invoice",
        "operation": "expense",
        "debit_account": "999",
        "credit_account": "521",
        "source_ref": "SEM",
        "valid_from": "2026-01-01",
        "change_reason": "test",
    }
    r = client.post(base, json=rule, headers=auth_headers(user))
    assert r.status_code == 422
    assert "999" in r.json()["detail"]
    accountant = make_user(db, "contabil@exemplu.md")
    db.add(OrganizationMember(organization_id=org.id, user_id=accountant.id, role=UserRole.accountant))
    db.flush()
    r = client.post(base, json={**rule, "debit_account": "713"}, headers=auth_headers(accountant))
    assert r.status_code == 403


def test_regulile_altei_organizatii_nu_se_vad(client, db, ong):
    user, org, _, _ = ong
    db.add(
        PostingRule(
            organization_id=org.id,
            document_type="invoice",
            operation="expense",
            debit_account="713",
            credit_account="521",
            source_ref="SEM",
            valid_from=date(2026, 1, 1),
        )
    )
    db.flush()
    intrus = make_user(db, "intrus@exemplu.md")
    other = make_org(db, intrus, "AO Beta")
    listed = client.get(f"/organizations/{other.id}/posting-rules", headers=auth_headers(intrus)).json()
    assert all(x["organization_id"] is None for x in listed)
    assert client.get(f"/organizations/{org.id}/posting-rules", headers=auth_headers(intrus)).status_code == 404
