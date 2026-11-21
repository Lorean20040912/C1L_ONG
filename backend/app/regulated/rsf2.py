"""RSF2 — situațiile financiare anuale ale asociației obștești (XML, formatul docs/exemple-fisc/rsf2.xml).

Valorile se iau din contabilitate: bilanțul din soldurile conturilor (`account_turnovers`) la 1 ianuarie și
31 decembrie, rezultatul financiar din înregistrările veniturilor (6) și cheltuielilor (7) ale anului, fără
înregistrările de închidere (33x). Sumele sunt în lei întregi (rotunjire comercială).

Corespondența cu rândurile formularului (ipoteze de lucru; formularul oficial nu se află în depozit):
  table1 (active imobilizate; c4 cost la început, c5 cost la sfârșit, c6 uzura, c7 valoarea contabilă)
    r030 ← 12x (cost) și 124 (amortizarea); r110 ← 11x (cost) și 112 (amortizarea);
    r060, r130, r180 = totaluri pe grupe; r200 = r060 + r130 + r180 + r190. Celelalte rânduri rămân 0.
  table2 (bilanț; c4 = 01.01, c5 = 31.12)
    r010 ← 11x net, r020 ← 12x net, r030 ← alte conturi din clasa 1, r100 = total active imobilizate;
    r110 ← 21x, r130 ← 22x, r140 ← 23x (r141 = 234.4, creanțe pe granturi), r150 ← 24x, r160 ← alte din clasa 2,
    r180 = total active curente, r190 = r100 + r180;
    r200 ← 331/332 de la 1 ianuarie (rezultat reportat), r210 = rezultatul anului, r220 ← alte conturi din clasa 3
    (fără 33 și 34), r260 = total capital propriu; r310 ← 3411, r320 ← 3412, r330 ← alte conturi 34,
    r340 ← 521, r350 ← 531/533/534, r360 ← 535, r370 ← 537, r380 ← restul clasei 5 și clasa 4,
    r390 = r310..r380, r400 = r260 + r390. Rândurile r010..r100 de la r090, r230..r250, r270..r300 rămân 0.
  table3 (rezultatul financiar; c3 = anul precedent, c4 = anul raportat)
    r010 = venituri statutare (r020 ← 616, r030 ← restul), r040 = venituri din activitatea economică,
    r050 = cheltuieli ale activității economice, r060 = r040 − r050, r110 = total venituri − total cheltuieli.
    Impozitul și celelalte rânduri (r070..r100) rămân 0.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogs.models import Account
from app.core import fisc_xml as fx
from app.posting.models import AccountTurnover
from app.regulated.sources import _class_filter, _lines
from app.workspaces.models import Organization

T1_ROWS = [f"{n:03d}" for n in range(10, 210, 10)]  # r010..r200
T2_ROWS = [f"{n:03d}" for n in range(10, 410, 10)]  # r010..r400 (+ r141)
T3_ROWS = [f"{n:03d}" for n in range(10, 120, 10)]  # r010..r110


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _balances(db: Session, organization_id, before: date | None, until: date | None) -> dict[str, Decimal]:
    """Soldul (debit − credit) pe cod de cont, din rulajele lunare: înainte de `before` sau până la `until`."""
    query = (
        select(Account.code, AccountTurnover.debit, AccountTurnover.credit)
        .join(Account, Account.id == AccountTurnover.account_id)
        .where(AccountTurnover.organization_id == organization_id)
    )
    if before is not None:
        query = query.where(AccountTurnover.period < before)
    if until is not None:
        query = query.where(AccountTurnover.period <= until)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for code, debit, credit in db.execute(query).all():
        totals[code] += debit - credit
    return totals


def _sum(bal: dict[str, Decimal], *prefixes: str, exclude: tuple[str, ...] = ()) -> Decimal:
    return sum(
        (v for k, v in bal.items() if k.startswith(prefixes) and not k.startswith(exclude)), Decimal(0)
    )


def _fixed_assets(bal: dict[str, Decimal]) -> dict[str, tuple[Decimal, Decimal]]:
    """Rând table1 → (cost, amortizare) la data soldului."""
    return {
        "030": (_sum(bal, "12", exclude=("124",)), -_sum(bal, "124")),
        "110": (_sum(bal, "11", exclude=("112",)), -_sum(bal, "112")),
    }


def _balance_sheet(bal: dict[str, Decimal], opening_equity: Decimal | None, result: int | None) -> dict[str, int]:
    """Rândurile bilanțului la o dată (`bal` = solduri); `result` doar la sfârșitul anului."""
    r: dict[str, int] = {}
    r["010"] = _round(_sum(bal, "11"))
    r["020"] = _round(_sum(bal, "12"))
    r["030"] = _round(_sum(bal, "1", exclude=("11", "12")))
    r["100"] = r["010"] + r["020"] + r["030"]
    r["110"] = _round(_sum(bal, "21"))
    r["130"] = _round(_sum(bal, "22"))
    r["140"] = _round(_sum(bal, "23"))
    r["141"] = _round(_sum(bal, "234.4"))
    r["150"] = _round(_sum(bal, "24"))
    r["160"] = _round(_sum(bal, "2", exclude=("21", "22", "23", "24")))
    r["180"] = r["110"] + r["130"] + r["140"] + r["150"] + r["160"]
    r["190"] = r["100"] + r["180"]
    r["220"] = -_round(_sum(bal, "3", exclude=("33", "34")))
    retained = -_round(opening_equity) if opening_equity is not None else 0
    r["200"] = retained
    r["210"] = result or 0
    r["260"] = r["200"] + r["210"] + r["220"]
    r["310"] = -_round(_sum(bal, "3411"))
    r["320"] = -_round(_sum(bal, "3412"))
    r["330"] = -_round(_sum(bal, "34", exclude=("3411", "3412")))
    r["340"] = -_round(_sum(bal, "521"))
    r["350"] = -_round(_sum(bal, "531", "533", "534"))
    r["360"] = -_round(_sum(bal, "535"))
    r["370"] = -_round(_sum(bal, "537"))
    r["380"] = -_round(_sum(bal, "4", "5", exclude=("521", "531", "533", "534", "535", "537")))
    r["390"] = sum(r[k] for k in ("310", "320", "330", "340", "350", "360", "370", "380"))
    r["400"] = r["260"] + r["390"]
    return r


def _result(db: Session, organization_id, year: int) -> dict[str, int]:
    """Rezultatul financiar al anului: rândurile table3 pentru `year`."""
    statutory_special = statutory_other = economic_income = economic_expense = Decimal(0)
    for line in _lines(db, organization_id, date(year, 1, 1), date(year, 12, 31), _class_filter(("6", "7"), ("6", "7"))):
        if (inc := line.income()) is not None:
            account, amount = inc
            if line.activity(account) == "economic":
                economic_income += amount
            elif account.startswith("616"):
                statutory_special += amount
            else:
                statutory_other += amount
        if (exp := line.expense()) is not None:
            account, amount = exp
            if line.activity(account) == "economic":
                economic_expense += amount
    total_expense = Decimal(0)
    for line in _lines(db, organization_id, date(year, 1, 1), date(year, 12, 31), _class_filter(("7",), ("7",))):
        if (exp := line.expense()) is not None:
            total_expense += exp[1]
    r = {
        "020": _round(statutory_special), "030": _round(statutory_other),
        "040": _round(economic_income), "050": _round(economic_expense),
    }  # fmt: skip
    r["010"] = r["020"] + r["030"]
    r["060"] = r["040"] - r["050"]
    r["110"] = r["010"] + r["040"] - _round(total_expense)
    return r


def compute(db: Session, org: Organization, year: int) -> dict:
    start, end = date(year, 1, 1), date(year, 12, 31)
    opening = _balances(db, org.id, start, None)
    closing = _balances(db, org.id, None, end)
    result = _result(db, org.id, year)
    previous = _result(db, org.id, year - 1)
    table1: dict[str, tuple[int, int, int, int]] = {}
    for code in T1_ROWS:
        table1[code] = (0, 0, 0, 0)
    open_fa, close_fa = _fixed_assets(opening), _fixed_assets(closing)
    for code in close_fa:
        cost0 = _round(open_fa[code][0])
        cost1, amort = _round(close_fa[code][0]), _round(close_fa[code][1])
        table1[code] = (cost0, cost1, amort, cost1 - amort)
    groups = {"060": ("010", "020", "030", "040", "050"), "130": ("070", "080", "090", "100", "110", "120"),
              "180": ("140", "150", "160", "170")}  # fmt: skip
    for total, members in groups.items():
        table1[total] = tuple(sum(table1[m][i] for m in members) for i in range(4))  # type: ignore[assignment]
    table1["200"] = tuple(sum(table1[k][i] for k in ("060", "130", "180", "190")) for i in range(4))  # type: ignore[assignment]

    equity_start = _sum(opening, "33")
    return {
        "table1": table1,
        "opening": _balance_sheet(opening, equity_start, None),
        "closing": _balance_sheet(closing, _sum(opening, "33"), result["110"]),
        "result": result,
        "previous": previous,
    }


def _int(value: int) -> str:
    return str(value)


def build_xml(org: Organization, year: int, data: dict) -> bytes:
    """XML-ul declarației: aceleași elemente, în aceeași ordine ca în exemplul oficial."""
    root = ET.Element("dec", {"TypeName": "rsf2"})
    fisc = fx.sub(root, "fiscCod")
    fx.sub(fisc, "name", org.name)
    fx.sub(fisc, "postal", 0)
    fx.sub(fisc, "fisc", org.sfs_office, title="")
    fx.sub(fisc, "cuatm", org.cuatm, title="")
    fx.sub(fisc, "idno", org.idno)
    fx.sub(fisc, "cfp", org.cfp, title="")
    fx.sub(fisc, "cfoj", org.cfoj, title="")
    fx.sub(fisc, "caem", org.caem, title="")
    fx.sub(fisc, "fiscal", org.idno)
    fx.sub(fisc, "telefon", 0)
    fx.sub(fisc, "cuiio", org.cuiio)
    fx.sub(fisc, "web")
    fx.sub(fisc, "email")
    fx.sub(fx.sub(root, "group2"), "adres")
    fx.sub(fx.sub(root, "director"), "director", org.director_name)
    fx.sub(fx.sub(root, "peroidnalog"), "datefisc", fx.year_period(year))
    period = fx.sub(root, "period")
    fx.sub(period, "from", f"01.01.{year}")
    fx.sub(period, "to", f"31.12.{year}")
    fx.sub(fx.sub(root, "pers"), "respons")
    fx.sub(root, "lichidare", 0)
    fx.sub(fx.sub(fx.sub(root, "table"), "row"), "anexeint", org.chief_accountant_name)
    accountant = fx.sub(root, "contabil")
    fx.sub(accountant, "name", org.chief_accountant_name)
    fx.sub(accountant, "telefon", 0)

    row = fx.sub(fx.sub(root, "table1"), "row")
    fx.sub(row, "dela", f"01.01.{year}")
    fx.sub(row, "pinala", f"31.12.{year}")
    for code in T1_ROWS:
        for col, value in zip((4, 5, 6, 7), data["table1"][code], strict=True):
            fx.sub(row, f"r{code}c{col}", _int(value))

    row = fx.sub(fx.sub(root, "table2"), "row")
    for code in T2_ROWS:
        for col, side in ((4, "opening"), (5, "closing")):
            if code in ("200", "210") and col == 4:
                continue
            fx.sub(row, f"r{code}c{col}", _int(data[side].get(code, 0)))
        if code == "140":
            for col, side in ((4, "opening"), (5, "closing")):
                fx.sub(row, f"r141c{col}", _int(data[side]["141"]))
    fx.sub(row, "bilant", f"31.12.{year}")

    row = fx.sub(fx.sub(root, "table3"), "row")
    for code in T3_ROWS:
        for col, side in ((3, "previous"), (4, "result")):
            fx.sub(row, f"r{code}c{col}", _int(data[side].get(code, 0)))
    fx.sub(row, "dela", f"01.01.{year}")
    fx.sub(row, "pinala", f"31.12.{year}")

    attachments = fx.sub(root, "dinamicAttachments")
    first = fx.sub(attachments, "row", line="1")
    fx.sub(first, "index", 1)
    fx.sub(first, "file", hash="", url="")
    second = fx.sub(attachments, "row", line="2")
    fx.sub(second, "index", 2)
    fx.sub(second, "file")
    return fx.serialize(root)


def file_name(year: int) -> str:
    return f"rsf2_{year}"
