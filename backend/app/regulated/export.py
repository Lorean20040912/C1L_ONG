"""Exportul rapoartelor: Excel (openpyxl) și XML pentru portalul BNS (5-CON).

XML-ul 5-CON urmează elementele din docs/07: antetul `Header` (ENT_NAME, IDNO,
CUIIO, ... flag1/flag2) și celulele `CAP1_R{rând}_C1` (coloana 1 = realizat în
trimestru), în mii lei; numele elementului rădăcină și al tabelului vin din
`report_forms.structure.xml`, ca o versiune nouă a schemei să nu ceară cod nou.
"""

from io import BytesIO
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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


def report_xml(out, spec: dict) -> bytes:
    root = ET.Element(spec.get("root", "dec"))
    head = ET.SubElement(root, spec.get("header", "Header"))
    for key, value in out.header.items():
        ET.SubElement(head, key).text = "" if value is None else str(value)
    ET.SubElement(head, "DATE_FISC").text = f"{out.period_to:%d.%m.%Y}"
    table = ET.SubElement(root, spec.get("table", "CAP1"))
    pattern = spec.get("cell", "CAP1_R{code}_C1")
    for row in out.rows:
        ET.SubElement(table, pattern.format(code=row.code)).text = format(row.value, "f")
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
