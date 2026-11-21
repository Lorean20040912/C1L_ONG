"""Import 1C: parsare, solduri inițiale prin motor, repetare fără dubluri, reconciliere, izolare, roluri."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.catalogs.models import Account, Counterparty
from app.core.enums import UserRole
from app.onec_import.models import OnecIdMap, OnecImportRun, OpeningBalance
from app.onec_import.service import ImportFormatError, app_balances, parse_export, run_import
from app.posting.models import EntryLine
from tests.conftest import auth_headers, make_accounts, make_org, make_user

GUID = "11111111-1111-1111-1111-111111111111"

EXPORT = f"""<Export>
  <Accounts>
    <Account code="221" name="Creanțe comerciale" kind="active"/>
    <Account code="521" name="Datorii comerciale" kind="passive"/>
    <Account code="242" name="Conturi bancare" kind="active"/>
  </Accounts>
  <Counterparties>
    <Counterparty guid="{GUID}" name="Client SRL" idno="1003600000001" vat_code="0300001"/>
  </Counterparties>
  <Balances date="2026-01-01">
    <Balance account="221" debit="1500.50" credit="0" counterparty_guid="{GUID}"/>
    <Balance account="242" debit="8000" credit="0"/>
    <Balance account="521" debit="0" credit="9500.50"/>
  </Balances>
  <ControlBalances date="2026-01-01">
    <Balance account="221" debit="1500.50" credit="0"/>
    <Balance account="242" debit="8000" credit="0"/>
    <Balance account="521" debit="0" credit="9500.50"/>
  </ControlBalances>
</Export>"""


@pytest.fixture
def org(db):
    user = make_user(db, "import@exemplu.md")
    return user, make_org(db, user, "AO Import")


def test_parse_refuza_doctype_si_format_gresit():
    with pytest.raises(ImportFormatError):
        parse_export('<!DOCTYPE x [<!ENTITY a "b">]><Export/>')
    with pytest.raises(ImportFormatError):
        parse_export("<Altceva/>")
    with pytest.raises(ImportFormatError):
        parse_export('<Export><Balances date="2026-01-01"><Balance account="221" debit="1.005"/></Balances></Export>')


def test_import_solduri_si_reconciliere(db, org):
    user, o = org
    run = run_import(db, organization_id=o.id, user_id=user.id, text=EXPORT)
    assert run.status.value == "done"
    assert run.stats["accounts"]["created"] == 3
    assert run.reconciliation["ok"] is True and run.reconciliation["accounts"] == 3
    balances = app_balances(db, o.id, date(2026, 1, 1))
    assert balances == {"221": Decimal("1500.50"), "242": Decimal("8000.00"), "521": Decimal("-9500.50")}
    assert db.scalar(select(func.count()).select_from(OpeningBalance).where(OpeningBalance.organization_id == o.id)) == 3
    assert db.scalar(select(Counterparty).where(Counterparty.organization_id == o.id)).onec_guid is not None


def test_import_repetat_fara_dubluri(db, org):
    user, o = org
    run_import(db, organization_id=o.id, user_id=user.id, text=EXPORT)
    run_import(db, organization_id=o.id, user_id=user.id, text=EXPORT)
    count = lambda m: db.scalar(select(func.count()).select_from(m).where(m.organization_id == o.id))  # noqa: E731
    assert count(OpeningBalance) == 3
    assert count(Counterparty) == 1
    assert count(OnecIdMap) == 1
    assert count(EntryLine) == 3
    assert count(Account) == 4  # + contul tehnic 000


def test_reconcilierea_gaseste_diferente(db, org):
    user, o = org
    bad = EXPORT.replace('<Balance account="242" debit="8000" credit="0"/>\n  </ControlBalances>', "")
    bad = bad.replace('account="242" debit="8000" credit="0"/>\n    <Balance account="521" debit="0" credit="9500.50"/>\n  </ControlBalances>',
                      'account="242" debit="7999" credit="0"/>\n    <Balance account="521" debit="0" credit="9500.50"/>\n  </ControlBalances>')  # fmt: skip
    run = run_import(db, organization_id=o.id, user_id=user.id, text=bad)
    rec = run.reconciliation
    assert rec["ok"] is False and rec["differences"][0]["account_code"] == "242"
    assert rec["differences"][0]["difference"] == "1.00"


def test_api_import_eroare_noteaza_rularea_esuata(client, db, org):
    user, o = org
    r = client.post(f"/organizations/{o.id}/onec-import/runs", json={"xml": "<Export><Balances date='x'/></Export>"},
                    headers=auth_headers(user))  # fmt: skip
    assert r.status_code == 422
    runs = client.get(f"/organizations/{o.id}/onec-import/runs", headers=auth_headers(user)).json()
    assert runs[0]["status"] == "failed"


def test_api_flux_complet_si_reconciliere_manuala(client, db, org):
    user, o = org
    h = auth_headers(user)
    r = client.post(f"/organizations/{o.id}/onec-import/runs", json={"xml": EXPORT}, headers=h)
    assert r.status_code == 201 and r.json()["reconciliation"]["ok"] is True
    run_id = r.json()["id"]
    rows = [{"account_code": "221", "debit": "1500.50"}, {"account_code": "242", "debit": "1"}]
    r = client.post(f"/organizations/{o.id}/onec-import/runs/{run_id}/reconcile",
                    json={"date": "2026-01-31", "rows": rows}, headers=h)  # fmt: skip
    assert r.status_code == 200
    codes = {d["account_code"] for d in r.json()["reconciliation"]["differences"]}
    assert codes == {"242", "521"}
    ob = client.get(f"/organizations/{o.id}/onec-import/opening-balances", headers=h).json()
    assert [x["account_code"] for x in ob] == ["221", "242", "521"]


def test_izolare_si_roluri(client, db, org):
    user, o = org
    other = make_user(db, "alt@exemplu.md")
    other_org = make_org(db, other, "AO Alta")
    run = run_import(db, organization_id=o.id, user_id=user.id, text=EXPORT)
    db.commit()
    h = auth_headers(other)
    assert client.get(f"/organizations/{o.id}/onec-import/runs", headers=h).status_code == 404
    assert client.get(f"/organizations/{other_org.id}/onec-import/runs/{run.id}", headers=h).status_code == 404
    assert client.post(f"/organizations/{other_org.id}/onec-import/runs/{run.id}/reconcile",
                       json={"date": "2026-01-01", "rows": []}, headers=h).status_code == 404  # fmt: skip
    acc = make_user(db, "contabil@exemplu.md")
    from app.auth.models import OrganizationMember

    db.add(OrganizationMember(organization_id=o.id, user_id=acc.id, role=UserRole.accountant))
    db.flush()
    r = client.post(f"/organizations/{o.id}/onec-import/runs", json={"xml": EXPORT}, headers=auth_headers(acc))
    assert r.status_code == 403
    assert db.scalar(select(func.count()).select_from(OnecImportRun)) >= 1


def test_reimport_cu_sold_zero_anuleaza_inregistrarile(db, org):
    user, o = org
    run_import(db, organization_id=o.id, user_id=user.id, text=EXPORT)
    zero = EXPORT.replace('debit="1500.50"', 'debit="0"').replace('debit="8000"', 'debit="0"').replace(
        'credit="9500.50"', 'credit="0"')  # fmt: skip
    run = run_import(db, organization_id=o.id, user_id=user.id, text=zero)
    assert app_balances(db, o.id, date(2026, 1, 1)) == {}
    assert run.reconciliation["ok"] is True


def test_sume_cu_semn_spatii_si_encoding_declarat():
    xml = (
        '<?xml version="1.0" encoding="windows-1251"?><Export><Counterparties>'
        f'<Counterparty guid="{GUID}" name="Ștefan SRL"/></Counterparties>'
        '<Balances date="2026-01-01"><Balance account="221" debit="-50,00"/>'
        '<Balance account="521" credit="1 234,50"/></Balances></Export>'
    )
    p = parse_export(xml)
    assert p.counterparties[0].name == "Ștefan SRL"
    assert (p.balances[0].debit, p.balances[0].credit) == (0, Decimal("50.00"))
    assert p.balances[1].credit == Decimal("1234.50")
