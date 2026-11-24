"""RSF2 și 5-CON: registrul contabil care reproduce cifrele unei declarații reale depuse pentru 2025.

Cifrele (lei întregi în RSF2, mii lei cu o zecimală în 5-CON) sunt cele ale declarațiilor confirmate de
contabilul-șef; registrul de mai jos este plauzibil, dar inventat (fără date de identificare).
"""

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.core.enums import DocumentType
from app.documents.models import Document
from app.grants.models import CostItem
from app.posting.engine import LineInput, post_document
from tests.conftest import auth_headers, make_accounts, make_org, make_user

CODES = ("123", "223", "226", "234.4", "241", "242", "341.2", "425", "521", "531", "533", "537", "616", "617", "716", "717")
Q4 = date(2025, 11, 20)


@pytest.fixture
def declaratie(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Gamma")
    org.caem, org.sfs_office, org.cuiio, org.director_name = "9499", "DFC Centru", "40000000", "Director Exemplu"
    acc = make_accounts(db, org, *CODES)
    items = {code: CostItem(organization_id=org.id, name=f"Articol {code}", con5_article=code)
             for code in ("051", "056", "063", "076", "080", "089", "100", "111", "230")}  # fmt: skip
    db.add_all(items.values())
    db.flush()
    counter = iter(range(1, 1000))

    def post(d, dt, kt, amount, article=None):
        doc = Document(organization_id=org.id, type=DocumentType.other, doc_number=f"D{next(counter)}", doc_date=d)
        db.add(doc)
        db.flush()
        item = items[article].id if article else None
        post_document(db, organization_id=org.id, document_id=doc.id, user_id=user.id,
                      lines=[LineInput(debit_account_id=acc[dt].id, credit_account_id=acc[kt].id,
                                       amount=Decimal(amount), cost_item_id=item)])  # fmt: skip

    # taxa de aderare: încasată și recunoscută ca venit în trimestrul I (nu intră în 5-CON trimestrul IV)
    post(date(2025, 2, 10), "241", "425", 702)
    post(date(2025, 2, 15), "425", "617", 702)
    # grantul: creanța la semnare (793999), încasări 614182 → creanță rămasă 179817
    post(date(2025, 1, 15), "234.4", "537", 793999)
    post(date(2025, 3, 20), "242", "234.4", 614182)
    # mijloc fix din grant: fondul se formează (537 → 341.2) și se scoate din evidență în același an
    post(date(2025, 5, 5), "123", "521", 55829)
    post(date(2025, 5, 6), "537", "341.2", 55829)
    post(date(2025, 5, 7), "521", "242", 55829)
    post(date(2025, 6, 1), "341.2", "123", 55829)
    # avans acordat și creanță a personalului
    post(Q4, "223", "242", 30629)
    post(Q4, "226", "242", 934)
    # cheltuieli din grant (716) în trimestrul IV, cu articolele 5-CON; venitul corespunzător 616
    expenses = [("051", 20000), ("056", 5300), ("063", 52100), ("076", 1900), ("080", 600), ("089", 95600), ("230", 4946)]
    for article, amount in expenses:
        post(Q4, "716", "242", amount, article)
    post(Q4, "716", "531", 77500, "100")
    post(Q4, "531", "242", 57065)  # rămân datorate 20435
    post(Q4, "716", "533", 28100, "111")
    post(Q4, "533", "242", 24163)  # rămân datorate 3937
    post(Q4, "537", "616", 286046)
    post(Q4, "717", "242", 464)  # cheltuială a organizației fără articol 5-CON → rândul 230
    db.flush()
    return user, org


def _rows(root, table):
    return {el.tag: int(el.text) for el in root.find(f"{table}/row") if el.text and el.text.lstrip("-").isdigit()}


@pytest.fixture
def rsf2(client, declaratie):
    user, org = declaratie
    r = client.get(f"/organizations/{org.id}/reports/rsf2.xml?year=2025", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    root = ET.fromstring(r.content)
    return {t: _rows(root, t) for t in ("table1", "table2", "table3")}


def test_rsf2_anexa_3_surse_de_finantare(rsf2):
    t1 = rsf2["table1"]
    expected = {
        "030": (0, 793999, 341875, 452124), "060": (0, 793999, 341875, 452124),
        "110": (0, 702, 702, 0), "130": (0, 702, 702, 0),
        "150": (0, 55829, 55829, 0), "160": (0, 238, 0, 238), "180": (0, 56067, 55829, 238),
        "200": (0, 850768, 398406, 452362),
    }  # fmt: skip
    for code in (f"{n:03d}" for n in range(10, 210, 10)):
        got = tuple(t1[f"r{code}c{c}"] for c in (4, 5, 6, 7))
        assert got == expected.get(code, (0, 0, 0, 0)), code
    # sumele de control: sold final = început + majorări − diminuări, totalul = suma rândurilor
    for code in t1.keys() & {k for k in t1 if k.endswith("c4")}:
        row = code[:-2]
        assert t1[f"{row}c4"] + t1[f"{row}c5"] - t1[f"{row}c6"] == t1[f"{row}c7"]
    assert t1["r200c7"] == t1["r060c7"] + t1["r130c7"] + t1["r180c7"]


def test_rsf2_anexa_1_bilant(rsf2):
    t2 = rsf2["table2"]
    expected_end = {
        "110": 30629, "130": 934, "140": 179817, "141": 179817, "150": 265354, "180": 476734, "190": 476734,
        "210": 238, "260": 238, "310": 452124, "340": 20435, "350": 3937, "390": 476496, "400": 476734,
    }  # fmt: skip
    for code in (f"{n:03d}" for n in range(10, 410, 10)):
        assert t2[f"r{code}c5"] == expected_end.get(code, 0), code
    assert t2["r141c5"] == 179817
    assert all(v == 0 for k, v in t2.items() if k.endswith("c4"))  # începutul perioadei = 0 peste tot
    assert t2["r190c5"] == t2["r400c5"]  # activ = pasiv
    assert t2["r180c5"] == sum(t2[f"r{n}c5"] for n in (110, 130, 140, 150))
    assert t2["r390c5"] == sum(t2[f"r{n}c5"] for n in (310, 340, 350))


def test_rsf2_anexa_2_venituri_si_cheltuieli(rsf2):
    t3 = rsf2["table3"]
    expected = {"010": 286046, "020": 286046, "040": 702, "050": 464, "060": 238, "110": 238}
    for code in (f"{n:03d}" for n in range(10, 120, 10)):
        assert t3[f"r{code}c4"] == expected.get(code, 0), code
        assert t3[f"r{code}c3"] == 0  # anul precedent
    assert t3["r060c4"] == t3["r010c4"] - t3["r020c4"] + t3["r040c4"] - t3["r050c4"]
    assert t3["r110c4"] == rsf2["table2"]["r210c5"]  # excedentul din Anexa 2 = rândul 210 din bilanț


def _generate(client, org, user):
    r = client.post(f"/organizations/{org.id}/reports/tax-reports",
                    json={"code": "5-CON", "period_from": "2025-10-01"}, headers=auth_headers(user))  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def test_5con_trimestrul_iv_2025(client, declaratie):
    user, org = declaratie
    report = _generate(client, org, user)
    v = {row["code"]: row["value"] for row in report["rows"]}
    expected = {
        "010": "286.0", "012": "286.0", "017": "286.0", "011": "0.0", "024": "0.0", "030": "0.0",
        "040": "286.5",
        "050": "77.4", "051": "20.0", "055": "5.3", "056": "5.3", "063": "52.1",
        "070": "98.1", "076": "1.9", "080": "0.6", "089": "95.6",
        "100": "77.5", "110": "28.1", "120": "5.4", "230": "5.4",
    }  # fmt: skip
    for code, value in expected.items():
        assert str(v[code]) == value or Decimal(str(v[code])) == Decimal(value), (code, v[code])
    # rândurile care nu apar în declarație sunt goale/zero
    for code in ("013", "014", "015", "016", "018", "052", "053", "054", "057", "060", "090", "130", "210", "220"):
        assert Decimal(str(v[code])) == 0, code
    assert report["header"]["flag1"] == "1" and report["header"]["TRIM"] == "4"
    # sumele de control: totalurile = suma componentelor
    d = {k: Decimal(str(x)) for k, x in v.items()}
    assert d["040"] == d["050"] + d["070"] + d["090"] + d["100"] + d["110"] + d["120"]
    assert d["050"] == d["051"] + d["055"] + d["063"]
    assert d["070"] == d["076"] + d["080"] + d["089"]

    xml = client.get(f"/organizations/{org.id}/reports/tax-reports/{report['id']}/export.xml", headers=auth_headers(user))
    assert xml.status_code == 200
    for tag, value in (("R010", "286.0"), ("R040", "286.5"), ("R050", "77.4"), ("R070", "98.1"), ("R100", "77.5"),
                       ("R110", "28.1"), ("R120", "5.4"), ("R230", "5.4")):  # fmt: skip
        assert f"<CAP1_{tag}_C1>{value}</CAP1_{tag}_C1>".encode() in xml.content, tag
