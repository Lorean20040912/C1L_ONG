"""Exportul ordinelor de plată în formatul băncii (docs/09 §2).

Profilul de export (`bank_formats.layout`, direcția `export_payments`):

```
{"exporter": "dbf", "total_row_first": true,
 "fields": [{"name": "DATA", "type": "D", "value": "date"},
            {"name": "NDOC", "type": "C", "length": 10, "value": "doc_number"},
            {"name": "SUMN", "type": "N", "length": 15, "decimals": 2, "value": "amount"},
            {"name": "DE1", "type": "C", "length": 220, "value": "purpose", "part": 0, "part_length": 250}, ...]}
```

Exportatori: `dbf` (dBase III, scris aici — dbfread doar citește), `xml_rowdata` (FinComBank),
`client_bank_exchange` (BS-Client: Victoriabank, Moldindconbank...), `fixed_width` (TXT).
Valorile (`value`): `date`, `doc_number`, `payer_iban`, `payer_idno`, `payer_name`, `beneficiary_iban`,
`beneficiary_name`, `beneficiary_idno`, `amount`, `currency`, `purpose`, `urgent` (U/N), `residency` (R/N),
`transaction_code`, `bank_code`, sau `const:<text>`.

Regulile din 1C (docs/09): numărul documentului doar cu cifre; din destinație se scot `%` și
rândurile noi; destinația se taie la lungimea câmpului (OTP 210; MAIB DE1 + DE2).
"""

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class ExportOrder:
    date: date
    doc_number: str
    amount: Decimal
    currency: str
    purpose: str
    payer_iban: str
    payer_idno: str
    payer_name: str
    beneficiary_iban: str
    beneficiary_name: str
    beneficiary_idno: str
    is_urgent: bool = False
    bank_code: str = ""
    transaction_code: str = "001"


class ExportError(Exception):
    pass


def clean_doc_number(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def clean_purpose(value: str | None) -> str:
    return " ".join((value or "").replace("%", "").split())


def _value(order: ExportOrder | None, spec: dict, total: Decimal | None = None):
    source = spec.get("value", "")
    if source.startswith("const:"):
        return source[6:]
    if order is None:  # rândul-total al lotului (MAIB): doar suma
        return total if source == "amount" else ("" if spec.get("type", "C") != "D" else None)
    if source == "date":
        return order.date
    if source == "doc_number":
        return clean_doc_number(order.doc_number)
    if source == "purpose":
        text = clean_purpose(order.purpose)
        if "part" in spec:
            size = spec.get("part_length", spec.get("length", 250))
            return text[spec["part"] * size : (spec["part"] + 1) * size]
        return text
    if source == "urgent":
        return "U" if order.is_urgent else "N"
    if source == "residency":
        return "R"
    if source == "amount":
        return order.amount
    value = getattr(order, source, "") or ""
    return f"{spec['prefix']}{value}" if value and spec.get("prefix") else value


def _fmt(value, spec: dict) -> str:
    if isinstance(value, date):
        return value.strftime(spec.get("format", "%Y%m%d"))
    if isinstance(value, Decimal):
        return f"{value:.{spec.get('decimals', 2)}f}"
    text = "" if value is None else str(value)
    return text[: spec["length"]] if spec.get("length") else text


def write_dbf(fields: list[dict], records: list[list], encoding: str) -> bytes:
    """dBase III fără memo: C (text), N (număr), D (dată AAAALLZZ)."""
    today = date.today()
    specs = []
    for f in fields:
        ftype = f.get("type", "C")
        length = 8 if ftype == "D" else int(f.get("length", 10))
        specs.append((f["name"].upper()[:10], ftype, length, int(f.get("decimals", 0)) if ftype == "N" else 0))
    record_len = 1 + sum(s[2] for s in specs)
    header_len = 32 + 32 * len(specs) + 1
    out = bytearray(
        struct.pack("<BBBBIHH20x", 3, today.year - 1900, today.month, today.day, len(records), header_len, record_len)
    )
    for name, ftype, length, decimals in specs:
        out += struct.pack("<11sc4xBB14x", name.encode("ascii"), ftype.encode("ascii"), length, decimals)
    out += b"\r"
    for rec in records:
        out += b" "
        for (name, ftype, length, decimals), value in zip(specs, rec, strict=True):
            if ftype == "D":
                cell = value.strftime("%Y%m%d").encode() if isinstance(value, date) else b" " * 8
            elif ftype == "N":
                cell = (f"{Decimal(value or 0):.{decimals}f}" if value not in (None, "") else "").rjust(length).encode()
            else:
                cell = str(value or "").encode(encoding, errors="replace")[:length].ljust(length, b" ")
            if len(cell) > length:
                raise ExportError(f"valoarea din {name} nu încape în {length} caractere")
            out += cell
    out += b"\x1a"
    return bytes(out)


def export_orders(orders: list[ExportOrder], layout: dict, encoding: str | None) -> bytes:
    encoding = encoding or "cp1251"
    exporter = layout.get("exporter", "dbf")
    total = sum((o.amount for o in orders), Decimal(0))
    fields = layout.get("fields") or []
    if exporter == "dbf":
        def cell(o, f):
            v = _value(o, f)
            return v if f.get("type", "C") in ("D", "N") else _fmt(v, f)

        records = [[cell(o, f) for f in fields] for o in orders]
        if layout.get("total_row_first"):
            records.insert(0, [_value(None, f, total) for f in fields])
        return write_dbf(fields, records, encoding)
    if exporter == "fixed_width":
        lines = ["".join(_fmt(_value(o, f), f).ljust(f["length"])[: f["length"]] for f in fields) for o in orders]
        return ("\r\n".join(lines) + "\r\n").encode(encoding, errors="replace")
    if exporter == "xml_rowdata":
        root = ET.Element(layout.get("root_tag", "ROWDATA"))
        for o in orders:
            ET.SubElement(root, layout.get("row_tag", "ROW"), {f["name"]: _fmt(_value(o, f), f) for f in fields})
        return b'<?xml version="1.0" encoding="' + encoding.encode() + b'"?>\n' + ET.tostring(root, encoding=encoding, xml_declaration=False)
    if exporter == "client_bank_exchange":
        return _client_bank(orders, layout, encoding, total)
    raise ExportError(f"exportator necunoscut: {exporter}")


def _client_bank(orders: list[ExportOrder], layout: dict, encoding: str, total: Decimal) -> bytes:
    first, last = min(o.date for o in orders), max(o.date for o in orders)
    d = layout.get("date_format", "%d.%m.%Y")
    lines = [
        layout.get("header", "1CClientBankExchange(V:M.1)"),
        f"BEGINDATE={first:{d}}",
        f"ENDDATE={last:{d}}",
        "SECTIONACCOUNTSTART",
        f"ACCOUNT={orders[0].payer_iban}",
        f"OUTCOME={total:.2f}",
        f"CURRCODE={orders[0].currency}",
        "SECTIONACCOUNTSTOP",
    ]
    for o in orders:
        lines += [
            "DocStart",
            f"DOCUMENTNUMBER={clean_doc_number(o.doc_number)}",
            f"DOCUMENTDATE={o.date:{d}}",
            f"PAYERACCOUNT={o.payer_iban}",
            f"PAYERFCODE={o.payer_idno}",
            f"PAYER={o.payer_name}",
            f"RECEIVER={o.beneficiary_name}",
            f"RECEIVERFCODE={o.beneficiary_idno}",
            f"RECEIVERACCOUNT={o.beneficiary_iban}",
            "RESIDENCE=R",
            f"AMOUNT={o.amount:.2f}",
            f"GROUND={clean_purpose(o.purpose)[: layout.get('purpose_length', 210)]}",
            f"TRANSACTIONCODE={o.transaction_code}",
            f"TRANSFERTYPE={'U' if o.is_urgent else 'N'}",
            "DocEnd",
        ]
    return ("\r\n".join(lines) + "\r\n").encode(encoding, errors="replace")
