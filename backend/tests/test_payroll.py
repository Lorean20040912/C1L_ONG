"""Calculul salariului (ToR M3): CIM vs contract civil, scutirile doar la CIM de bază,
repartizarea pe granturi, pasul „Calculul salariului” din închiderea lunii,
plata cumulată și IPC21 = suma calculelor.

Cotele sunt cele din migrarea sal_0002 (12% impozit, 9% CNAM, 24% CNAS,
scutirea personală 29 700 lei/an = 2 475 lei/lună, 9 900 lei/an pe persoană întreținută).
"""

import uuid
from xml.etree import ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.bank.models import BankAccount
from app.catalogs.models import Account, Department
from app.core import crypto
from app.core.enums import ContractType, DocumentType
from app.documents.models import Document
from app.documents.posting import post_payment
from app.grants.models import BudgetLine, Grant
from app.individual_payments.posting import post as post_individual
from app.month_close.service import get_run, revert_step, run_step
from app.payroll import calc, ipc21
from app.payroll.models import Contract, ContractFunding, ExemptionClaim, IndividualPayment, PayrollEntry, Person
from app.payroll.service import (
    GroupedPaymentInput,
    build_purpose,
    create_grouped_payment,
    delete_grouped_payment,
    period_entries,
)
from app.posting.engine import PostingError, turnover_differences
from app.posting.models import AccountingPolicy, EntryLine
from app.taxes.models import TaxRate
from tests.conftest import make_accounts, make_org, make_user
from tests.xml_structure import assert_format, assert_same_structure

Y, M = 2026, 11
ACCOUNTS = ("234.4", "242", "531", "533", "534", "537", "544", "616", "716", "717", "718")


@pytest.fixture
def ong(db):
    user = make_user(db, "contabil@exemplu.md")
    org = make_org(db, user, "AO Alfa")
    acc = make_accounts(db, org, *ACCOUNTS)
    db.add(
        AccountingPolicy(
            organization_id=org.id, valid_from=date(2026, 1, 1), grant_receivable_account_id=acc["234.4"].id
        )
    )
    sor = Grant(
        organization_id=org.id, code="SOR-2026-01", title="Proiect", funding_type="grant", currency="MDL",
        total_amount=Decimal(500000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )  # fmt: skip
    own = Grant(
        organization_id=org.id, code="COT", title="Cotizații", funding_type="cotizații", currency="MDL",
        total_amount=Decimal(50000), start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )  # fmt: skip
    db.add_all([sor, own])
    db.flush()
    lines = {
        "sal": BudgetLine(grant_id=sor.id, code="1.1", name="Salarii", planned_amount=Decimal(200000)),
        "chirie": BudgetLine(grant_id=sor.id, code="3.1", name="Chirie", planned_amount=Decimal(20000)),
        "own": BudgetLine(grant_id=own.id, code="1", name="Administrare", planned_amount=Decimal(50000)),
    }
    bank = BankAccount(organization_id=org.id, iban_enc="MD00AG0000000225", currency="MDL", account_id=acc["242"].id)
    db.add_all([*lines.values(), bank])
    db.flush()
    return user, org, acc, {"sor": sor, "own": own}, lines, bank


def person(db, org, name="Popescu Ion", idnp="2001234567890", cpas="123456789"):
    p = Person(organization_id=org.id, full_name=name, idnp_enc=crypto.encrypt(idnp), cpas=cpas)
    db.add(p)
    db.flush()
    return p


def contract(db, p, kind=ContractType.cim, gross="10000", main=True, funding=None, start=date(2026, 1, 1), end=None):
    c = Contract(
        person_id=p.id, type=kind, is_main_job=main, number=f"{kind.value}-{p.full_name[:3]}",
        start_date=start, end_date=end, gross_amount=Decimal(gross),
    )  # fmt: skip
    c.funding = [
        ContractFunding(grant_id=g.id, budget_line_id=bl.id if bl else None, share_percent=Decimal(s), valid_from=start)
        for g, bl, s in funding
    ]
    db.add(c)
    db.flush()
    return c


def exempt(db, c, kind="personal", count=0):
    db.add(ExemptionClaim(person_id=c.person_id, contract_id=c.id, kind=kind, dependents_count=count,
                          valid_from=date(2026, 1, 1)))  # fmt: skip
    db.flush()
    db.refresh(c)


def calc_of(db, c):
    db.expire_all()
    return calc.calculate_contract(db, db.get(Contract, c.id), Y, M)


def codes(db, doc_id):
    code = dict(db.execute(select(Account.id, Account.code)).all())
    rows = db.scalars(select(EntryLine).where(EntryLine.document_id == doc_id).order_by(EntryLine.line_no))
    return [(code[e.debit_account_id], code[e.credit_account_id], e.amount, e.grant_id) for e in rows]


# ───────────────────────── calculul pe contract ─────────────────────────


def test_cim_de_baza_cu_scutire_personala(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), funding=[(g["sor"], bl["sal"], 100)])
    exempt(db, c)
    r = calc_of(db, c)
    assert r.income_code == "SAL"
    assert (r.gross, r.cnas, r.cnam) == (Decimal("10000.00"), Decimal("2400.00"), Decimal("900.00"))
    assert r.personal_exemption == Decimal("2475.00")
    assert r.taxable == Decimal("6625.00")  # 10 000 − 900 − 2 475
    assert r.income_tax == Decimal("795.00")
    assert r.net == Decimal("8305.00")
    assert set(r.details["rates"]) >= {"CNAS_EMPLOYER", "CNAM_EMPLOYEE", "INCOME_TAX", "PERSONAL_EXEMPTION_YEAR"}


def test_contract_civil_fara_scutire(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), ContractType.civil, gross="5000", main=False, funding=[(g["sor"], bl["sal"], 100)])
    exempt(db, c)  # chiar dacă există o cerere în BD, la contractul civil nu se aplică
    r = calc_of(db, c)
    assert r.income_code == "PL"
    assert r.personal_exemption == r.dependents_exemption == 0
    assert (r.cnam, r.taxable, r.income_tax, r.net) == (
        Decimal("450.00"), Decimal("4550.00"), Decimal("546.00"), Decimal("4004.00"),
    )  # fmt: skip


def test_scutirea_doar_la_locul_de_baza(db, ong):
    _, org, _, g, bl, _ = ong
    p = person(db, org)
    secondary = contract(db, p, gross="4000", main=False, funding=[(g["sor"], bl["sal"], 100)])
    exempt(db, secondary)
    r = calc_of(db, secondary)
    assert r.personal_exemption == 0 and r.taxable == Decimal("3640.00")


def test_scutirea_pentru_persoane_intretinute(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), funding=[(g["sor"], bl["sal"], 100)])
    exempt(db, c)
    exempt(db, c, "dependents", 2)
    r = calc_of(db, c)
    assert r.dependents_exemption == Decimal("1650.00")  # 2 × 9 900 / 12
    assert r.taxable == Decimal("4975.00")


def test_baza_impozabila_nu_e_negativa(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), gross="2000", funding=[(g["sor"], bl["sal"], 100)])
    exempt(db, c)
    r = calc_of(db, c)
    assert r.taxable == 0 and r.income_tax == 0 and r.net == Decimal("1820.00")


def test_cim_proportional_cu_zilele_lucratoare(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), start=date(2026, 11, 16), funding=[(g["sor"], bl["sal"], 100)])
    r = calc_of(db, c)
    # noiembrie 2026: 21 de zile lucrătoare, din 16.11 — 11
    assert r.details["working_days"] == {"month": 21, "worked": 11}
    assert r.gross == Decimal("5238.10") and r.period_start == date(2026, 11, 16)


def test_contract_inactiv_nu_se_calculeaza(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), start=date(2026, 1, 1), end=date(2026, 10, 31), funding=[(g["sor"], bl["sal"], 100)])
    assert calc_of(db, c) is None


def test_cota_valabila_la_data(db, ong):
    _, org, _, g, bl, _ = ong
    db.add(TaxRate(code="CNAM_EMPLOYEE", value=Decimal(10), valid_from=date(2026, 11, 1), legal_basis="test"))
    old = db.scalar(select(TaxRate).where(TaxRate.code == "CNAM_EMPLOYEE", TaxRate.valid_from == date(2019, 1, 1)))
    old.valid_to = date(2026, 10, 31)
    db.flush()
    c = contract(db, person(db, org), funding=[(g["sor"], bl["sal"], 100)])
    assert calc_of(db, c).cnam == Decimal("1000.00")
    assert calc.calculate_contract(db, db.get(Contract, c.id), 2026, 10).cnam == Decimal("900.00")


def test_repartizarea_pe_granturi_cu_rotunjire(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), gross="10000.01", funding=[(g["sor"], bl["sal"], 60), (g["own"], bl["own"], 40)])
    r = calc_of(db, c)
    sor, own = r.parts
    for key in calc.AMOUNTS:
        assert sor.amounts[key] + own.amounts[key] == {
            "gross": r.gross, "cnas": r.cnas, "cnam": r.cnam, "income_tax": r.income_tax, "net": r.net,
        }[key]  # fmt: skip
    assert sor.amounts["gross"] == Decimal("6000.01") and own.amounts["gross"] == Decimal("4000.00")
    assert calc.split(Decimal("100.00"), [Decimal(1), Decimal(1), Decimal(1)]) == [
        Decimal("33.33"), Decimal("33.33"), Decimal("33.34"),
    ]  # fmt: skip


def test_finantarea_sub_100_la_suta_opreste_calculul(db, ong):
    user, org, _, g, bl, _ = ong
    contract(db, person(db, org), funding=[(g["sor"], bl["sal"], 60)])
    plan = calc.plan(db, org.id, Y, M)
    assert plan.errors and "60" in plan.errors[0]
    with pytest.raises(PostingError, match="100%"):
        run_step(db, org.id, Y, M, "payroll", user.id)


# ───────────────────────── pasul din închiderea lunii ─────────────────────────


def setup_staff(db, ong):
    _, org, _, g, bl, _ = ong
    ion = person(db, org, "Popescu Ion", "2001234567890")
    cim = contract(db, ion, funding=[(g["sor"], bl["sal"], 60), (g["own"], bl["own"], 40)])
    exempt(db, cim)
    maria = person(db, org, "Rusu Maria", "2009876543210")
    civil = contract(db, maria, ContractType.civil, gross="5000", main=False, funding=[(g["sor"], bl["sal"], 100)])
    return ion, cim, maria, civil


def test_pasul_inregistreaza_pe_granturi_si_ingheata_rezultatele(db, ong):
    user, org, _, g, _, _ = ong
    _, cim, _, civil = setup_staff(db, ong)
    run_step(db, org.id, Y, M, "payroll", user.id)
    run = get_run(db, org.id, Y, M)
    step = next(s for s in run.steps if s["step"] == "payroll")
    assert step["status"] == "done" and step["total"] == "15000.00"
    lines = codes(db, step["document_id"])
    total = lambda dt, kt, grant: sum((a for d, k, a, gr in lines if (d, k, gr) == (dt, kt, grant)), Decimal(0))  # noqa: E731
    assert total("716", "531", g["sor"].id) == Decimal("11000.00")  # 6 000 CIM + 5 000 civil
    assert total("717", "531", g["own"].id) == Decimal("4000.00")
    assert total("716", "533", g["sor"].id) == Decimal("2640.00")  # 24% din 11 000
    assert total("537", "616", g["sor"].id) == Decimal("13640.00")  # venitul = cheltuiala proiectului
    assert total("537", "616", g["own"].id) == 0  # mijloacele nepredestinate nu au 537/616
    assert total("531", "534", g["sor"].id) + total("531", "534", g["own"].id) == Decimal("1341.00")  # 795 + 546
    entries = {e.contract_id: e for e in db.scalars(select(PayrollEntry))}
    assert entries[cim.id].income_code == "SAL" and entries[civil.id].income_code == "PL"
    assert entries[cim.id].calc_details["funding"][0]["grant_code"] == "SOR-2026-01"
    assert entries[civil.id].budget_line_id is not None  # o singură finanțare → linia pe rând
    assert turnover_differences(db, org.id) == []

    # repetarea înlocuiește calculul, nu îl dublează
    run_step(db, org.id, Y, M, "payroll", user.id)
    assert db.scalar(select(func.count()).select_from(PayrollEntry)) == 2
    assert len(codes(db, step["document_id"])) == len(lines)

    # contractul se modifică după calcul: luna calculată rămâne înghețată
    db.get(Contract, civil.id).gross_amount = Decimal(9000)
    db.flush()
    frozen = db.scalar(select(PayrollEntry).where(PayrollEntry.contract_id == civil.id))
    assert frozen.gross == Decimal("5000.00")

    revert_step(db, org.id, Y, M, "payroll", user.id)
    assert db.scalar(select(func.count()).select_from(PayrollEntry)) == 0
    assert db.get(Document, uuid.UUID(step["document_id"])).is_posted is False


# ───────────────────────── plata cumulată ─────────────────────────


def test_plata_cumulata_stinge_datoria_pe_persoane_si_granturi(db, ong):
    user, org, acc, g, _, bank = ong
    setup_staff(db, ong)
    run_step(db, org.id, Y, M, "payroll", user.id)
    doc, order = create_grouped_payment(
        db,
        org.id,
        GroupedPaymentInput(year=Y, month=M, tax_kind="income_tax", bank_account_id=bank.id, doc_number="101",
                            doc_date=date(2026, 12, 5)),  # fmt: skip
        user.id,
    )
    assert order.kind == "grouped_tax" and doc.total_amount == Decimal("1341.00")
    assert len(order.lines) == 3  # Popescu pe 2 granturi + Rusu
    assert order.purpose == "IV 11.2026: Popescu I. 795,00; Rusu M. 546,00"
    post_payment(db, org.id, doc.id, user.id)
    lines = codes(db, doc.id)
    assert {(d, k) for d, k, _, _ in lines} == {("534", "242")}
    assert sum(a for _, _, a, _ in lines) == Decimal("1341.00")
    # datoria 534 pe fiecare grant e stinsă
    for grant in g.values():
        debit = db.scalar(
            select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
                EntryLine.debit_account_id == acc["534"].id, EntryLine.grant_id == grant.id
            )
        )
        credit = db.scalar(
            select(func.coalesce(func.sum(EntryLine.amount), 0)).where(
                EntryLine.credit_account_id == acc["534"].id, EntryLine.grant_id == grant.id
            )
        )
        assert debit == credit
    # aceleași sume nu se plătesc de două ori
    with pytest.raises(PostingError, match="deja incluse"):
        create_grouped_payment(
            db, org.id,
            GroupedPaymentInput(year=Y, month=M, tax_kind="income_tax", bank_account_id=bank.id, doc_number="102",
                                doc_date=date(2026, 12, 5)),
            user.id,
        )  # fmt: skip
    # calculul nu se anulează cât timp există plăți pe el
    with pytest.raises(PostingError, match="plăți cumulate"):
        revert_step(db, org.id, Y, M, "payroll", user.id)


def test_plata_cumulata_pe_un_grant_si_stergerea(db, ong):
    user, org, _, g, _, bank = ong
    setup_staff(db, ong)
    run_step(db, org.id, Y, M, "payroll", user.id)
    doc, order = create_grouped_payment(
        db, org.id,
        GroupedPaymentInput(year=Y, month=M, tax_kind="cnas", bank_account_id=bank.id, doc_number="7",
                            doc_date=date(2026, 12, 5), grant_id=g["own"].id),
        user.id,
    )  # fmt: skip
    assert order.purpose == "CAS 11.2026 proiect COT: Popescu I. 960,00"
    assert {ln.grant_id for ln in order.lines} == {g["own"].id}
    post_payment(db, org.id, doc.id, user.id)
    assert {(d, k) for d, k, _, _ in codes(db, doc.id)} == {("533", "242")}
    with pytest.raises(PostingError, match="anulați"):
        delete_grouped_payment(db, org.id, doc.id, user.id)


def test_destinatia_se_scurteaza_sau_cere_impartirea():
    people = [("Popescu Ion", Decimal("1234")), ("Rusu Maria", Decimal("980.5"))]
    assert build_purpose("CAS 10.2026", people, 210) == "CAS 10.2026: Popescu I. 1 234,00; Rusu M. 980,50"
    assert build_purpose("CAS 10.2026", people, 45) == "CAS 10.2026: Popescu 1 234,00; Rusu 980,50"
    with pytest.raises(PostingError, match="împărțiți"):
        build_purpose("CAS 10.2026", people, 20)


# ───────────────────────── plata către persoană fizică ─────────────────────────


def individual(db, org, p, line, kind="rent", gross="1000", day=date(2026, 11, 20)):
    doc = Document(organization_id=org.id, type=DocumentType.individual_payment, doc_number="CH-1", doc_date=day)
    db.add(doc)
    db.flush()
    pay = IndividualPayment(document_id=doc.id, person_id=p.id, payment_kind=kind, income_code="?",
                            accrual_date=day, gross=Decimal(gross), budget_line_id=line.id)  # fmt: skip
    db.add(pay)
    db.flush()
    return doc, pay


def test_chiria_se_retine_la_fol(db, ong):
    user, org, _, g, bl, _ = ong
    doc, pay = individual(db, org, person(db, org, "Ceban Vasile", "2005555555555"), bl["chirie"])
    post_individual(db, org.id, doc.id, user.id)
    assert (pay.income_code, pay.income_tax, pay.net) == ("FOL", Decimal("70.00"), Decimal("930.00"))
    assert [(d, k, a) for d, k, a, _ in codes(db, doc.id)] == [
        ("716", "544", Decimal("1000.00")), ("537", "616", Decimal("1000.00")), ("544", "534", Decimal("70.00")),
    ]  # fmt: skip


# ───────────────────────── IPC21 ─────────────────────────


def test_ipc21_este_suma_calculelor(db, ong):
    user, org, _, _, bl, _ = ong
    dept = Department(organization_id=org.id, name="Oficiul Chișinău", cuatm="0100")
    db.add(dept)
    db.flush()
    _, cim, _, _ = setup_staff(db, ong)
    cim.department_id = dept.id
    db.flush()
    run_step(db, org.id, Y, M, "payroll", user.id)
    doc, _ = individual(db, org, person(db, org, "Ceban Vasile", "2005555555555"), bl["chirie"])
    post_individual(db, org.id, doc.id, user.id)
    # o plată neînregistrată nu intră în declarație
    individual(db, org, person(db, org, "Lungu Ana", "2004444444444"), bl["chirie"], "donation", "500")

    r = ipc21.build(db, org.id, Y, M)
    rows = {x.code: x for x in r.table1}
    entries = period_entries(db, org.id, Y, M)
    sal = [e.entry for e in entries if e.entry.income_code == "SAL"]
    pl = [e.entry for e in entries if e.entry.income_code == "PL"]
    assert (rows["SAL"].c4, rows["SAL"].c5, rows["SAL"].c6) == (
        sum(e.gross for e in sal), sum(e.income_tax for e in sal), sum(e.cnam_employee for e in sal),
    )  # fmt: skip
    assert (rows["PL"].c4, rows["PL"].c5, rows["PL"].c6) == (Decimal("5000.00"), Decimal("546.00"), 0)
    assert (rows["FOL"].c4, rows["FOL"].c5) == (Decimal("1000.00"), Decimal("70.00"))
    assert rows["DON pf"].c4 == 0
    assert r.total.c5 == Decimal("795.00") + Decimal("546.00") + Decimal("70.00")
    assert r.control_sum == r.total.c5 - Decimal("70.00")
    assert r.annex == [{"no": 1, "cuatm": "0100", "c3": Decimal("795.00"), "c4": Decimal("795.00"), "c5": 0}]
    assert [n.full_name for n in r.nominal] == ["Popescu Ion", "Rusu Maria"]
    assert r.tariffs == [{"row": "r11b", "tariff": Decimal("24.00"), "c9": Decimal("15000.00"),
                          "c11": Decimal("3600.00")}]  # fmt: skip
    assert r.errors == []
    xml = ipc21.to_xml(r).decode()
    assert "<r11c5>795.00</r11c5>" in xml and "<r41c4>1000.00</r41c4>" in xml and "2001234567890" in xml
    # structura și formatul exportului oficial (docs/exemple-fisc/ipc21.xml)
    assert_format(xml.encode(), "ipc21.xml")
    assert_same_structure(xml.encode(), "ipc21.xml")
    root = ET.fromstring(xml)
    assert root.find("peroidnalog/datefisc").text == "L/11/2026"
    assert root.find("table1/row/r61c4").text == format(r.total.c4, ".2f")
    assert [c.tag for c in root.find("table1/row")][-3:] == ["r61c6", "r61c5", "r61c4"]
    nominal = root.find("dinamicTable2/row")
    assert nominal.find("c71").text == "24%" and nominal.find("c5").text == "01.11.2026"
    assert root.find("table2/row/r11bc11").text == "3600.00"


def test_ipc21_semnaleaza_cpas_lipsa(db, ong):
    user, org, _, g, bl, _ = ong
    p = person(db, org, cpas=None)
    contract(db, p, funding=[(g["sor"], bl["sal"], 100)])
    run_step(db, org.id, Y, M, "payroll", user.id)
    assert any("CPAS" in e for e in ipc21.build(db, org.id, Y, M).errors)


def test_finantarea_se_schimba_in_mijlocul_lunii(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), gross="3000", funding=[(g["sor"], bl["sal"], 100)])
    c.funding[0].valid_to = date(2026, 11, 10)
    c.funding.append(ContractFunding(grant_id=g["own"].id, budget_line_id=bl["own"].id, share_percent=Decimal(100),
                                     valid_from=date(2026, 11, 11)))  # fmt: skip
    db.flush()
    r = calc_of(db, c)
    assert r.error is None
    sor, own = r.parts
    assert sor.amounts["gross"] == Decimal("1000.00") and own.amounts["gross"] == Decimal("2000.00")  # 10 / 20 zile
    assert sor.amounts["gross"] + own.amounts["gross"] == r.gross


def test_o_zi_fara_finantare_opreste_calculul(db, ong):
    _, org, _, g, bl, _ = ong
    c = contract(db, person(db, org), funding=[(g["sor"], bl["sal"], 100)])
    c.funding[0].valid_to = date(2026, 11, 20)
    db.flush()
    assert "21.11.2026" in calc_of(db, c).error


def test_cotele_confirmate_nu_mai_sunt_marcate_de_verificat(db):
    """fix_0004: valorile rămân, doar temeiul legal pierde marcajul pentru cotele confirmate."""
    rows = {
        (r.code, r.applies_to.value if r.applies_to else None): r
        for r in db.scalars(select(TaxRate).where(TaxRate.valid_to.is_(None)))
    }
    for key, value in {
        ("INCOME_TAX", "cim"): "12",
        ("CNAM_EMPLOYEE", None): "9",
        ("CNAS_EMPLOYER", None): "24",
        ("PERSONAL_EXEMPTION_YEAR", "cim"): "29700",
        ("MAJOR_PERSONAL_EXEMPTION_YEAR", "cim"): "30000",
        ("DEPENDENT_EXEMPTION_YEAR", "cim"): "9900",
        ("DISABLED_DEPENDENT_EXEMPTION_YEAR", "cim"): "30000",
        ("WITHHOLDING_FOL", None): "7",
    }.items():
        assert rows[key].value == Decimal(value)
        assert "de verificat" not in rows[key].legal_basis


def test_ipc21_gol_are_aceeasi_structura(db, ong):
    _, org, *_ = ong
    xml = ipc21.to_xml(ipc21.build(db, org.id, Y, M))
    assert_same_structure(xml, "ipc21.xml")
