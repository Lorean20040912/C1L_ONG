"""Date demonstrative pentru dezvoltare: `python -m app.seed`.

Creează utilizatorul din DEMO_EMAIL / DEMO_PASSWORD (dacă sunt setate în .env)
și o bază cu o organizație fictivă, conturile ONG, politica contabilă, un grant cu linii de buget,
un furnizor și un cont bancar. Rulat de mai multe ori,
nu dublează nimic.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.auth.models import OrganizationMember, User
from app.bank.models import BankAccount
from app.catalogs.models import Account, Counterparty
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import AccountKind, EntityType, UserRole
from app.core.security import hash_password
from app.features.models import OrganizationFeature
from app.features.service import enable_defaults
from app.grants.models import BudgetLine, Grant
from app.posting.models import AccountingPolicy
from app.workspaces.models import Organization, Workspace

# conturile folosite de regulile standard ONG (docs/11)
DEMO_ACCOUNTS = [
    ("123", "Mijloace fixe", AccountKind.active),
    ("124", "Amortizarea mijloacelor fixe", AccountKind.passive),
    ("211", "Materiale", AccountKind.active),
    ("234", "Creanțe curente privind alte operațiuni", AccountKind.active),
    ("234.4", "Creanțe privind mijloacele cu destinație specială", AccountKind.active),
    ("241", "Casa", AccountKind.active),
    ("242", "Conturi curente în monedă națională", AccountKind.active),
    ("243", "Conturi curente în valută străină", AccountKind.active),
    ("341.2", "Fonduri de active imobilizate", AccountKind.passive),
    ("341.3", "Fonduri de autofinanțare", AccountKind.passive),
    ("425", "Finanțări și încasări cu destinație specială pe termen lung", AccountKind.passive),
    ("521", "Datorii comerciale curente", AccountKind.passive),
    ("531", "Datorii față de personal", AccountKind.passive),
    ("533", "Datorii privind asigurările", AccountKind.passive),
    ("534", "Datorii față de buget", AccountKind.passive),
    ("535", "Venituri anticipate curente", AccountKind.passive),
    ("537", "Finanțări și încasări cu destinație specială curente", AccountKind.passive),
    ("544", "Alte datorii curente", AccountKind.passive),
    ("616", "Venituri aferente mijloacelor cu destinație specială", AccountKind.passive),
    ("617", "Venituri ale organizației", AccountKind.passive),
    ("618", "Venituri din activitatea economică", AccountKind.passive),
    ("713", "Cheltuieli administrative", AccountKind.active),
    ("716", "Cheltuieli aferente mijloacelor cu destinație specială", AccountKind.active),
    ("717", "Cheltuieli ale organizației", AccountKind.active),
    ("718", "Cheltuieli din activitatea economică", AccountKind.active),
]


def run() -> None:
    settings = get_settings()
    if not settings.demo_email or not settings.demo_password:
        print("seed: DEMO_EMAIL / DEMO_PASSWORD nu sunt setate — nimic de creat")
        return
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == settings.demo_email.lower())):
            print("seed: utilizatorul demonstrativ există deja")
            return
        user = User(
            email=settings.demo_email.lower(),
            full_name="Contabil demonstrativ",
            password_hash=hash_password(settings.demo_password),
        )
        db.add(user)
        db.flush()
        ws = Workspace(name="AO „Exemplu Verde”", created_by=user.id, source="empty")
        db.add(ws)
        db.flush()
        org = Organization(
            workspace_id=ws.id,
            name="Asociația Obștească „Exemplu Verde”",
            idno="1000000000001",
            entity_type=EntityType.ngo_association,
            legal_form="AO",
            ngo_category="A",
        )
        db.add(org)
        db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=UserRole.admin))
        enable_defaults(db, org, date(2026, 1, 1))
        db.add(OrganizationFeature(organization_id=org.id, feature_code="payroll", enabled_from=date(2026, 1, 1)))
        accounts = {
            code: Account(organization_id=org.id, code=code, name=name, account_kind=kind)
            for code, name, kind in DEMO_ACCOUNTS
        }
        db.add_all(accounts.values())
        db.flush()
        db.add(
            AccountingPolicy(
                organization_id=org.id,
                valid_from=date(2026, 1, 1),
                grant_receivable_account_id=accounts["234.4"].id,
                grant_recognition="on_signing",
            )
        )
        grant = Grant(
            organization_id=org.id,
            code="DEMO-2026-01",
            title="Proiect demonstrativ",
            funding_type="grant",
            currency="MDL",
            total_amount=Decimal(120000),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        own = Grant(
            organization_id=org.id,
            code="COT-2026",
            title="Cotizații membri",
            funding_type="cotizații",
            currency="MDL",
            total_amount=Decimal(10000),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.add_all([grant, own])
        db.flush()
        for g, code, name, planned in [
            (grant, "1.1", "Salarii personal proiect", 60000),
            (grant, "2.1", "Echipament", 30000),
            (grant, "3.2", "Comunicații", 6000),
            (grant, "4.2", "Consumabile", 4000),
            (own, "1", "Cheltuieli administrative", 10000),
        ]:
            db.add(BudgetLine(grant_id=g.id, code=code, name=name, planned_amount=Decimal(planned)))
        db.add(Counterparty(organization_id=org.id, name="„Furnizor Exemplu” SRL", idno="1000000000002"))
        bank = BankAccount(
            organization_id=org.id, bank_name="Banca demonstrativă", currency="MDL", account_id=accounts["242"].id
        )
        bank.iban = "MD00XX000000000000000001"
        db.add(bank)
        db.commit()
        print(f"seed: creat {settings.demo_email} cu baza „{ws.name}”")


if __name__ == "__main__":
    run()
