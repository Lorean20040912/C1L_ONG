"""Modulul bancă: importul extraselor (deduplicare, contrapartidă, ciorne, înregistrare), exportul
ordinelor, cursul BNM, diferențele de curs la închiderea lunii, izolarea pe organizație."""

import base64
import tempfile
from datetime import date
from decimal import Decimal

import pytest
from dbfread import DBF
from sqlalchemy import select

from app.bank.models import BankAccount, BankFormat, BankTransaction, ExchangeRate
from app.catalogs.models import Counterparty
from app.core.crypto import is_encrypted
from app.core.enums import DocumentType, PaymentDirection
from app.documents.models import Document, PaymentOrder
from app.grants.models import Grant
from app.month_close.service import get_run, preview_step, revert_step, run_step
from app.posting.engine import LineInput, post_document
from app.posting.models import AccountingPolicy, EntryLine
from tests.conftest import auth_headers, make_accounts, make_org, make_user

OUR = "MD24AG000225100013104168"
EUR_IBAN = "MD51AG000225100013104169"
SUPPLIER_IBAN = "MD11ML000000002251234567"
DONOR_IBAN = "MD77VI000000002250000001"
CHART = ("234.4", "242", "243", "521", "537", "616", "622", "716", "722")


@pytest.fixture
def ong(db):
    user = make_user(db, "banca@exemplu.md")
    org = make_org(db, user, "AO Banca")
    acc = make_accounts(db, org, *CHART)
    for code in ("243", "521", "234.4"):
        acc[code].is_currency = True
    db.add(
        AccountingPolicy(organization_id=org.id, valid_from=date(2026, 1, 1),
                         grant_receivable_account_id=acc["234.4"].id, grant_recognition="on_receipt")
    )  # fmt: skip
    grant = Grant(organization_id=org.id, code="SOR-01", title="Proiect", funding_type="grant", currency="MDL",
                  total_amount=Decimal(100000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))  # fmt: skip
    supplier = Counterparty(organization_id=org.id, name="Furnizor SRL", idno="1003600000001")
    donor = Counterparty(organization_id=org.id, name="Fundația Donator", idno="1002600000009", iban_enc=DONOR_IBAN)
    db.add_all([grant, supplier, donor])
    db.flush()
    bank = BankAccount(organization_id=org.id, currency="MDL", account_id=acc["242"].id, grant_id=grant.id)
    bank.iban = OUR
    db.add(bank)
    db.flush()
    return user, org, acc, grant, supplier, donor, bank


def fmt(db, bank_name: str, direction: str, file_type: str | None = None) -> BankFormat:
    query = select(BankFormat).where(BankFormat.bank_name == bank_name, BankFormat.direction == direction)
    if file_type:
        query = query.where(BankFormat.file_type == file_type)
    return db.scalars(query).first()


def maib_txt(*rows: str) -> str:
    head = f"DATA^NDOC^DC^CCL^CCOR^CFCCOR^DENCT^TV^SUMN^DE1^DE2^DE3^DE4^COD_TRANZ\r\n^^^{OUR}^^^SOLD^^0^^^^^\r\n"
    return base64.b64encode((head + "".join(r + "\r\n" for r in rows)).encode("cp1251")).decode()


ROWS = (
    f"03.11.2026^101^D^{OUR}^{SUPPLIER_IBAN}^1003600000001^Furnizor SRL^MDL^1250.50^Plata factura AA1^^^^",
    f"04.11.2026^7^C^{OUR}^{DONOR_IBAN}^^Fundatia Donator^MDL^5000.00^Transa 1^^^^",
    f"04.11.2026^^D^{OUR}^^^^MDL^15.00^Comision bancar^^^^",
    f"04.11.2026^^D^{OUR}^^^^MDL^15.00^Comision bancar^^^^",
)


def do_import(client, h, org, bank, fmt_id, content, dry_run=False):
    return client.post(
        f"/organizations/{org.id}/bank-imports",
        headers=h,
        json={"bank_account_id": str(bank.id), "format_id": str(fmt_id), "file_name": "extras.txt",
              "content_base64": content, "dry_run": dry_run},
    )  # fmt: skip


def test_import_deduplicare_si_reimport(client, db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    h = auth_headers(user)
    profile = fmt(db, "MAIB", "import_statement", "txt")
    content = maib_txt(*ROWS)

    preview = do_import(client, h, org, bank, profile.id, content, dry_run=True)
    assert preview.status_code == 201, preview.text
    assert preview.json()["rows_created"] == 4 and preview.json()["dry_run"]
    assert db.scalar(select(BankTransaction.id)) is None  # previzualizarea nu scrie nimic

    first = do_import(client, h, org, bank, profile.id, content).json()
    assert (first["rows_total"], first["rows_created"], first["rows_skipped"], first["rows_failed"]) == (4, 4, 0, 0)
    tx = {t["doc_number"] or f"c{i}": t for i, t in enumerate(first["transactions"])}
    assert tx["101"]["direction"] == "outgoing" and tx["101"]["counterparty_id"] == str(supplier.id)  # după IDNO
    assert tx["7"]["counterparty_id"] == str(donor.id)  # după IBAN
    assert all(t["match"] == "new_draft" and t["grant_id"] == str(grant.id) for t in first["transactions"])
    assert len({t["document_id"] for t in first["transactions"]}) == 4  # cele două comisioane identice rămân două

    again = do_import(client, h, org, bank, profile.id, content).json()
    assert (again["rows_created"], again["rows_skipped"]) == (0, 4)
    # extrasul următor conține și rândurile vechi: se adaugă doar cel nou
    more = do_import(client, h, org, bank, profile.id, maib_txt(*ROWS, ROWS[0].replace("^101^", "^102^"))).json()
    assert (more["rows_created"], more["rows_skipped"]) == (1, 4)
    assert db.query(PaymentOrder).count() == 5


def test_import_randuri_gresite_si_alt_cont(client, db, ong):
    user, org, *_, bank = ong
    h = auth_headers(user)
    profile = fmt(db, "MAIB", "import_statement", "txt")
    content = maib_txt(
        f"03.11.2026^1^D^{SUPPLIER_IBAN}^^^^MDL^10^x^^^^",  # alt cont
        f"03.11.2026^2^D^{OUR}^^^^EUR^10^x^^^^",  # altă valută
        f"32.11.2026^3^D^{OUR}^^^^MDL^10^x^^^^",  # dată greșită
        f"03.11.2026^4^D^{OUR}^^^^MDL^abc^x^^^^",  # sumă greșită
    )
    body = do_import(client, h, org, bank, profile.id, content).json()
    assert body["rows_created"] == 0 and body["rows_failed"] == 4 and len(body["errors"]) == 4
    bad = do_import(client, h, org, bank, fmt(db, "MAIB (DBO)", "import_statement").id, content)
    assert bad.status_code == 422 and "1CClientBankExchange" in bad.json()["detail"]


def test_confirmare_si_inregistrare(client, db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    h = auth_headers(user)
    profile = fmt(db, "MAIB", "import_statement", "txt")
    body = do_import(client, h, org, bank, profile.id, maib_txt(*ROWS[:2])).json()
    by_no = {t["doc_number"]: t for t in body["transactions"]}
    res = client.post(
        f"/organizations/{org.id}/bank-imports/{body['id']}/post",
        headers=h,
        json={"items": [{"transaction_id": by_no["101"]["id"]}, {"transaction_id": by_no["7"]["id"], "grant_id": str(grant.id)}]},
    )
    assert res.status_code == 200, res.text
    assert all(r["ok"] for r in res.json()), res.json()
    code = {a.id: a.code for a in acc.values()}
    lines = sorted(
        (code[e.debit_account_id], code[e.credit_account_id], e.amount)
        for e in db.scalars(select(EntryLine).where(EntryLine.organization_id == org.id))
    )
    assert lines == [("242", "537", Decimal("5000.00")), ("521", "242", Decimal("1250.50"))]
    detail = client.get(f"/organizations/{org.id}/bank-imports/{body['id']}", headers=h).json()
    assert all(t["is_posted"] for t in detail["transactions"])
    # grantul altei organizații nu se poate alege
    other_user = make_user(db, "alta@exemplu.md")
    other = make_org(db, other_user, "AO Alta")
    foreign = Grant(organization_id=other.id, code="X", title="X", currency="MDL", total_amount=1,
                    start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))  # fmt: skip
    db.add(foreign)
    db.flush()
    body2 = do_import(client, h, org, bank, profile.id, maib_txt(ROWS[2])).json()
    res = client.post(
        f"/organizations/{org.id}/bank-imports/{body2['id']}/post", headers=h,
        json={"items": [{"transaction_id": body2["transactions"][0]["id"], "grant_id": str(foreign.id)}]},
    )  # fmt: skip
    assert res.json()[0] == {"transaction_id": body2["transactions"][0]["id"], "ok": False,
                             "error": "Grantul nu aparține organizației"}  # fmt: skip


def make_order(db, org, bank, supplier, number, amount, iban=SUPPLIER_IBAN) -> Document:
    doc = Document(organization_id=org.id, type=DocumentType.payment_order, doc_number=number,
                   doc_date=date(2026, 11, 10), total_amount=Decimal(amount), currency="MDL",
                   counterparty_id=supplier.id)  # fmt: skip
    db.add(doc)
    db.flush()
    db.add(PaymentOrder(document_id=doc.id, direction=PaymentDirection.outgoing, bank_account_id=bank.id,
                        purpose="Plata 100% servicii\nnoiembrie", beneficiary_iban=iban,
                        beneficiary_name=supplier.name, beneficiary_idno=supplier.idno))  # fmt: skip
    db.flush()
    return doc


def read_dbf(content: bytes) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".dbf") as fh:
        fh.write(content)
        fh.flush()
        return list(DBF(fh.name, encoding="cp1251"))


def test_export_ordine_si_potrivirea_la_import(client, db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}"
    d1 = make_order(db, org, bank, supplier, "PO-12", "1500.00")
    d2 = make_order(db, org, bank, supplier, "PO-13", "99.90")
    otp = fmt(db, "OTP Bank", "export_payments")
    res = client.post(f"{base}/payment-batches", headers=h,
                      json={"document_ids": [str(d1.id), str(d2.id)], "format_id": str(otp.id)})  # fmt: skip
    assert res.status_code == 201, res.text
    (batch,) = res.json()
    assert batch["orders_count"] == 2 and Decimal(batch["total_amount"]) == Decimal("1599.90")
    assert batch["file_name"] == f"plati_{OUR}.dbf" and batch["folder_path"].startswith("Bancă/Export/")
    file = client.get(f"{base}/payment-batches/{batch['id']}/file", headers=h)
    rows = read_dbf(file.content)
    assert [r["NDOC"] for r in rows] == ["12", "13"] and rows[0]["CCL"] == OUR and rows[0]["DATAV"] == "20261110"
    assert rows[0]["DE"] == "Plata 100 servicii noiembrie" and rows[0]["SUMN"] == 1500.0 and rows[0]["REZB"] == "R"
    assert {o.bank_status for o in db.scalars(select(PaymentOrder))} == {"exported"}

    # al doilea export al aceluiași ordin cere confirmare
    again = client.post(f"{base}/payment-batches", headers=h, json={"document_ids": [str(d1.id)], "format_id": str(otp.id)})
    assert again.status_code == 422 and "deja exportat" in again.json()["detail"]
    maib = fmt(db, "MAIB", "export_payments")
    forced = client.post(f"{base}/payment-batches", headers=h,
                         json={"document_ids": [str(d1.id)], "format_id": str(maib.id), "force": True})  # fmt: skip
    assert forced.status_code == 201
    maib_rows = read_dbf(client.get(f"{base}/payment-batches/{forced.json()[0]['id']}/file", headers=h).content)
    assert len(maib_rows) == 2 and maib_rows[0]["SUMN"] == 1500.0 and maib_rows[1]["DENC"] == "(R) Furnizor SRL"

    # extrasul cu plata exportată confirmă ordinul, nu creează ciornă nouă
    profile = fmt(db, "MAIB", "import_statement", "txt")
    body = do_import(client, h, org, bank, profile.id,
                     maib_txt(f"11.11.2026^12^D^{OUR}^{SUPPLIER_IBAN}^1003600000001^Furnizor^MDL^1500.00^x^^^^")).json()  # fmt: skip
    (tx,) = body["transactions"]
    assert tx["match"] == "exported_order" and tx["document_id"] == str(d1.id)
    db.expire_all()
    assert db.scalar(select(PaymentOrder.bank_status).where(PaymentOrder.document_id == d1.id)) == "executed"
    assert db.query(PaymentOrder).count() == 2


def test_export_refuza_incasari_si_fara_iban(client, db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    h = auth_headers(user)
    d = make_order(db, org, bank, supplier, "5", "10", iban=None)
    otp = fmt(db, "OTP Bank", "export_payments")
    res = client.post(f"/organizations/{org.id}/payment-batches", headers=h,
                      json={"document_ids": [str(d.id)], "format_id": str(otp.id)})  # fmt: skip
    assert res.status_code == 422 and "IBAN" in res.json()["detail"]
    imp = fmt(db, "MAIB", "import_statement", "txt")
    res = client.post(f"/organizations/{org.id}/payment-batches", headers=h,
                      json={"document_ids": [str(d.id)], "format_id": str(imp.id)})  # fmt: skip
    assert res.status_code == 422


def test_profiluri_banci_si_iban_criptat(client, db, ong):
    user, org, acc, *_ = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}"
    standard = client.get(f"{base}/bank-formats?direction=import_statement", headers=h).json()
    assert {f["bank_name"] for f in standard} >= {"MAIB", "Moldindconbank", "FinComBank", "OTP Bank"}
    assert all(f["is_standard"] for f in standard)
    std = standard[0]
    assert client.put(f"{base}/bank-formats/{std['id']}", headers=h, json={**std}).status_code == 409
    own = client.post(f"{base}/bank-formats", headers=h, json={
        "bank_name": "Victoriabank", "file_type": "csv", "direction": "import_statement", "encoding": "utf-8",
        "layout": {"parser": "delimited", "separator": ";", "fields": {"date": "DATA", "amount": "SUMA"}}})  # fmt: skip
    assert own.status_code == 201 and not own.json()["is_standard"]
    upd = client.put(f"{base}/bank-formats/{own.json()['id']}", headers=h, json={**own.json(), "encoding": "cp866"})
    assert upd.json()["encoding"] == "cp866" and upd.json()["version"] == 2
    bad = client.post(f"{base}/bank-formats", headers=h, json={**own.json(), "encoding": "nu-exista"})
    assert bad.status_code == 422

    created = client.post(f"{base}/bank-accounts", headers=h, json={
        "iban": "md24 ag00 0225 1000 1310 4170", "currency": "EUR", "account_id": str(acc["243"].id)})  # fmt: skip
    assert created.status_code == 201 and created.json()["iban"] == "MD24AG000225100013104170"
    stored = db.get(BankAccount, created.json()["id"])
    assert is_encrypted(stored.iban_enc) and "MD24" not in stored.iban_enc


def test_curs_manual_si_ultimul_curs_anterior(client, db, ong):
    user, org, *_ = ong
    h = auth_headers(user)
    base = f"/organizations/{org.id}"
    r = client.put(f"{base}/exchange-rates", headers=h, json={"currency": "eur", "rate_date": "2026-11-27", "rate": "19.5"})
    assert r.status_code == 200 and r.json()["currency"] == "EUR"
    client.put(f"{base}/exchange-rates", headers=h, json={"currency": "EUR", "rate_date": "2026-11-27", "rate": "19.6"})
    on = client.get(f"{base}/exchange-rates/on?currency=EUR&on=2026-11-29", headers=h).json()  # duminică
    assert Decimal(on["rate"]) == Decimal("19.6") and on["rate_date"] == "2026-11-27"
    assert client.get(f"{base}/exchange-rates/on?currency=EUR&on=2026-11-01", headers=h).status_code == 404
    assert len(client.get(f"{base}/exchange-rates?currency=EUR", headers=h).json()) == 1


# ───────────────────── diferențele de curs la închiderea lunii ─────────────────────


def post_lines(db, org, user, lines, number):
    doc = Document(organization_id=org.id, type=DocumentType.other, doc_number=number, doc_date=date(2026, 11, 5))
    db.add(doc)
    db.flush()
    post_document(db, organization_id=org.id, document_id=doc.id, lines=lines, user_id=user.id)
    return doc


def fx_entries(db, org, acc, run):
    code = {a.id: a.code for a in acc.values()}
    doc_id = next(s["document_id"] for s in run.steps if s["step"] == "fx_difference")
    return sorted(
        (code[e.debit_account_id], code[e.credit_account_id], e.amount, e.grant_id is not None)
        for e in db.scalars(select(EntryLine).where(EntryLine.document_id == doc_id))
    )


def test_diferente_de_curs_pe_537_si_pe_venituri_financiare(db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    d = date(2026, 11, 5)
    eur = dict(currency="EUR", entry_date=d)
    post_lines(db, org, user, [
        # tranșa grantului în EUR: 1 000 EUR la 19,50 → 243 (destinație specială)
        LineInput(debit_account_id=acc["243"].id, credit_account_id=acc["537"].id, amount=Decimal("19500.00"),
                  currency_amount=Decimal(1000), grant_id=grant.id, **eur),
        # datoria față de furnizor din grant, 200 EUR la 19,50
        LineInput(debit_account_id=acc["716"].id, credit_account_id=acc["521"].id, amount=Decimal("3900.00"),
                  currency_amount=Decimal(200), grant_id=grant.id, **eur),
        # mijloace proprii în EUR, 100 EUR la 19,50
        LineInput(debit_account_id=acc["243"].id, credit_account_id=acc["616"].id, amount=Decimal("1950.00"),
                  currency_amount=Decimal(100), **eur),
    ], "OP-EUR")  # fmt: skip

    missing = preview_step(db, org.id, 2026, 11, "fx_difference")
    assert missing.errors == ["Lipsește cursul BNM pentru EUR la 30.11.2026"]

    db.add(ExchangeRate(organization_id=org.id, currency="EUR", rate_date=date(2026, 11, 28), rate=Decimal("19.8")))
    db.flush()
    run_step(db, org.id, 2026, 11, "fx_difference", user.id)
    run = get_run(db, org.id, 2026, 11)
    assert fx_entries(db, org, acc, run) == [
        ("243", "537", Decimal("300.00"), True),  # 1000 × 0,30 — majorează finanțarea, nu e venit
        ("243", "622", Decimal("30.00"), False),  # 100 × 0,30 — venit financiar
        ("537", "521", Decimal("60.00"), True),  # datoria crește cu 200 × 0,30: curs nefavorabil
    ]
    # repetarea nu dublează: reevaluarea proprie nu intră în sold
    run_step(db, org.id, 2026, 11, "fx_difference", user.id)
    assert len(fx_entries(db, org, acc, get_run(db, org.id, 2026, 11))) == 3
    # cursul scade în luna următoare: diferențe în sens invers
    db.add(ExchangeRate(organization_id=org.id, currency="EUR", rate_date=date(2026, 12, 31), rate=Decimal("19.7")))
    db.flush()
    plan = preview_step(db, org.id, 2026, 12, "fx_difference")
    assert sorted((r.debit_account, r.credit_account, r.amount) for r in plan.rows) == [
        ("521", "537", Decimal("20.00")), ("537", "243", Decimal("100.00")), ("722", "243", Decimal("10.00")),
    ]  # fmt: skip
    revert_step(db, org.id, 2026, 11, "fx_difference", user.id)
    assert not db.get(Document, next(s["document_id"] for s in get_run(db, org.id, 2026, 11).steps
                                     if s["step"] == "fx_difference")).is_posted  # fmt: skip


def test_fara_solduri_in_valuta(db, ong):
    _, org, *_ = ong
    plan = preview_step(db, org.id, 2026, 11, "fx_difference")
    assert plan.errors == [] and plan.lines == [] and "Nu există" in plan.rows[0].label


# ───────────────────────── izolarea pe organizație ─────────────────────────


def test_izolarea_pe_organizatie(client, db, ong):
    user, org, acc, grant, supplier, donor, bank = ong
    h = auth_headers(user)
    profile = fmt(db, "MAIB", "import_statement", "txt")
    body = do_import(client, h, org, bank, profile.id, maib_txt(ROWS[0])).json()
    d = make_order(db, org, bank, supplier, "77", "10")
    otp = fmt(db, "OTP Bank", "export_payments")
    batch = client.post(f"/organizations/{org.id}/payment-batches", headers=h,
                        json={"document_ids": [str(d.id)], "format_id": str(otp.id)}).json()[0]  # fmt: skip
    own_fmt = client.post(f"/organizations/{org.id}/bank-formats", headers=h, json={
        "bank_name": "Proprie", "file_type": "txt", "direction": "import_statement", "layout": {"fields": {}}}).json()  # fmt: skip
    client.put(f"/organizations/{org.id}/exchange-rates", headers=h,
               json={"currency": "USD", "rate_date": "2026-11-02", "rate": "17.5"})  # fmt: skip

    intruder = make_user(db, "intrus@exemplu.md")
    other = make_org(db, intruder, "AO Intrus")
    other_bank = BankAccount(organization_id=other.id, currency="MDL")
    other_bank.iban = OUR
    db.add(other_bank)
    db.flush()
    hi = auth_headers(intruder)
    ob = f"/organizations/{other.id}"
    # datele organizației A nu se văd din B
    assert client.get(f"{ob}/bank-imports/{body['id']}", headers=hi).status_code == 404
    assert client.get(f"{ob}/bank-imports", headers=hi).json() == []
    assert client.get(f"{ob}/payment-batches/{batch['id']}/file", headers=hi).status_code == 404
    assert client.get(f"{ob}/payment-batches", headers=hi).json() == []
    assert own_fmt["id"] not in {f["id"] for f in client.get(f"{ob}/bank-formats", headers=hi).json()}
    assert client.put(f"{ob}/bank-formats/{own_fmt['id']}", headers=hi, json=own_fmt).status_code == 404
    assert client.get(f"{ob}/exchange-rates", headers=hi).json() == []
    # nici prin calea organizației A
    assert client.get(f"/organizations/{org.id}/bank-imports", headers=hi).status_code == 404
    # B nu poate folosi contul bancar, profilul propriu sau ordinele lui A
    assert do_import(client, hi, other, bank, profile.id, maib_txt(ROWS[0])).status_code == 422
    assert do_import(client, hi, other, other_bank, own_fmt["id"], maib_txt(ROWS[0])).status_code == 422
    res = client.post(f"{ob}/payment-batches", headers=hi, json={"document_ids": [str(d.id)], "format_id": str(otp.id)})
    assert res.status_code == 422
    res = client.post(f"{ob}/bank-imports/{body['id']}/post", headers=hi,
                      json={"items": [{"transaction_id": body["transactions"][0]["id"]}]})  # fmt: skip
    assert res.status_code == 404
    # același extras în B (alt cont bancar) se importă separat: cheia anti-dublură ține de cont
    assert do_import(client, hi, other, other_bank, profile.id, maib_txt(ROWS[0])).json()["rows_created"] == 1


def test_rolurile(client, db, ong):
    _, org, *_, bank = ong
    auditor = make_user(db, "auditor@exemplu.md")
    from app.auth.models import OrganizationMember
    from app.core.enums import UserRole

    db.add(OrganizationMember(organization_id=org.id, user_id=auditor.id, role=UserRole.auditor))
    db.flush()
    h = auth_headers(auditor)
    profile = fmt(db, "MAIB", "import_statement", "txt")
    assert do_import(client, h, org, bank, profile.id, maib_txt(ROWS[0])).status_code == 403
    assert client.get(f"/organizations/{org.id}/bank-imports", headers=h).status_code == 200
    assert client.put(f"/organizations/{org.id}/exchange-rates", headers=h,
                      json={"currency": "EUR", "rate_date": "2026-11-02", "rate": "19"}).status_code == 403  # fmt: skip


def test_migrarea_cripteaza_ibanurile_vechi(db):
    """Contul creat cu IBAN în clar (ca înainte de modulul bancă) se citește la fel."""
    user = make_user(db, "vechi@exemplu.md")
    org = make_org(db, user, "AO Veche")
    legacy = BankAccount(organization_id=org.id, iban_enc="MD00VECHI000000000000001", currency="MDL")
    db.add(legacy)
    db.flush()
    assert legacy.iban == "MD00VECHI000000000000001"
