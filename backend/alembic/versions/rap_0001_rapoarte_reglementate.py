"""Rapoartele reglementate: formulare cu versiuni, rapoarte întocmite, calendarul, statistica.

Formularele ONG17 (docs/06) și 5-CON (docs/07) se descriu ca date în
`report_forms.structure`: rândurile, formula fiecărui total, sursa fiecărei
celule calculate și verificările. Când SFS / BNS schimbă formularul se adaugă o
versiune nouă (ToR F6a.5). IPC21 primește doar rândul din catalog (termenul din
calendar); structura celulelor vine cu modulul salarii.

Sintaxa formulelor: `[cod]` = valoarea finală a rândului (după corecțiile
manuale), `{sursă}` = valoarea calculată din contabilitate, `max(a, b)`.

Revision ID: rap_0001
Revises: 0005
Create Date: 2026-11-21
"""

import json
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "rap_0001"
down_revision = "0005"
branch_labels = None
depends_on = None

REPORT_STATUS = postgresql.ENUM("draft", "checked", "submitted", name="report_status", create_type=False)
NGO_TYPES = ["ngo_association", "ngo_foundation", "ngo_other"]


def _row(code, label, *, formula=None, source=None, indent=0, informative=False, unit=None):
    row = {"code": code, "label": label, "indent": indent}
    if formula:
        row["formula"] = formula
    if source:
        row["source"] = source
    if informative:
        row["informative"] = True
    if unit:
        row["unit"] = unit
    return row


ONG17 = {
    "title": "Declarația cu privire la impozitul pe venit pentru organizațiile necomerciale (ONG17)",
    "legal_basis": "Ordinul MF nr. 08/2018, modificat prin Ordinul MF nr. 64 din 25.06.2025",
    "unit": "lei",
    "decimals": 2,
    "applies_to": NGO_TYPES,
    "header": ["period", "ngo_category", "name", "idno", "caem", "sfs_office", "date"],
    "rows": [
        _row("010", "Excedentul (deficitul) perioadei până la impozitare", formula="[0101] - [0102]"),
        _row("0101", "Total venituri", formula="[01011] + [01012] + [01013]", indent=1),
        _row("01011", "Venituri aferente mijloacelor cu destinație specială", source="ong17.income.special_purpose", indent=2),
        _row("01012", "Venituri din activitatea economică prevăzută în statut", source="ong17.income.economic", indent=2),
        _row("01013", "Venituri aferente mijloacelor nepredestinate (inclusiv desemnarea procentuală)",
             source="ong17.income.other", indent=2),
        _row("01014", "Încasări din desemnarea procentuală în perioadă (informativ)",
             source="ong17.income.designation", indent=2, informative=True),
        _row("0102", "Total cheltuieli", formula="[01021] + [01022] + [01023]", indent=1),
        _row("01021", "Cheltuieli aferente mijloacelor cu destinație specială", source="ong17.expense.special_purpose", indent=2),
        _row("010211", "– din care utilizate contrar destinației (inclusiv peste buget)",
             source="ong17.expense.special_purpose.non_statutory", indent=3),
        _row("01022", "Cheltuieli din activitatea economică prevăzută în statut", source="ong17.expense.economic", indent=2),
        _row("01023", "Alte cheltuieli (cu excepția celor din activitatea economică)", source="ong17.expense.other", indent=2),
        _row("010231", "– din care utilizate în scopuri neprevăzute de statut",
             source="ong17.expense.other.non_statutory", indent=3),
        _row("01024", "Cheltuieli din mijloacele desemnării procentuale (informativ)",
             source="ong17.expense.designation", indent=2, informative=True),
        _row("010241", "– din care neutilizate în scopul din pct. 27 HG 1286/2016",
             source="ong17.expense.designation.non_statutory", indent=3),
        _row("020", "Suma spre impozitare", formula="[010211] + [010231] + [010241]"),
        _row("030", "Excedentul scutit de impozitare", formula="max(0, [0101] - [0102] - [020])"),
        _row("040", "Impozitul pe venit nesupus achitării", formula="[030] * [050] / 100"),
        _row("050", "Cota impozitului pe venit, %", source="tax_rate.INCOME_TAX_LEGAL", unit="%"),
        _row("060", "Total impozit pe venit spre plată", formula="[020] * [050] / 100"),
        _row("CTRL", "Suma de control", formula="[060]"),
    ],
    "checks": [
        {"expr": "[010211] <= [01021]", "severity": "error", "message": "010211 nu poate depăși 01021"},
        {"expr": "[010231] <= [01023]", "severity": "error", "message": "010231 nu poate depăși 01023"},
        {"expr": "[010241] <= [01024]", "severity": "error", "message": "010241 nu poate depăși 01024"},
        {"expr": "[030] >= 0", "severity": "error", "message": "030 nu poate fi negativ"},
        {"expr": "[01014] <= [01013]", "severity": "warning",
         "message": "Încasările din desemnarea procentuală (01014) depășesc veniturile nepredestinate (01013)"},
    ],
}


def _con5_rows():
    r = []

    def add(code, label, formula=None, source=None, indent=0, unit=None):
        r.append(_row(code, label, formula=formula, source=source, indent=indent, unit=unit))

    def leaf(code, label, indent=2):
        add(code, label, source=f"con5:{code}", indent=indent)

    add("010", "Venituri – total", "[011] + [012] + [018] + [024] + [030]")
    add("011", "Contribuțiile fondatorilor și membrilor", source="con5.income.members", indent=1)
    add("012", "Mijloace cu destinație specială", "[014] + [015] + [016] + [017]", indent=1)
    add("013", "– din care: din străinătate", source="con5.income.special_purpose.foreign", indent=2)
    for code, label, form in (("014", "active imobilizate", "fixed_assets"), ("015", "stocuri", "stocks"),
                              ("016", "servicii", "services"), ("017", "numerar (mijloace financiare)", "cash")):
        add(code, f"inclusiv: {label}", source=f"con5.income.special_purpose.{form}", indent=2)
    add("018", "Mijloace nepredestinate", "[020] + [021] + [022] + [023]", indent=1)
    add("019", "– din care: din străinătate", source="con5.income.other.foreign", indent=2)
    for code, label, form in (("020", "active imobilizate", "fixed_assets"), ("021", "stocuri", "stocks"),
                              ("022", "servicii", "services"), ("023", "numerar (mijloace financiare)", "cash")):
        add(code, f"inclusiv: {label}", source=f"con5.income.other.{form}", indent=2)
    add("024", "Venituri din activitatea economică", "[025] + [026] + [027] + [028] + [029]", indent=1)
    for code, label, kind in (("025", "produse finite", "products"), ("026", "mărfuri", "goods"),
                              ("027", "servicii", "services"), ("028", "arendă curentă", "rent"),
                              ("029", "alte venituri din activitatea economică", "other")):
        add(code, label, source=f"con5.income.economic.{kind}", indent=2)
    add("030", "Alte venituri (alte intrări)", source="con5.income.misc", indent=1)

    add("040", "Consumuri și cheltuieli – total", "[050] + [070] + [090] + [100] + [110] + [120]")
    add("050", "Materiale – total",
        "[051] + [052] + [053] + [054] + [055] + [060] + [061] + [062] + [063] + [069]", indent=1)
    leaf("051", "materii prime și materiale")
    leaf("052", "piese de schimb")
    leaf("053", "materiale de construcție pentru reparație")
    leaf("054", "ambalaje")
    add("055", "combustibil – total", "{con5:055} + [056] + [057] + [058] + [059]", indent=2)
    leaf("056", "produse petroliere", 3)
    leaf("057", "cărbune", 3)
    leaf("058", "gaze", 3)
    leaf("059", "alte tipuri de combustibil", 3)
    leaf("060", "energie electrică")
    leaf("061", "energie termică")
    leaf("062", "apă")
    leaf("063", "obiecte de mică valoare și scurtă durată")
    leaf("069", "alte materiale")
    add("070", "Servicii prestate de terți – total",
        "[071] + [072] + [073] + [075] + [076] + [077] + [078] + [079] + [080] + [081] + [082] + [089]", indent=1)
    leaf("071", "transport")
    leaf("072", "comunicații")
    add("073", "reparația mijloacelor fixe", "{con5:073} + [074]", indent=2)
    leaf("074", "– din care reparație curentă", 3)
    leaf("075", "prelucrare")
    leaf("076", "bancare")
    leaf("077", "audit")
    leaf("078", "notariale și juridice")
    leaf("079", "pompieri și pază")
    leaf("080", "publicitate")
    leaf("081", "instruire")
    leaf("082", "canalizare, evacuarea gunoiului, ascensor")
    leaf("089", "alte servicii")
    add("090", "Uzura (amortizarea) – total", "[091] + [092]", indent=1)
    leaf("091", "mijloace fixe")
    leaf("092", "active nemateriale")
    add("100", "Retribuirea muncii", source="con5:100", indent=1)
    add("110", "Contribuții CNAS și CNAM", "{con5:110} + [111] + [112]", indent=1)
    leaf("111", "contribuții CNAS")
    leaf("112", "prime CNAM")
    add("120", "Alte cheltuieli operaționale – total",
        "[130] + [140] + [150] + [160] + [170] + [180] + [190] + [200] + [210] + [220] + [230]", indent=1)
    add("130", "arendă operațională", "{con5:130} + [131]", indent=2)
    leaf("131", "– din care terenuri", 3)
    add("140", "deplasări", "{con5:140} + [141] + [142]", indent=2)
    leaf("141", "– din care cazare", 3)
    leaf("142", "– din care diurnă", 3)
    leaf("150", "protocol")
    leaf("160", "asigurare obligatorie")
    add("170", "dobânzi", "{con5:170} + [171] + [172]", indent=2)
    leaf("171", "nerezidenților", 3)
    add("172", "rezidenților", "{con5:172} + [173] + [174]", indent=3)
    leaf("173", "instituții financiare", 4)
    leaf("174", "întreprinderi", 4)
    leaf("180", "datorii dubioase")
    leaf("190", "amenzi, penalități")
    leaf("200", "valoarea activelor curente ieșite")
    leaf("210", "donații și sponsorizări")
    add("220", "impozite și taxe în cheltuieli", "{con5:220} + [221] + [222] + [223] + [224] + [225]", indent=2)
    leaf("221", "impozitul funciar", 3)
    leaf("222", "impozitul pe bunurile imobiliare", 3)
    leaf("223", "taxa rutieră", 3)
    leaf("224", "taxe locale", 3)
    leaf("225", "alte impozite și taxe", 3)
    add("230", "alte cheltuieli", "{con5:230} + {con5:unassigned}", indent=2)

    add("300", "Numărul membrilor la ultima zi a trimestrului", source="stats.members", unit="pers.")
    add("310", "Numărul mediu al salariaților", source="stats.employees", unit="pers.")
    add("320", "Numărul de voluntari", source="stats.volunteers", unit="pers.")
    return r


CON5 = {
    "title": "5-CON — Consumurile și cheltuielile organizațiilor necomerciale",
    "legal_basis": "BNS, schema XML 5CON_xsd_2023",
    "unit": "mii lei",
    "decimals": 1,
    "scale": 1000,
    "applies_to": NGO_TYPES,
    "header": ["ENT_NAME", "IDNO", "CUIIO", "CFOJ", "CFP", "CAEM", "CUATM", "YEAR", "TRIM", "HEAD", "EXECUTOR"],
    "xml": {"root": "dec", "header": "Header", "table": "CAP1", "cell": "CAP1_R{code}_C1"},
    "rows": _con5_rows(),
    "checks": [
        {"expr": "[013] <= [012]", "severity": "error", "message": "013 nu poate depăși 012"},
        {"expr": "[019] <= [018]", "severity": "error", "message": "019 nu poate depăși 018"},
        {"expr": "[074] <= [073]", "severity": "error", "message": "074 nu poate depăși 073"},
        {"expr": "[131] <= [130]", "severity": "error", "message": "131 nu poate depăși 130"},
        {"expr": "[141] + [142] <= [140]", "severity": "error", "message": "141 + 142 nu poate depăși 140"},
        {"expr": "{con5:unassigned} == 0", "severity": "warning",
         "message": "Există cheltuieli fără articol 5-CON — au intrat la rândul 230; indicați articolul de cheltuieli"},
    ],
}

IPC21 = {
    "title": "IPC21 — Darea de seamă privind reținerea impozitului pe venit, a contribuțiilor CNAS și a primelor CNAM",
    "unit": "lei",
    "decimals": 2,
    "rows": [],
    "note": "Structura celulelor vine cu modulul salarii (docs/05-specificatie-IPC21.md)",
}

FORMS = [
    ("ONG17", "SFS", "year", "2025", date(2025, 1, 1), ONG17, "next_year:03-25"),
    ("5-CON", "BNS", "quarter", "2023", date(2023, 1, 1), CON5, "next_month:25"),
    ("IPC21", "SFS", "month", "1", date(2024, 1, 1), IPC21, "next_month:25"),
]


def upgrade() -> None:
    bind = op.get_bind()
    REPORT_STATUS.create(bind, checkfirst=True)
    op.create_table(
        "report_forms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("authority", sa.String(), nullable=False),
        sa.Column("periodicity", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("structure", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("due_day_rule", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version"),
    )
    op.create_table(
        "tax_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("form_id", sa.UUID(), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("status", REPORT_STATUS, server_default=sa.text("'draft'"), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("manual_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("export_file_id", sa.String(), nullable=True),
        sa.Column("prepared_by", sa.UUID(), nullable=True),
        sa.Column("submitted_at", postgresql.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["report_forms.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["prepared_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reporting_calendar",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("form_id", sa.UUID(), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("tax_report_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["report_forms.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["tax_report_id"], ["tax_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "form_id", "period_from"),
    )
    op.create_table(
        "organization_stats",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("members_count", sa.Integer(), nullable=True),
        sa.Column("volunteers_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "period_end"),
    )

    for code, authority, periodicity, version, valid_from, structure, due in FORMS:
        bind.execute(
            sa.text(
                "INSERT INTO report_forms (id, code, authority, periodicity, version, valid_from, structure, due_day_rule) "
                "VALUES (:id, :code, :authority, :periodicity, :version, :valid_from, CAST(:structure AS jsonb), :due) "
                "ON CONFLICT (code, version) DO NOTHING"
            ),
            dict(id=uuid.uuid4(), code=code, authority=authority, periodicity=periodicity, version=version,
                 valid_from=valid_from, structure=json.dumps(structure, ensure_ascii=False), due=due),
        )  # fmt: skip

    # cota impozitului pe venit al persoanelor juridice — rândul 050 din ONG17
    bind.execute(
        sa.text(
            "INSERT INTO tax_rates (id, code, value, is_percent, valid_from, legal_basis) "
            "VALUES (:id, 'INCOME_TAX_LEGAL', 12, true, :valid_from, 'Codul fiscal art. 15 lit. b)') "
            "ON CONFLICT ON CONSTRAINT uq_tax_rates_code_applies_valid DO NOTHING"
        ),
        dict(id=uuid.uuid4(), valid_from=date(2012, 1, 1)),
    )


def downgrade() -> None:
    op.execute("DELETE FROM tax_rates WHERE code = 'INCOME_TAX_LEGAL' AND valid_from = '2012-01-01'")
    op.drop_table("organization_stats")
    op.drop_table("reporting_calendar")
    op.drop_table("tax_reports")
    op.drop_table("report_forms")
    REPORT_STATUS.drop(op.get_bind(), checkfirst=True)
