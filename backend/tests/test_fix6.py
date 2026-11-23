"""Ecrane complete (fix6): punere în funcțiune, casare, ajustarea perioadei, tipuri de calcul, surse de documente,
subdiviziuni, contrapartide, finanțare primită, achiziții pe granturi, pachet donator, documente scanate (AI)."""

import base64
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.assistant.llm import LLMReply, ToolCall
from app.catalogs.models import Counterparty
from app.core.enums import DocumentType, LineKind, UserRole
from app.documents.models import Document, Invoice, InvoiceLine
from app.fix6.scans import llm_client
from app.fixed_assets.models import FixedAsset
from app.grants.models import BudgetLine, Grant, GrantTranche
from app.main import app
from app.posting.engine import LineInput, post_document
from app.posting.models import EntryLine
from tests.conftest import auth_headers, make_accounts, make_org, make_user

CHART = ("123", "124", "341.2", "623", "628", "521", "532")


@pytest.fixture
def ctx(db):
    user = make_user(db, "fix6@test.md")
    org = make_org(db, user, "AO Ecrane")
    acc = make_accounts(db, org, *CHART)
    return user, org, acc, auth_headers(user), f"/organizations/{org.id}"


def make_asset(db, org, acc, status="suspended", cost="1200.00", **kw):
    asset = FixedAsset(
        organization_id=org.id, inventory_no="MF-00001", name="Laptop", initial_cost=Decimal(cost),
        account_id=acc["123"].id, depreciation_account_id=acc["124"].id, status=status, **kw,
    )  # fmt: skip
    db.add(asset)
    db.flush()
    return asset


# ───────────── punere în funcțiune ─────────────


def test_punere_in_functiune_si_anulare(client, db, ctx):
    user, org, acc, h, base = ctx
    asset = make_asset(db, org, acc)
    url = f"{base}/fixed-assets/{asset.id}/commissioning"
    assert client.post(url, json={"commissioning_date": "2099-01-01", "useful_life_months": 12}, headers=h).status_code == 422
    assert client.post(url, json={"commissioning_date": "2026-03-10"}, headers=h).status_code == 422  # fără durată
    r = client.post(url, json={"commissioning_date": "2026-03-10", "useful_life_months": 24}, headers=h)
    assert r.status_code == 201, r.text
    event = r.json()
    db.refresh(asset)
    assert asset.status == "in_use" and asset.depreciation_start == date(2026, 4, 1) and asset.useful_life_months == 24
    assert client.post(url, json={"commissioning_date": "2026-03-10", "useful_life_months": 24}, headers=h).status_code == 409
    listed = client.get(f"{base}/fixed-asset-events?kind=commissioning", headers=h).json()
    assert [e["inventory_no"] for e in listed] == ["MF-00001"]

    r = client.post(f"{base}/fixed-asset-events/{event['id']}/cancel-commissioning", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    db.refresh(asset)
    assert asset.status == "suspended" and asset.depreciation_start is None
    assert client.post(f"{base}/fixed-asset-events/{event['id']}/cancel-commissioning", headers=h).status_code == 409


def test_punere_in_functiune_cere_rol_de_contabil(client, db, ctx):
    user, org, acc, h, base = ctx
    asset = make_asset(db, org, acc)
    viewer = make_user(db, "audit@test.md")
    from app.auth.models import OrganizationMember

    db.add(OrganizationMember(organization_id=org.id, user_id=viewer.id, role=UserRole.auditor))
    db.flush()
    r = client.post(f"{base}/fixed-assets/{asset.id}/commissioning", json={"commissioning_date": "2026-03-10", "useful_life_months": 12},
                    headers=auth_headers(viewer))  # fmt: skip
    assert r.status_code == 403


# ───────────── casare ─────────────


def test_casare_inregistreaza_si_se_anuleaza(client, db, ctx):
    user, org, acc, h, base = ctx
    asset = make_asset(db, org, acc, status="in_use", commissioning_date=date(2026, 1, 15))
    url = f"{base}/fixed-assets/{asset.id}/writeoff"
    body = {"writeoff_date": "2026-06-01", "reason": "uzură"}
    assert client.post(url, json=body, headers=h).status_code == 422  # lipsește contul de cheltuieli
    assert client.post(url, json={**body, "writeoff_date": "2026-01-01"}, headers=h).status_code == 422  # înainte de punere în funcțiune
    r = client.post(url, json={**body, "loss_account_id": str(acc["628"].id)}, headers=h)
    assert r.status_code == 201, r.text
    event = r.json()
    assert Decimal(event["amount"]) == Decimal("1200.00")
    db.refresh(asset)
    assert asset.status == "written_off"
    line = db.scalar(select(EntryLine).where(EntryLine.document_id == event["document_id"]))
    assert line.debit_account_id == acc["628"].id and line.credit_account_id == acc["123"].id and line.amount == Decimal("1200.00")
    assert client.post(url, json={**body, "loss_account_id": str(acc["628"].id)}, headers=h).status_code == 409

    r = client.post(f"{base}/fixed-asset-events/{event['id']}/cancel-writeoff", headers=h)
    assert r.status_code == 200, r.text
    db.refresh(asset)
    assert asset.status == "in_use"
    assert db.scalar(select(EntryLine).where(EntryLine.document_id == event["document_id"])) is None


# ───────────── ajustarea perioadei ─────────────


def test_ajustare_cu_stornare_si_anulare(client, db, ctx):
    user, org, acc, h, base = ctx
    body = {"adjustment_date": "2026-03-31", "description": "Cheltuieli angajate", "debit_account_id": str(acc["623"].id),
            "credit_account_id": str(acc["532"].id), "amount": "500.00", "reverse_next_month": True}  # fmt: skip
    assert client.post(f"{base}/period-adjustments", json={**body, "credit_account_id": body["debit_account_id"]}, headers=h).status_code == 422
    assert client.post(f"{base}/period-adjustments", json={**body, "amount": "0"}, headers=h).status_code == 422
    r = client.post(f"{base}/period-adjustments", json=body, headers=h)
    assert r.status_code == 201, r.text
    adj = r.json()
    assert adj["debit_account"] == "623" and adj["reversal_date"] == "2026-04-01"
    lines = db.scalars(select(EntryLine).where(EntryLine.organization_id == org.id)).all()
    assert sorted((ln.entry_date, ln.debit_account_id == acc["623"].id) for ln in lines) == [(date(2026, 3, 31), True), (date(2026, 4, 1), False)]

    r = client.post(f"{base}/period-adjustments/{adj['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert db.scalars(select(EntryLine).where(EntryLine.organization_id == org.id)).all() == []
    assert client.post(f"{base}/period-adjustments/{adj['id']}/cancel", headers=h).status_code == 409


# ───────────── tipuri de calcul ─────────────


def test_tipuri_de_calcul(client, db, ctx):
    user, org, acc, h, base = ctx
    url = f"{base}/payroll-calc-types"
    r = client.post(url, json={"code": "prm", "name": "Prima de sărbători", "kind": "accrual"}, headers=h)
    assert r.status_code == 201 and r.json()["code"] == "PRM"
    assert client.post(url, json={"code": "PRM", "name": "Alta", "kind": "accrual"}, headers=h).status_code == 409
    assert client.post(url, json={"code": "X", "name": "Tip", "kind": "altceva"}, headers=h).status_code == 422
    std = client.post(f"{url}/standard", headers=h)
    assert std.status_code == 201
    codes = [t["code"] for t in std.json()]
    assert codes.count("PRM") == 1 and "SAL" in codes and "IVS" in codes
    row = next(t for t in std.json() if t["code"] == "SAL")
    assert client.put(f"{url}/{row['id']}", json={**row, "name": "Salariu tarifar"}, headers=h).json()["name"] == "Salariu tarifar"
    assert client.delete(f"{url}/{row['id']}", headers=h).status_code == 204
    assert row["id"] not in [t["id"] for t in client.get(url, headers=h).json()]


# ───────────── surse de documente ─────────────


def test_surse_de_documente(client, db, ctx):
    user, org, acc, h, base = ctx
    url = f"{base}/document-sources"
    drive = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp"
    assert client.post(url, json={"kind": "google_drive", "name": "Drive", "location": "https://exemplu.md/x"}, headers=h).status_code == 422
    assert client.post(url, json={"kind": "server_folder", "name": "Server", "location": "relativ/folder"}, headers=h).status_code == 422
    assert client.post(url, json={"kind": "server_folder", "name": "Server", "location": "/srv/../etc"}, headers=h).status_code == 422
    assert client.post(url, json={"kind": "ftp", "name": "FTP", "location": "x"}, headers=h).status_code == 422
    r = client.post(url, json={"kind": "google_drive", "name": "Drive facturi", "location": drive}, headers=h)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.put(f"{url}/{sid}", json={"kind": "google_drive", "name": "Drive facturi", "location": drive, "is_active": False}, headers=h)
    assert r.json()["is_active"] is False
    assert client.delete(f"{url}/{sid}", headers=h).status_code == 204
    assert client.get(url, headers=h).json() == []


# ───────────── subdiviziuni ─────────────


def test_subdiviziuni_ierarhie_si_stergere(client, db, ctx):
    user, org, acc, h, base = ctx
    url = f"{base}/departments"
    root = client.post(url, json={"name": "Sediul central", "cuatm": "0100000"}, headers=h)
    assert root.status_code == 201
    rid = root.json()["id"]
    assert client.post(url, json={"name": "sediul central"}, headers=h).status_code == 409
    assert client.post(url, json={"name": "Birou", "cuatm": "123"}, headers=h).status_code == 422
    child = client.post(url, json={"name": "Biroul Bălți", "parent_id": rid}, headers=h).json()
    # fără cicluri
    assert client.put(f"{url}/{rid}", json={"name": "Sediul central", "parent_id": child["id"]}, headers=h).status_code == 422
    assert client.put(f"{url}/{rid}", json={"name": "Sediul central", "parent_id": rid}, headers=h).status_code == 422
    assert client.delete(f"{url}/{rid}", headers=h).status_code == 409  # are subordonate
    assert client.delete(f"{url}/{child['id']}", headers=h).status_code == 204
    assert client.delete(f"{url}/{rid}", headers=h).status_code == 204


# ───────────── contrapartide ─────────────


def test_contrapartide_modificare_si_stergere(client, db, ctx):
    user, org, acc, h, base = ctx
    a = client.post(f"{base}/counterparties", json={"name": "Furnizor A", "idno": "1002600000001"}, headers=h).json()
    client.post(f"{base}/counterparties", json={"name": "Furnizor B", "idno": "1002600000002"}, headers=h)
    assert client.put(f"{base}/counterparties/{a['id']}", json={"name": "Furnizor A", "idno": "1002600000002"}, headers=h).status_code == 409
    r = client.put(f"{base}/counterparties/{a['id']}", json={"name": "Furnizor A SRL", "idno": "1002600000001", "address": "Chișinău"}, headers=h)
    assert r.status_code == 200
    assert db.scalar(select(Counterparty.name).where(Counterparty.id == a["id"])) == "Furnizor A SRL"
    db.add(Document(organization_id=org.id, type=DocumentType.invoice, counterparty_id=a["id"], doc_date=date(2026, 1, 1)))
    db.flush()
    assert client.delete(f"{base}/counterparties/{a['id']}", headers=h).status_code == 409  # apare în documente


# ───────────── granturi: finanțare primită, achiziții, pachet donator ─────────────


def make_grant(db, org):
    grant = Grant(organization_id=org.id, code="G1", title="Grant test", currency="MDL", total_amount=Decimal("10000"),
                  start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))  # fmt: skip
    db.add(grant)
    db.flush()
    line = BudgetLine(grant_id=grant.id, code="1.1", name="Echipamente", planned_amount=Decimal("5000"))
    db.add(line)
    db.flush()
    return grant, line


def make_posted_invoice(db, org, acc, grant, line, cp, with_file=False):
    doc = Document(organization_id=org.id, type=DocumentType.invoice, doc_number="F-1", doc_date=date(2026, 2, 10),
                   total_amount=Decimal("300"), counterparty_id=cp.id, file_name="f1.pdf" if with_file else None)  # fmt: skip
    db.add(doc)
    db.flush()
    inv = Invoice(document_id=doc.id)
    db.add(inv)
    db.flush()
    db.add(InvoiceLine(invoice_id=inv.id, description="Imprimantă", amount=Decimal("300"), line_kind=LineKind.goods,
                       budget_line_id=line.id))  # fmt: skip
    db.flush()
    post_document(db, organization_id=org.id, document_id=doc.id, user_id=None,
                  lines=[LineInput(acc["628"].id, acc["532"].id, Decimal("300"), grant_id=grant.id, budget_line_id=line.id)])  # fmt: skip
    return doc


def test_transe_achizitii_si_pachet_donator(client, db, ctx):
    user, org, acc, h, base = ctx
    grant, line = make_grant(db, org)
    db.add(GrantTranche(grant_id=grant.id, number=1, planned_date=date(2026, 3, 1), amount=Decimal("4000"), currency="MDL"))
    db.flush()
    rows = client.get(f"{base}/tranches", headers=h).json()
    assert [(r["grant_code"], r["number"], r["status"]) for r in rows] == [("G1", 1, "planned")]

    cp = Counterparty(organization_id=org.id, name="Furnizor C")
    db.add(cp)
    db.flush()
    doc = make_posted_invoice(db, org, acc, grant, line, cp)

    purchases = client.get(f"{base}/reports/grant-purchases?grant_id={grant.id}", headers=h).json()
    assert [(p["grant_code"], p["description"], p["amount"]) for p in purchases] == [("G1", "Imprimantă", "300.00")]
    assert client.get(f"{base}/reports/grant-purchases?date_from=2026-03-01", headers=h).json() == []
    assert client.get(f"{base}/reports/grant-purchases?date_from=2026-05-01&date_to=2026-01-01", headers=h).status_code == 422

    pkg = client.get(f"{base}/grants/{grant.id}/donor-package", headers=h).json()
    assert pkg["total_spent"] == "300.00" and pkg["missing_files"] == 1
    assert pkg["lines"][0]["documents"][0]["doc_number"] == "F-1" and pkg["lines"][0]["documents"][0]["has_file"] is False
    doc.file_name = "f1.pdf"
    db.flush()
    assert client.get(f"{base}/grants/{grant.id}/donor-package", headers=h).json()["missing_files"] == 0
    csv = client.get(f"{base}/grants/{grant.id}/donor-package/csv", headers=h)
    assert csv.status_code == 200 and "F-1" in csv.text and "Echipamente" in csv.text
    assert client.get(f"{base}/grants/{doc.id}/donor-package", headers=h).status_code == 404


# ───────────── documente scanate ─────────────


class FakeLLM:
    def __init__(self, fields):
        self.fields = fields
        self.calls = []

    def complete(self, system, messages, tools):
        self.calls.append(messages)
        return LLMReply(tool_calls=[ToolCall("t1", "fill_fields", self.fields)] if self.fields else [])


PDF = base64.b64encode(b"%PDF-1.4 test").decode()


def test_documente_scanate_flux_complet(client, db, ctx):
    user, org, acc, h, base = ctx
    cp = Counterparty(organization_id=org.id, name="Furnizor D", idno="1002600000009")
    db.add(cp)
    db.flush()
    url = f"{base}/scanned-documents"
    assert client.post(url, json={"file_name": "x.exe", "mime_type": "application/x-msdownload", "content_base64": PDF}, headers=h).status_code == 422
    assert client.post(url, json={"file_name": "x.pdf", "mime_type": "application/pdf", "content_base64": "!!!"}, headers=h).status_code == 422
    r = client.post(url, json={"file_name": "factura.pdf", "mime_type": "application/pdf", "content_base64": PDF}, headers=h)
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["status"] == "new"
    assert client.post(url, json={"file_name": "alta.pdf", "mime_type": "application/pdf", "content_base64": PDF}, headers=h).status_code == 409

    assert client.get(f"{url}/{scan['id']}/file", headers=h).content == b"%PDF-1.4 test"
    # fără câmpuri completate, validarea e refuzată
    r = client.post(f"{url}/{scan['id']}/validate", headers=h)
    assert r.status_code == 422 and "data" in r.json()["detail"]

    llm = FakeLLM({"document_type": "invoice", "doc_number": "F-77", "doc_date": "2026-05-04", "total_amount": 120.5,
                   "currency": "mdl", "supplier_idno": "1002600000009"})  # fmt: skip
    app.dependency_overrides[llm_client] = lambda: llm
    r = client.post(f"{url}/{scan['id']}/extract", headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "to_review" and out["doc_number"] == "F-77" and out["total_amount"] == "120.50"
    assert out["currency"] == "MDL" and out["counterparty"] == "Furnizor D" and out["type"] == "invoice"
    assert llm.calls[0][0]["content"][0]["type"] == "document"

    r = client.patch(f"{url}/{scan['id']}", json={"total_amount": "130.00"}, headers=h)
    assert r.json()["total_amount"] == "130.00"
    assert client.patch(f"{url}/{scan['id']}", json={"total_amount": "-5"}, headers=h).status_code == 422
    r = client.post(f"{url}/{scan['id']}/validate", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "validated"
    assert client.patch(f"{url}/{scan['id']}", json={"doc_number": "x"}, headers=h).status_code == 409
    assert client.delete(f"{url}/{scan['id']}", headers=h).status_code == 409
    assert client.post(f"{url}/{scan['id']}/reopen", headers=h).json()["status"] == "to_review"
    assert client.post(f"{url}/{scan['id']}/reject", headers=h).json()["status"] == "rejected"
    assert [s["id"] for s in client.get(f"{url}?status_filter=rejected", headers=h).json()] == [scan["id"]]
    assert client.delete(f"{url}/{scan['id']}", headers=h).status_code == 204
    assert client.get(url, headers=h).json() == []
    app.dependency_overrides.pop(llm_client, None)


def test_scan_ai_nu_citeste_si_fara_cheie(client, db, ctx, monkeypatch):
    user, org, acc, h, base = ctx
    url = f"{base}/scanned-documents"
    scan = client.post(url, json={"file_name": "a.png", "mime_type": "image/png", "content_base64": PDF}, headers=h).json()
    app.dependency_overrides[llm_client] = lambda: FakeLLM(None)
    assert client.post(f"{url}/{scan['id']}/extract", headers=h).status_code == 422
    app.dependency_overrides.pop(llm_client, None)
    monkeypatch.setattr("app.assistant.llm.get_settings", lambda: type("S", (), {"anthropic_api_key": None})())
    r = client.post(f"{url}/{scan['id']}/extract", headers=h)
    assert r.status_code == 503 and "cheia API" in r.json()["detail"]


def test_scanurile_sunt_izolate_pe_organizatie(client, db, ctx):
    user, org, acc, h, base = ctx
    scan = client.post(f"{base}/scanned-documents", json={"file_name": "a.pdf", "mime_type": "application/pdf", "content_base64": PDF}, headers=h).json()
    other = make_user(db, "alt@test.md")
    org2 = make_org(db, other, "AO Alta")
    h2 = auth_headers(other)
    assert client.get(f"/organizations/{org2.id}/scanned-documents", headers=h2).json() == []
    assert client.get(f"/organizations/{org2.id}/scanned-documents/{scan['id']}/file", headers=h2).status_code == 404
    assert client.get(f"/organizations/{org.id}/scanned-documents", headers=h2).status_code in (403, 404)
