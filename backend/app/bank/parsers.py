"""Parserele extraselor bancare (docs/09 §1): fișier → rânduri normalizate.

Profilul băncii (`bank_formats.layout`) alege parserul și spune ce coloană înseamnă ce:

```
{"parser": "delimited", "separator": "^", "header": true, "skip_rows": 1,
 "date_formats": ["%d.%m.%Y"],
 "fields": {"date": "DATA", "doc_number": "NDOC", "dc": "DC", "account": "CCL",
            "counterparty_iban": "CCOR", "counterparty_idno": "CFCCOR",
            "counterparty_name": "DENCT", "amount": "SUMN", "purpose": ["DE1", "DE2"]},
 "direction": {"field": "dc", "outgoing": ["D"], "incoming": ["C"]}}
```

- `delimited` — TXT / CSV cu separator; coloanele prin nume (cu antet) sau prin număr (fără antet);
- `fixed_width` — lățime fixă; câmpul = `[început, lungime]` (de la 0);
- `dbf` — DBF (dbfread); coloanele prin nume;
- `xml_rowdata` — `ROWDATA/ROW` cu atribute;
- `client_bank_exchange` — 1CClientBankExchange (`CHEIE=valoare`, `DocStart … DocEnd`), formatul DBO.

Direcția: după un câmp D/C (`direction.field`) sau `{"mode": "by_account"}` — dacă plătitorul e contul
nostru, plata e ieșire și contrapartida e beneficiarul (câmpurile `payer_*` / `receiver_*`).
Un câmp cu listă (`["DE1", "DE2"]`) se compune din mai multe coloane.
"""

import csv
import io
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.crypto import normalize_iban
from app.core.enums import PaymentDirection

DEFAULT_DATE_FORMATS = ["%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y%m%d", "%d.%m.%y", "%y%m%d"]

# cheile standard ale formatului 1CClientBankExchange (folosite dacă profilul nu le schimbă)
CLIENT_BANK_FIELDS = {
    "date": "DOCUMENTDATE",
    "doc_number": "DOCUMENTNUMBER",
    "amount": "AMOUNT",
    "payer_account": "PAYERACCOUNT",
    "payer_idno": "PAYERFCODE",
    "payer_name": "PAYER",
    "receiver_account": "RECEIVERACCOUNT",
    "receiver_idno": "RECEIVERFCODE",
    "receiver_name": "RECEIVER",
    "purpose": "GROUND",
    "tx_code": "TRANSACTIONCODE",
}


class ParseError(Exception):
    pass


@dataclass
class StatementRow:
    line_no: int
    tx_date: date
    direction: PaymentDirection
    amount: Decimal
    doc_number: str | None = None
    account: str | None = None  # IBAN-ul nostru din rând (dacă fișierul îl are)
    counterparty_iban: str | None = None
    counterparty_idno: str | None = None
    counterparty_name: str | None = None
    currency: str | None = None
    purpose: str | None = None
    tx_code: str | None = None


@dataclass
class ParseResult:
    rows: list[StatementRow] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # {"line": n, "error": "..."}


# ───────────────────────── valori ─────────────────────────


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = " ".join(str(value).split())
    return text or None


def parse_amount(value: Any) -> Decimal:
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    raw = "".join(str(value or "").split()).replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")  # 1,234.50
    raw = raw.replace(",", ".")
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ParseError(f"suma „{value}” nu este un număr") from None


def parse_date(value: Any, formats: list[str]) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = (str(value or "")).strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"data „{raw}” nu corespunde formatului")


# ───────────────────── citirea „înregistrărilor” brute ─────────────────────


def _records_delimited(text: str, layout: dict) -> list[tuple[int, Any]]:
    separator = layout.get("separator", ";")
    reader = csv.reader(io.StringIO(text), delimiter=separator, quotechar=layout.get("quote", '"'))
    rows = [(i, r) for i, r in enumerate(reader, start=1) if any(c.strip() for c in r)]
    header = None
    if layout.get("header", True) and rows:
        header = [c.strip().upper() for c in rows[0][1]]
        rows = rows[1:]
    rows = rows[layout.get("skip_rows", 0) :]
    if header is None:
        return rows
    return [(i, {header[k]: v for k, v in enumerate(r) if k < len(header)}) for i, r in rows]


def _records_fixed(text: str, layout: dict) -> list[tuple[int, Any]]:
    lines = [(i, ln.rstrip("\r\n")) for i, ln in enumerate(text.splitlines(), start=1)]
    lines = [(i, ln) for i, ln in lines if ln.strip()]
    return lines[layout.get("skip_rows", 0) :]


def _records_dbf(data: bytes, layout: dict, encoding: str) -> list[tuple[int, Any]]:
    from dbfread import DBF  # biblioteca citește doar din fișier

    fd, path = tempfile.mkstemp(suffix=".dbf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        table = DBF(path, encoding=encoding, char_decode_errors="replace", ignore_missing_memofile=True)
        records = [(i, {k.upper(): v for k, v in rec.items()}) for i, rec in enumerate(table, start=1)]
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise ParseError(f"fișierul DBF nu se poate citi: {exc}") from None
    finally:
        os.unlink(path)
    return records[layout.get("skip_rows", 0) :]


def _records_xml(data: bytes, layout: dict) -> list[tuple[int, Any]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"XML invalid: {exc}") from None
    tag = layout.get("row_tag", "ROW")
    return [
        (i, {k.upper(): v for k, v in el.attrib.items()} | {c.tag.upper(): c.text for c in el})
        for i, el in enumerate(root.iter(tag), start=1)
    ]


def _records_client_bank(text: str) -> list[tuple[int, Any]]:
    lines = text.splitlines()
    if not lines or not lines[0].strip().startswith("1CClientBankExchange"):
        raise ParseError("fișierul nu începe cu 1CClientBankExchange")
    records, current, start = [], None, 0
    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        # varianta CSV a Moldindconbank: un document pe rând, `DocStart,CHEIE=valoare,...`
        if line.startswith("DocStart,"):
            parts = line.split(",")
            rec = {}
            for p in parts[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    rec[k.strip().upper()] = v.strip()
            records.append((i, rec))
            continue
        if line.upper().startswith("DOCSTART"):
            current, start = {}, i
        elif line.upper().startswith("DOCEND"):
            if current is not None:
                records.append((start, current))
            current = None
        elif current is not None and "=" in line:
            k, v = line.split("=", 1)
            current[k.strip().upper()] = v.strip()
    return records


# ───────────────────────── normalizarea ─────────────────────────


def _get(record: Any, spec: Any, parser: str) -> Any:
    if spec is None:
        return None
    if isinstance(spec, list) and spec and not (parser == "fixed_width" and isinstance(spec[0], int)):
        parts = [_text(_get(record, s, parser)) for s in spec]
        return " ".join(p for p in parts if p) or None
    if parser == "fixed_width":
        start, length = spec
        return record[start : start + length].strip() or None
    if isinstance(record, dict):
        return record.get(str(spec).upper())
    index = int(spec)
    return record[index].strip() if index < len(record) else None


def _normalize(line_no: int, record: Any, layout: dict, parser: str, our_iban: str | None) -> StatementRow:
    fields = dict(CLIENT_BANK_FIELDS) if parser == "client_bank_exchange" else {}
    fields.update(layout.get("fields") or {})
    formats = layout.get("date_formats") or DEFAULT_DATE_FORMATS

    def value(name: str) -> Any:
        return _get(record, fields.get(name), parser)

    raw_date = value("date")
    if not raw_date and parser == "client_bank_exchange":
        raw_date = record.get("DATEWRITTEN")
    tx_date = parse_date(raw_date, formats)
    amount = parse_amount(value("amount"))
    if amount == 0:
        raise ParseError("suma este zero")
    direction_cfg = layout.get("direction") or (
        {"mode": "by_account"} if parser == "client_bank_exchange" else {"field": "dc"}
    )
    row = StatementRow(
        line_no=line_no,
        tx_date=tx_date,
        direction=PaymentDirection.incoming,
        amount=abs(amount),
        doc_number=_text(value("doc_number")),
        currency=(_text(value("currency")) or "").upper()[:3] or None,
        purpose=_text(value("purpose")),
        tx_code=_text(value("tx_code")),
    )
    if direction_cfg.get("mode") == "by_account":
        payer = normalize_iban(_text(value("payer_account")))
        receiver = normalize_iban(_text(value("receiver_account")))
        ours = normalize_iban(our_iban)
        if ours and payer == ours:
            side = "payer"
            row.direction, row.account = PaymentDirection.outgoing, payer
        elif ours and receiver == ours:
            side = "receiver"
            row.account = receiver
        else:
            raise ParseError("nici plătitorul, nici beneficiarul nu este contul ales")
        other = "receiver" if side == "payer" else "payer"
        row.counterparty_iban = normalize_iban(_text(value(f"{other}_account"))) or None
        row.counterparty_idno = _text(value(f"{other}_idno"))
        row.counterparty_name = _text(value(f"{other}_name"))
        return row

    if direction_cfg.get("field") == "sign":
        row.direction = PaymentDirection.outgoing if amount < 0 else PaymentDirection.incoming
    else:
        flag = (_text(value(direction_cfg.get("field", "dc"))) or "").upper()
        outgoing = [s.upper() for s in direction_cfg.get("outgoing", ["D"])]
        incoming = [s.upper() for s in direction_cfg.get("incoming", ["C", "K"])]
        if flag in outgoing:
            row.direction = PaymentDirection.outgoing
        elif flag not in incoming:
            raise ParseError(f"debit/credit necunoscut: „{flag}”")
    row.account = normalize_iban(_text(value("account"))) or None
    row.counterparty_iban = normalize_iban(_text(value("counterparty_iban"))) or None
    row.counterparty_idno = _text(value("counterparty_idno"))
    row.counterparty_name = _text(value("counterparty_name"))
    return row


def parse_statement(
    data: bytes, file_type: str, encoding: str | None, layout: dict, our_iban: str | None = None
) -> ParseResult:
    """Citește fișierul după profil. Rândurile greșite nu opresc importul: ajung în `errors`."""
    encoding = encoding or "cp1251"
    parser = layout.get("parser") or {"dbf": "dbf", "xml": "xml_rowdata", "dbo": "client_bank_exchange"}.get(
        file_type, "delimited"
    )
    if parser == "dbf":
        records = _records_dbf(data, layout, encoding)
    elif parser == "xml_rowdata":
        records = _records_xml(data, layout)
    else:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            raise ParseError(f"fișierul nu este în codificarea {encoding}: {exc}") from None
        text = text.lstrip("﻿")
        if parser == "delimited":
            records = _records_delimited(text, layout)
        elif parser == "fixed_width":
            records = _records_fixed(text, layout)
        elif parser == "client_bank_exchange":
            records = _records_client_bank(text)
        else:
            raise ParseError(f"parser necunoscut: {parser}")
    result = ParseResult()
    for line_no, record in records:
        try:
            result.rows.append(_normalize(line_no, record, layout, parser, our_iban))
        except ParseError as exc:
            result.errors.append({"line": line_no, "error": str(exc)})
    return result
