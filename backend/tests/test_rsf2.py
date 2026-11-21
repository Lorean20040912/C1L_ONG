"""RSF2: exportul XML al situațiilor financiare anuale, față de exemplul oficial."""

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.documents.models import Document
from app.core.enums import DocumentType
from app.posting.engine import LineInput, post_document
from tests.conftest import auth_headers, make_accounts, make_org, make_user
from tests.xml_structure import assert_format, assert_same_structure


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Beta")
    org.caem, org.sfs_office, org.cuiio, org.director_name = "9499", "DFC Centru", "40000000", "Director Exemplu"
    acc = make_accounts(db, org, "123", "124", "242", "3411", "521", "618", "718", "616", "537", "331")

    def post(d, dt, kt, amount):
        doc = Document(organization_id=org.id, type=DocumentType.other, doc_number=f"D{amount}{dt}", doc_date=d)
        db.add(doc)
        db.flush()
        post_document(db, organization_id=org.id, document_id=doc.id, user_id=user.id,
                      lines=[LineInput(debit_account_id=acc[dt].id, credit_account_id=acc[kt].id, amount=Decimal(amount))])  # fmt: skip

    post(date(2025, 3, 1), "123", "3411", 1000)  # mijloc fix primit în 2025
    post(date(2026, 2, 1), "3411", "124", 100)  # amortizare în 2026
    post(date(2026, 5, 1), "242", "618", 2000)
    post(date(2026, 6, 1), "718", "521", 800)
    post(date(2026, 7, 1), "537", "616", 500)
    post(date(2026, 7, 2), "242", "537", 500)
    post(date(2026, 12, 31), "618", "331", 2000)  # închiderea anului — nu se numără
    db.flush()
    return user, org


def _xml(client, org, user, year):
    r = client.get(f"/organizations/{org.id}/reports/rsf2.xml?year={year}", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    assert "rsf2_" in r.headers["content-disposition"]
    return r.content


def test_rsf2_are_structura_exemplului_oficial(client, ong):
    user, org = ong
    xml = _xml(client, org, user, 2026)
    assert_format(xml, "rsf2.xml")
    assert_same_structure(xml, "rsf2.xml")
    root = ET.fromstring(xml)
    assert root.find("peroidnalog/datefisc").text == "A/2026"
    assert (root.find("period/from").text, root.find("period/to").text) == ("01.01.2026", "31.12.2026")
    assert root.find("fiscCod/idno").text == org.idno


def test_rsf2_valori_din_contabilitate(client, ong):
    user, org = ong
    root = ET.fromstring(_xml(client, org, user, 2026))
    t1, t2, t3 = (int_map(root.find(f"{t}/row")) for t in ("table1", "table2", "table3"))
    # mijloace fixe: cost 1000 (și la început), amortizare 100 la sfârșit, valoarea contabilă 900
    assert [t1[f"r030c{c}"] for c in (4, 5, 6, 7)] == [1000, 1000, 100, 900]
    assert t1["r200c7"] == t1["r060c7"] == 900
    # rezultatul: 2000 venituri economice − 800 cheltuieli, statutar 500
    assert (t3["r040c4"], t3["r050c4"], t3["r060c4"]) == (2000, 800, 1200)
    assert (t3["r020c4"], t3["r110c4"]) == (500, 1700)
    assert t3["r110c3"] == 0  # anul precedent
    # bilanț: totalul activelor = totalul pasivelor, rezultatul anului în r210
    assert t2["r210c5"] == 1700
    assert t2["r190c5"] == t2["r400c5"] and t2["r190c4"] == t2["r400c4"]
    assert t2["r310c5"] == t2["r190c5"] - t2["r260c5"] - sum(t2[f"r{n}c5"] for n in (320, 330, 340, 350, 360, 370, 380))


def test_rsf2_an_invalid_si_acces(client, ong):
    user, org = ong
    r = client.get(f"/organizations/{org.id}/reports/rsf2.xml?year=1900", headers=auth_headers(user))
    assert r.status_code == 422
    assert client.get(f"/organizations/{org.id}/reports/rsf2.xml?year=2026").status_code == 401


def int_map(row):
    return {el.tag: int(el.text) for el in row if el.text and el.text.lstrip("-").isdigit()}
