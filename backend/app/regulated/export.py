"""Exportul rapoartelor: Excel (openpyxl) și XML în formatul exporturilor oficiale
(docs/exemple-fisc/): 5-CON (BNS: `Header` + `Data` cu `CAP1_R{rând}_C1`, în mii lei)
și ONG17 (SFS: `fiscCod`, `table`, `table1`, `table2` = anexa 1D, `table3`).
"""

from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core import fisc_xml as fx

HEADER_FILL = PatternFill("solid", fgColor="F7E7A6")
BOLD = Font(bold=True)


def file_name(out) -> str:
    return f"{out.code}_{out.period_from:%Y-%m}_{out.period_to:%Y-%m}"


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def report_xlsx(out, organization_name: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = out.code
    ws.append([out.title])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([organization_name])
    ws.append([f"Perioada: {out.period_from:%d.%m.%Y} – {out.period_to:%d.%m.%Y}", f"Unitatea: {out.unit}",
               f"Versiunea formularului: {out.form_version}", f"Statut: {out.status.value}"])  # fmt: skip
    ws.append([])
    for key, value in out.header.items():
        ws.append([key, value])
    ws.append([])
    ws.append(["Cod rând", "Indicator", "Valoare", "Calculat", "Corectat manual"])
    for cell in ws[ws.max_row]:
        cell.font, cell.fill = BOLD, HEADER_FILL
    for row in out.rows:
        ws.append([row.code, "  " * row.indent + row.label, float(row.value), float(row.calculated),
                   "da" if row.overridden else ""])  # fmt: skip
        ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True)
        if row.has_formula:
            ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 2).font = ws.cell(ws.max_row, 3).font = BOLD
    _widths(ws, [10, 70, 16, 16, 16])

    if out.annex_1d:
        an = wb.create_sheet("Anexa 1D")
        an.append(["Anexa 1D — utilizarea sumelor din desemnarea procentuală (lei)"])
        an["A1"].font = BOLD
        for item in out.annex_1d:
            an.append([])
            an.append([f"{item['grant_code']} — desemnarea {item['designation_year']}"])
            an.append(["Rând", "Perioada desemnării", "Prima perioadă după", "A doua perioadă după", "Rămase (de restituit)"])
            for cell in an[an.max_row]:
                cell.font, cell.fill = BOLD, HEADER_FILL
            cols = item["columns"]

            def col(key: str, cols=cols) -> list:
                return [float(c[key]) if c else "X" for c in cols]

            an.append(["Sumele desemnate procentual", float(item["received"]), "X", "X", "X"])
            an.append(["Suma cheltuielilor TOTAL", *col("total"), "X"])
            an.append(["– activități de utilitate publică", *col("public_utility"), "X"])
            an.append(["– activități sociale, morale, culturale sau de caritate", *col("social_charity"), "X"])
            an.append(["– acoperirea cheltuielilor administrative", *col("administrative"), "X"])
            an.append(["Sume rămase la sfârșitul perioadei", "X", "X", "X", float(item["remaining"])])
        _widths(an, [55, 20, 20, 20, 22])

    if out.checks:
        ch = wb.create_sheet("Verificări")
        ch.append(["Tip", "Mesaj"])
        for cell in ch[1]:
            cell.font, cell.fill = BOLD, HEADER_FILL
        for check in out.checks:
            ch.append(["eroare" if check["severity"] == "error" else "avertisment", check["message"]])
        _widths(ch, [14, 100])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# rândurile 5-CON în ordinea din exportul oficial (fără 111 și 112: intră în rândul 110)
CON5_CELLS = (
    "010 011 012 013 014 015 016 017 018 019 020 021 022 023 024 025 026 027 028 029 030 040 050 051 052 "
    "053 054 055 056 057 058 059 060 061 062 063 069 070 071 072 073 074 075 076 077 078 079 080 081 082 "
    "089 090 091 092 100 110 120 130 131 140 141 142 150 160 170 171 172 173 174 180 190 200 210 220 221 "
    "222 223 224 225 230 300 310 320"
).split()

# rândurile ONG17 din table1/row, în ordinea din exportul oficial
ONG17_CELLS = (
    "010 0101 01011 01012 01013 01014 0102 01021 010211 01022 01023 010231 01024 010241 020 030 040 050 060"
).split()
ONG17_CATEGORIES = "ABCDEFG"
XML_FORMS = ("5-CON", "ONG17")


def has_xml(code: str) -> bool:
    return code in XML_FORMS


def _values(out) -> dict[str, Decimal]:
    return {row.code: row.value for row in out.rows}


def _con5_xml(out) -> bytes:
    h = out.header
    quarter = str(h.get("TRIM") or (out.period_from.month - 1) // 3 + 1)
    root = ET.Element("dec", {"TypeName": "5-con_22"})
    head = fx.sub(fx.sub(root, "DataSet"), "Header")
    fx.sub(head, "ENT_NAME", h.get("ENT_NAME"))
    fx.sub(head, "STREET")
    fx.sub(head, "FISCCOD_FISC", title="")
    fx.sub(head, "CUATM", h.get("CUATM"), title="")
    fx.sub(head, "IDNO", h.get("IDNO"))
    fx.sub(head, "CFP", h.get("CFP"), title="")
    fx.sub(head, "CFOJ", h.get("CFOJ"), title="")
    fx.sub(head, "CAEM", h.get("CAEM"), title="")
    fx.sub(head, "HEAD", h.get("HEAD"))
    fx.sub(head, "emal")
    fx.sub(head, "PHONE")
    fx.sub(head, "nalogPeriodLetter", "T")
    fx.sub(head, "YEAR", title="")
    fx.sub(head, "TRIM", quarter, title=quarter)
    fx.sub(head, "nalogPeriodType", fx.quarter_period(out.period_from.year, int(quarter)))
    fx.sub(head, "CUIIO", h.get("CUIIO"))
    fx.sub(head, "EXECUTOR", h.get("EXECUTOR"))
    fx.sub(head, "flag1", h.get("flag1", "1"))
    fx.sub(head, "flag2", h.get("flag2", "0"))
    data = fx.sub(root.find("DataSet"), "Data")
    values = _values(out)
    for code in CON5_CELLS:
        fx.sub(data, f"CAP1_R{code}_C1", None if code not in values else fx.money(values[code], 1))
    return fx.serialize(root)


def _ong17_xml(out) -> bytes:
    h = out.header
    root = ET.Element("dec", {"TypeName": "ong17"})
    fisc = fx.sub(root, "fiscCod")
    fx.sub(fisc, "fiscal", h.get("idno"))
    fx.sub(fisc, "name", h.get("name"))
    fx.sub(fisc, "fisc", h.get("sfs_office"), title="")
    fx.sub(fisc, "caem", h.get("caem"), title="")
    fx.sub(fx.sub(root, "peroidnalog"), "datefisc", fx.year_period(out.period_to.year))

    table = fx.sub(root, "table")
    fx.sub(table, "flag", 0)
    category = (h.get("ngo_category") or "").upper()
    for n, letter in enumerate(ONG17_CATEGORIES, start=1):
        row = fx.sub(table, f"row{n}")
        fx.sub(row, f"flag{n}", int(category == letter))
        if n == 2:
            fx.sub(row, "flag21", 0)

    row = fx.sub(fx.sub(root, "table1"), "row")
    values = _values(out)
    for code in ONG17_CELLS:
        fx.sub(row, f"r{code}", fx.money(values.get(code), empty_zero=True))

    annex = fx.sub(root, "table2")
    for item in out.annex_1d or [None]:
        arow = fx.sub(annex, "row")
        cols = (item or {}).get("columns") or [None] * 3

        def col(key: str, cols=cols) -> list[str]:
            return [fx.money(Decimal(c[key]), empty_zero=True) if c else "" for c in cols]

        fx.sub(arow, "ar1c2", fx.money(Decimal(item["received"]), empty_zero=True) if item else "")
        for n, key in enumerate(("total", "public_utility", "social_charity", "administrative"), start=2):
            for c, text in zip((2, 3, 4), col(key), strict=True):
                fx.sub(arow, f"ar{n}c{c}", text)
        fx.sub(arow, "ar6c5", fx.money(Decimal(item["remaining"]), empty_zero=True) if item else "")
    fx.sub(fx.sub(root, "table3"), "summContr", fx.money(values.get("060"), empty_zero=True))
    director = fx.sub(root, "director")
    fx.sub(director, "director")
    fx.sub(director, "contabil")
    return fx.serialize(root)


def report_xml(out) -> bytes:
    """XML-ul declarației în formatul exportului oficial (docs/exemple-fisc)."""
    if out.code == "5-CON":
        return _con5_xml(out)
    if out.code == "ONG17":
        return _ong17_xml(out)
    raise ValueError(f"{out.code} nu are export XML")


def table_xlsx(title: str, subtitle: str, columns: list[str], rows: list[list], widths: list[int] | None = None) -> bytes:
    """Un tabel simplu (fișa contului, analiza contului)."""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([subtitle])
    ws.append([])
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font, cell.fill = BOLD, HEADER_FILL
    for r in rows:
        ws.append(r)
    if widths:
        _widths(ws, widths)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
