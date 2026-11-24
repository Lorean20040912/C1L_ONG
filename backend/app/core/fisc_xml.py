"""Piese comune pentru fișierele XML ale declarațiilor depuse la fisc.md / BNS.

Formatul urmează exporturile oficiale (docs/exemple-fisc/): declarația XML cu
`<?xml version="1.0" encoding="UTF-8" ?>`, rădăcina `<dec TypeName="...">`, elemente
goale scrise `<x />`, date `dd.mm.yyyy`, sume cu două zecimale și punct, perioada
`L/01/2026` (lună), `T/3/2026` (trimestru), `A/2025` (an).
"""

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

DECLARATION = '<?xml version="1.0" encoding="UTF-8" ?>\n'


def sub(parent: ET.Element, tag: str, text: object = None, **attrs: str) -> ET.Element:
    """Element copil; `text=None` sau "" dă un element gol (`<tag />`)."""
    el = ET.SubElement(parent, tag, attrs)
    if text not in (None, ""):
        el.text = str(text)
    return el


def date_text(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def money(value: Decimal | int | None, decimals: int = 2, *, empty_zero: bool = False) -> str:
    """Suma cu punct zecimal; `empty_zero` — câmpurile pe care fiscul le lasă goale la zero."""
    if value is None or (empty_zero and value == 0):
        return ""
    return f"{Decimal(value):.{decimals}f}"


def month_period(year: int, month: int) -> str:
    return f"L/{month:02d}/{year}"


def quarter_period(year: int, quarter: int) -> str:
    return f"T/{quarter}/{year}"


def year_period(year: int) -> str:
    return f"A/{year}"


def serialize(root: ET.Element) -> bytes:
    return (DECLARATION + ET.tostring(root, encoding="unicode")).encode("utf-8")
