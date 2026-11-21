"""Parserele extraselor și exportatorii, pe fișiere-exemplu fictive (fără bază de date)."""

import io
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest

from app.bank.exporters import ExportOrder, clean_doc_number, clean_purpose, export_orders, write_dbf
from app.bank.parsers import ParseError, parse_statement
from app.bank.rates import RateError, parse_bnm_xml
from app.core.crypto_bank import decrypt, encrypt
from app.core.enums import PaymentDirection

OUR = "MD24AG000225100013104168"
OTHER = "MD11ML000000002251234567"

MAIB_FIELDS = {
    "date": "DATA", "doc_number": "NDOC", "dc": "DC", "account": "CCL", "counterparty_iban": "CCOR",
    "counterparty_idno": "CFCCOR", "counterparty_name": "DENCT", "amount": "SUMN", "currency": "TV",
    "purpose": ["DE1", "DE2"],
}  # fmt: skip
MAIB_LAYOUT = {"parser": "delimited", "separator": "^", "header": True, "skip_rows": 1,
               "date_formats": ["%d.%m.%Y"], "fields": MAIB_FIELDS}  # fmt: skip


def test_txt_delimitat_maib_cp1251():
    text = (
        "DATA^NDOC^DC^CCL^CCOR^CFCCOR^DENCT^TV^SUMN^DE1^DE2\r\n"
        f"^^^{OUR}^^^SOLD INITIAL^MDL^1000.00^^\r\n"
        f"03.11.2026^101^D^{OUR}^{OTHER}^1003600000001^ООО «Ромашка»^MDL^1 250,50^Plata fact. AA0001234^rechizite\r\n"
        f"04.11.2026^7^C^{OUR}^{OTHER}^1002600000009^Fundatia Exemplu^MDL^5000^Transa 1 grant^\r\n"
        f"05.11.2026^8^X^{OUR}^{OTHER}^1^Gresit^MDL^10^^\r\n"
    ).encode("cp1251")
    result = parse_statement(text, "txt", "cp1251", MAIB_LAYOUT)
    assert len(result.rows) == 2 and result.errors == [{"line": 5, "error": "debit/credit necunoscut: „X”"}]
    out, inc = result.rows
    assert out.direction == PaymentDirection.outgoing and out.amount == Decimal("1250.50")
    assert out.tx_date == date(2026, 11, 3) and out.doc_number == "101" and out.account == OUR
    assert out.counterparty_name == "ООО «Ромашка»" and out.purpose == "Plata fact. AA0001234 rechizite"
    assert inc.direction == PaymentDirection.incoming and inc.counterparty_idno == "1002600000009"


def test_csv_fara_antet_coloane_prin_numar():
    data = "03-11-2026,12,D,MD11ML000000002251234567,1003600000001,99.90,Abonament\n".encode()
    layout = {"parser": "delimited", "separator": ",", "header": False, "date_formats": ["%d-%m-%Y"],
              "fields": {"date": 0, "doc_number": 1, "dc": 2, "counterparty_iban": 3, "counterparty_idno": 4,
                         "amount": 5, "purpose": 6}}  # fmt: skip
    (row,) = parse_statement(data, "csv", "utf-8", layout).rows
    assert row.amount == Decimal("99.90") and row.counterparty_iban == OTHER and row.purpose == "Abonament"


def test_latime_fixa():
    def rec(*parts):
        return "".join(str(v).ljust(n) for v, n in parts)

    line = rec(("20261103", 8), ("55", 10), ("D", 1), (OUR, 24), (OTHER, 24), ("1003600000001", 13),
               ("Furnizor SRL", 30), ("300.00", 15), ("Servicii de curatenie", 40))  # fmt: skip
    layout = {"parser": "fixed_width", "date_formats": ["%Y%m%d"],
              "fields": {"date": [0, 8], "doc_number": [8, 10], "dc": [18, 1], "account": [19, 24],
                         "counterparty_iban": [43, 24], "counterparty_idno": [67, 13], "counterparty_name": [80, 30],
                         "amount": [110, 15], "purpose": [125, 40]}}  # fmt: skip
    (row,) = parse_statement((line + "\r\n\r\n").encode("cp1251"), "txt", "cp1251", layout).rows
    assert row.doc_number == "55" and row.amount == Decimal("300.00") and row.counterparty_name == "Furnizor SRL"
    assert row.direction == PaymentDirection.outgoing and row.purpose == "Servicii de curatenie"


def test_dbf_scris_si_citit():
    fields = [
        {"name": "DATA", "type": "D"}, {"name": "NDOC", "type": "C", "length": 10},
        {"name": "DC", "type": "C", "length": 1}, {"name": "CCOR", "type": "C", "length": 30},
        {"name": "CFCCOR", "type": "C", "length": 18}, {"name": "DENCT", "type": "C", "length": 50},
        {"name": "SUMN", "type": "N", "length": 15, "decimals": 2}, {"name": "DE1", "type": "C", "length": 100},
    ]  # fmt: skip
    data = write_dbf(
        fields,
        [[date(2026, 11, 3), "101", "D", OTHER, "1003600000001", "Предприятие Штефан", Decimal("12.34"), "Plată"]],
        "cp866",
    )
    (row,) = parse_statement(data, "dbf", "cp866", {"parser": "dbf", "fields": MAIB_FIELDS}).rows
    assert row.tx_date == date(2026, 11, 3) and row.amount == Decimal("12.34")
    assert row.counterparty_name == "Предприятие Штефан" and row.direction == PaymentDirection.outgoing


def test_xml_rowdata():
    data = (
        '<?xml version="1.0" encoding="utf-8"?><ROWDATA>'
        f'<ROW DOCUMENTDATE="261103" DOCUMENTNO="9" AMOUNT="75.00" IBAN_A="{OUR}" IBAN_B="{OTHER}" '
        'CORRFISCALCODE="1003600000001" CORRSNAME="Furnizor" DETAILSOFPAYMENT="Telefonie"/>'
        f'<ROW DOCUMENTDATE="261104" DOCUMENTNO="10" AMOUNT="100" IBAN_A="{OTHER}" IBAN_B="{OUR}" '
        'FISCALCODE="1002600000009" CONTRAGENTSNAME="Donator" DETAILSOFPAYMENT="Donație"/></ROWDATA>'
    ).encode()
    layout = {"parser": "xml_rowdata", "direction": {"mode": "by_account"}, "date_formats": ["%y%m%d"],
              "fields": {"date": "DOCUMENTDATE", "doc_number": "DOCUMENTNO", "amount": "AMOUNT",
                         "payer_account": "IBAN_A", "receiver_account": "IBAN_B", "payer_idno": "FISCALCODE",
                         "receiver_idno": "CORRFISCALCODE", "payer_name": "CONTRAGENTSNAME",
                         "receiver_name": "CORRSNAME", "purpose": "DETAILSOFPAYMENT"}}  # fmt: skip
    out, inc = parse_statement(data, "xml", "utf-8", layout, our_iban=OUR).rows
    assert out.direction == PaymentDirection.outgoing and out.counterparty_iban == OTHER and out.counterparty_name == "Furnizor"
    assert inc.direction == PaymentDirection.incoming and inc.counterparty_idno == "1002600000009"


CBE = (
    "1CClientBankExchange(V:M.1)\r\nBEGINDATE=01.11.2026\r\nSECTIONACCOUNTSTART\r\nACCOUNT={our}\r\n"
    "SECTIONACCOUNTSTOP\r\nDocStart\r\nDOCUMENTNUMBER=15\r\nDOCUMENTDATE=03.11.2026\r\nPAYERACCOUNT={our}\r\n"
    "PAYER=AO Alfa\r\nRECEIVERACCOUNT={other}\r\nRECEIVERFCODE=1003600000001\r\nRECEIVER=Furnizor SRL\r\n"
    "AMOUNT=410.00\r\nGROUND=Plata serviciilor\r\nDocEnd\r\nDocStart\r\nDOCUMENTNUMBER=3\r\n"
    "DOCUMENTDATE=04.11.2026\r\nPAYERACCOUNT={other}\r\nPAYERFCODE=1002600000009\r\nPAYER=Donator\r\n"
    "RECEIVERACCOUNT={our}\r\nAMOUNT=2000.00\r\nGROUND=Transa\r\nDocEnd\r\n"
).format(our=OUR, other=OTHER)


def test_client_bank_exchange_dbo():
    out, inc = parse_statement(CBE.encode("cp1251"), "dbo", "cp1251", {"parser": "client_bank_exchange"}, OUR).rows
    assert (out.direction, out.amount, out.counterparty_idno) == (PaymentDirection.outgoing, Decimal("410.00"), "1003600000001")
    assert (inc.direction, inc.counterparty_name, inc.purpose) == (PaymentDirection.incoming, "Donator", "Transa")


def test_client_bank_exchange_varianta_csv_si_cont_strain():
    data = (
        "1CClientBankExchange\n"
        f"DocStart,DOCUMENTNUMBER=4,DOCUMENTDATE=05.11.2026,PAYERACCOUNT={OUR},RECEIVERACCOUNT={OTHER},AMOUNT=10.00\n"
        f"DocStart,DOCUMENTNUMBER=5,DOCUMENTDATE=05.11.2026,PAYERACCOUNT={OTHER},RECEIVERACCOUNT={OTHER},AMOUNT=1\n"
    ).encode()
    result = parse_statement(data, "dbo", "utf-8", {"parser": "client_bank_exchange"}, OUR)
    assert len(result.rows) == 1 and result.rows[0].doc_number == "4"
    assert "contul ales" in result.errors[0]["error"]


def test_fisier_invalid():
    with pytest.raises(ParseError):
        parse_statement(b"nu e 1C", "dbo", "utf-8", {"parser": "client_bank_exchange"})
    with pytest.raises(ParseError):
        parse_statement(b"<ROWDATA>", "xml", "utf-8", {"parser": "xml_rowdata"})


# ───────────────────────── export ─────────────────────────


def order(**kw) -> ExportOrder:
    base = dict(
        date=date(2026, 11, 10), doc_number="PO-0012", amount=Decimal("1500.00"), currency="MDL",
        purpose="Plata 100% pentru\nservicii", payer_iban=OUR, payer_idno="1012600000001", payer_name="AO Alfa",
        beneficiary_iban=OTHER, beneficiary_name="Furnizor SRL", beneficiary_idno="1003600000001",
    )  # fmt: skip
    return ExportOrder(**{**base, **kw})


def test_reguli_comune_export():
    assert clean_doc_number("PO-0012/a") == "0012"
    assert clean_purpose("Plata 100% pentru\nservicii") == "Plata 100 pentru servicii"


def test_export_dbf_maib_cu_rand_total():
    from dbfread import DBF

    layout = {"exporter": "dbf", "total_row_first": True, "fields": [
        {"name": "DATA", "type": "D", "value": "date"}, {"name": "NDOC", "type": "C", "length": 10, "value": "doc_number"},
        {"name": "CCOR", "type": "C", "length": 30, "value": "beneficiary_iban"},
        {"name": "DENC", "type": "C", "length": 55, "value": "beneficiary_name", "prefix": "(R) "},
        {"name": "SUMN", "type": "N", "length": 15, "decimals": 2, "value": "amount"},
        {"name": "TD", "type": "N", "length": 2, "decimals": 0, "value": "const:8"},
        {"name": "DE1", "type": "C", "length": 10, "value": "purpose", "part": 0, "part_length": 10},
        {"name": "DE2", "type": "C", "length": 220, "value": "purpose", "part": 1, "part_length": 10},
        {"name": "URGENT", "type": "C", "length": 1, "value": "urgent"},
    ]}  # fmt: skip
    data = export_orders([order(), order(doc_number="13", amount=Decimal("0.50"), is_urgent=True)], layout, "cp1251")
    path = io.BytesIO(data)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".dbf") as fh:
        fh.write(path.getvalue())
        fh.flush()
        rows = list(DBF(fh.name, encoding="cp1251"))
    assert len(rows) == 3 and rows[0]["SUMN"] == 1500.5 and rows[0]["NDOC"] == ""
    first = rows[1]
    assert first["DATA"] == date(2026, 11, 10) and first["NDOC"] == "0012" and first["DENC"] == "(R) Furnizor SRL"
    assert first["DE1"] == "Plata 100" and first["DE2"] == "pentru ser" and first["TD"] == 8
    assert rows[2]["URGENT"] == "U" and first["URGENT"] == "N"


def test_export_xml_si_bs_client():
    xml = export_orders([order()], {"exporter": "xml_rowdata", "fields": [
        {"name": "DOCUMENTDATE", "value": "date", "format": "%y%m%d"}, {"name": "AMOUNT", "value": "amount"},
        {"name": "IBAN_B", "value": "beneficiary_iban"}]}, "utf-8")  # fmt: skip
    row = ET.fromstring(xml).find("ROW")
    assert row.attrib == {"DOCUMENTDATE": "261110", "AMOUNT": "1500.00", "IBAN_B": OTHER}
    txt = export_orders([order()], {"exporter": "client_bank_exchange"}, "cp1251").decode("cp1251")
    assert txt.startswith("1CClientBankExchange") and "AMOUNT=1500.00" in txt and "DOCUMENTNUMBER=0012" in txt
    # fișierul exportat se poate citi înapoi cu parserul DBO
    (parsed,) = parse_statement(txt.encode("cp1251"), "dbo", "cp1251", {"parser": "client_bank_exchange"}, OUR).rows
    assert parsed.amount == Decimal("1500.00") and parsed.direction == PaymentDirection.outgoing


def test_curs_bnm_xml():
    data = (
        '<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="28.11.2026" name="Cursul oficial">'
        "<Valute><NumCode>978</NumCode><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>19.4321</Value></Valute>"
        "<Valute><NumCode>643</NumCode><CharCode>RUB</CharCode><Nominal>10</Nominal><Value>2.1050</Value></Valute>"
        "</ValCurs>"
    ).encode("cp1251")
    assert parse_bnm_xml(data) == {"EUR": Decimal("19.4321"), "RUB": Decimal("0.2105")}
    with pytest.raises(RateError):
        parse_bnm_xml(b"<ValCurs/>")


def test_criptarea_ibanului():
    token = encrypt(OUR, "cheie-test")
    assert token != OUR and decrypt(token, "cheie-test") == OUR
    assert decrypt("MD00VECHI") == "MD00VECHI"  # valorile vechi necriptate
    with pytest.raises(ValueError):
        decrypt(token, "alta-cheie")
