"""RSF2 — situațiile financiare anuale ale asociației obștești (XML, formatul docs/exemple-fisc/rsf2.xml).

Valorile se iau din contabilitate: bilanțul din soldurile conturilor (`account_turnovers`) la 1 ianuarie și
31 decembrie, rezultatul financiar din înregistrările veniturilor (6) și cheltuielilor (7) ale anului, fără
înregistrările de închidere (33x). Sumele sunt în lei întregi (rotunjire comercială).

Elementele XML au numele formularului: `table1` = Anexa 3 (modificările surselor de finanțare; coloanele
c4 sold la început, c5 majorări, c6 diminuări, c7 sold la sfârșit), `table2` = Anexa 1 (bilanț; c4 = 01.01,
c5 = 31.12), `table3` = Anexa 2 (venituri și cheltuieli; c3 = anul precedent, c4 = anul raportat).
Numărul rândurilor și valorile au fost confirmate cu o declarație reală depusă pentru 2025; corespondența
cont → rând de mai jos este o ipoteză de lucru acolo unde declarația nu are sume (vezi DEZVOLTARE.md).

  table1 (Anexa 3; soldul = creditul conturilor, majorări = rulaj creditor, diminuări = rulaj debitor)
    r030 Granturi ← 537 și 425 cu proiect; r060 = r010..r050;
    r110 Taxe de aderare și cotizații ← 425 fără proiect; r130 = r070..r120;
    r150 Fond de active imobilizate ← 341.2; r160 Fond de autofinanțare ← 341.1/341.3/341.4, 33x și rezultatul
    anului (excedentul anului majorează fondul înainte de închidere); r180 = r140..r170;
    r200 = r060 + r130 + r180. Celelalte rânduri rămân 0.
  table2 (Anexa 1, bilanț)
    r010 ← 11x net, r020 ← 12x net, r030 ← alte conturi din clasa 1, r100 = r010..r090;
    r110 ← 22x fără 225/226 (creanțe comerciale, avansuri acordate), r130 ← 226 (personal),
    r140 ← 225 și 23x (r141 = 234.4, creanțe privind mijloacele cu destinație specială), r150 ← 24x (numerar),
    r160 ← 21x și alte active circulante (25x..29x), r180 = r110..r170, r190 = r100 + r180;
    r200 ← 33x de la 1 ianuarie (rezultat reportat), r210 = rezultatul anului (= table3 r110),
    r220 ← restul clasei 3 (34x etc.), r260 = r200 + r210 + r220;
    r270 ← 425, r290 ← alte conturi 4xx, r300 = r270..r290;
    r310 ← 537 (mijloace cu destinație specială nefolosite), r320 ← 535, r330 ← 521..523, r340 ← 531,
    r350 ← 532/533, r360 ← 534, r370 ← 51x, r380 ← restul clasei 5, r390 = r310..r380,
    r400 = r260 + r300 + r390.
  table3 (Anexa 2; c3 = anul precedent, c4 = anul raportat)
    r010 ← venituri 616, r020 ← cheltuieli 716, r030 = r010 − r020, r040 ← alte venituri (restul clasei 6),
    r050 ← alte cheltuieli (restul clasei 7), r060 = r030 + r040 − r050, r070..r100 = 0 (impozit etc.),
    r110 = r060 − r070 − … − r100.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.catalogs.models import Account
from app.core import fisc_xml as fx
from app.posting.models import AccountTurnover, EntryLine
from app.regulated.sources import _class_filter, _lines
from app.workspaces.models import Organization

T1_ROWS = [f"{n:03d}" for n in range(10, 210, 10)]  # r010..r200 (Anexa 3)
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


def _balance_sheet(bal: dict[str, Decimal], opening_equity: Decimal | None, result: int | None) -> dict[str, int]:
    """Rândurile bilanțului la o dată (`bal` = solduri); `result` doar la sfârșitul anului."""
    r: dict[str, int] = {}
    r["010"] = _round(_sum(bal, "11"))
    r["020"] = _round(_sum(bal, "12"))
    r["030"] = _round(_sum(bal, "1", exclude=("11", "12")))
    r["100"] = r["010"] + r["020"] + r["030"]
    r["110"] = _round(_sum(bal, "22", exclude=("225", "226")))
    r["130"] = _round(_sum(bal, "226"))
    r["140"] = _round(_sum(bal, "225", "23"))
    r["141"] = _round(_sum(bal, "234.4"))
    r["150"] = _round(_sum(bal, "24"))
    r["160"] = _round(_sum(bal, "21", "25", "26", "27", "28", "29"))
    r["180"] = r["110"] + r["130"] + r["140"] + r["150"] + r["160"]
    r["190"] = r["100"] + r["180"]
    r["220"] = -_round(_sum(bal, "3", exclude=("33",)))
    r["200"] = -_round(opening_equity) if opening_equity is not None else 0
    r["210"] = result or 0
    r["260"] = r["200"] + r["210"] + r["220"]
    r["270"] = -_round(_sum(bal, "425"))
    r["290"] = -_round(_sum(bal, "4", exclude=("425",)))
    r["300"] = r["270"] + r["290"]
    r["310"] = -_round(_sum(bal, "537"))
    r["320"] = -_round(_sum(bal, "535"))
    r["330"] = -_round(_sum(bal, "521", "522", "523"))
    r["340"] = -_round(_sum(bal, "531"))
    r["350"] = -_round(_sum(bal, "532", "533"))
    r["360"] = -_round(_sum(bal, "534"))
    r["370"] = -_round(_sum(bal, "51"))
    r["380"] = -_round(_sum(bal, "5", exclude=("51", "521", "522", "523", "531", "532", "533", "534", "535", "537")))
    r["390"] = sum(r[k] for k in ("310", "320", "330", "340", "350", "360", "370", "380"))
    r["400"] = r["260"] + r["300"] + r["390"]
    return r


def _result(db: Session, organization_id, year: int) -> dict[str, int]:
    """Rezultatul financiar al anului: rândurile table3 pentru `year`."""
    special_income = other_income = special_expense = other_expense = Decimal(0)
    for line in _lines(db, organization_id, date(year, 1, 1), date(year, 12, 31), _class_filter(("6", "7"), ("6", "7"))):
        if (inc := line.income()) is not None:
            account, amount = inc
            if account.startswith("616"):
                special_income += amount
            else:
                other_income += amount
        if (exp := line.expense()) is not None:
            account, amount = exp
            if account.startswith("716"):
                special_expense += amount
            else:
                other_expense += amount
    r = {"010": _round(special_income), "020": _round(special_expense),
         "040": _round(other_income), "050": _round(other_expense)}  # fmt: skip
    r["030"] = r["010"] - r["020"]
    r["060"] = r["030"] + r["040"] - r["050"]
    for code in ("070", "080", "090", "100"):
        r[code] = 0
    r["110"] = r["060"]
    return r


def _fund_row(code: str, has_grant: bool) -> str | None:
    """Rândul Anexei 3 al unui cont de finanțare/fond (None = nu face parte din Anexa 3)."""
    if code.startswith("537") or (code.startswith("425") and has_grant):
        return "030"
    if code.startswith("425"):
        return "110"
    if code.startswith("341.2"):
        return "150"
    return None


def _equity_group(code: str) -> bool:
    """Conturile fondului de autofinanțare: alte fonduri (341.x), rezultatul reportat (33x) și veniturile/cheltuielile."""
    return code.startswith(("341", "33", "6", "7")) and not code.startswith("341.2")


def _sources_of_financing(db: Session, organization_id, year: int) -> dict[str, tuple[int, int, int, int]]:
    """Anexa 3: rând → (sold început, majorări, diminuări, sold sfârșit), din înregistrările contabile."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    debit, credit = aliased(Account), aliased(Account)
    query = (
        select(EntryLine.entry_date, EntryLine.amount, EntryLine.grant_id, debit.code, credit.code)
        .join(debit, debit.id == EntryLine.debit_account_id)
        .join(credit, credit.id == EntryLine.credit_account_id)
        .where(EntryLine.organization_id == organization_id, EntryLine.entry_date <= end)
    )
    opening: dict[str, Decimal] = defaultdict(Decimal)
    increase: dict[str, Decimal] = defaultdict(Decimal)
    decrease: dict[str, Decimal] = defaultdict(Decimal)
    equity_open = equity_end = Decimal(0)
    for entry_date, amount, grant_id, debit_code, credit_code in db.execute(query).all():
        for code, sign in ((credit_code, 1), (debit_code, -1)):
            if (row := _fund_row(code, grant_id is not None)) is not None:
                if entry_date < start:
                    opening[row] += sign * amount
                elif sign > 0:
                    increase[row] += amount
                else:
                    decrease[row] += amount
            if _equity_group(code):
                equity_end += sign * amount
                if entry_date < start:
                    equity_open += sign * amount
    rows: dict[str, tuple[int, int, int, int]] = {}
    for row in ("030", "110", "150"):
        o, i, d = _round(opening[row]), _round(increase[row]), _round(decrease[row])
        rows[row] = (o, i, d, o + i - d)
    # fondul de autofinanțare: soldul crește cu excedentul anului chiar înainte de închiderea lui în 33x
    o, e = _round(equity_open), _round(equity_end)
    change = e - o
    rows["160"] = (o, max(change, 0), max(-change, 0), e)
    return rows


def compute(db: Session, org: Organization, year: int) -> dict:
    start, end = date(year, 1, 1), date(year, 12, 31)
    opening = _balances(db, org.id, start, None)
    closing = _balances(db, org.id, None, end)
    result = _result(db, org.id, year)
    previous = _result(db, org.id, year - 1)
    table1: dict[str, tuple[int, int, int, int]] = {code: (0, 0, 0, 0) for code in T1_ROWS}
    table1.update(_sources_of_financing(db, org.id, year))
    groups = {"060": ("010", "020", "030", "040", "050"), "130": ("070", "080", "090", "100", "110", "120"),
              "180": ("140", "150", "160", "170")}  # fmt: skip
    for total, members in groups.items():
        table1[total] = tuple(sum(table1[m][i] for m in members) for i in range(4))  # type: ignore[assignment]
    table1["200"] = tuple(sum(table1[k][i] for k in ("060", "130", "180")) for i in range(4))  # type: ignore[assignment]

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
