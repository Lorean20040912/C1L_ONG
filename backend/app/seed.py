"""Date demonstrative pentru dezvoltare: `python -m app.seed`.

Creează utilizatorul din DEMO_EMAIL / DEMO_PASSWORD (dacă sunt setate în .env)
și o bază cu o organizație fictivă, conturile ONG și politica contabilă. Rulat de mai multe ori,
nu dublează nimic.
"""

from datetime import date

from sqlalchemy import select

from app.auth.models import OrganizationMember, User
from app.catalogs.models import Account
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import AccountKind, EntityType, UserRole
from app.core.security import hash_password
from app.posting.models import AccountingPolicy
from app.workspaces.models import Organization, Workspace

# conturile folosite de regulile standard ONG (docs/11)
DEMO_ACCOUNTS = [
    ("123", "Mijloace fixe", AccountKind.active),
    ("124", "Amortizarea mijloacelor fixe", AccountKind.passive),
    ("211", "Materiale", AccountKind.active),
    ("234", "Creanțe curente privind alte operațiuni", AccountKind.active),
    ("234.4", "Creanțe privind mijloacele cu destinație specială", AccountKind.active),
    ("242", "Conturi curente în monedă națională", AccountKind.active),
    ("3411", "Fonduri de active imobilizate", AccountKind.passive),
    ("3412", "Fonduri de autofinanțare", AccountKind.passive),
    ("425", "Finanțări și încasări cu destinație specială pe termen lung", AccountKind.passive),
    ("521", "Datorii comerciale curente", AccountKind.passive),
    ("531", "Datorii față de personal", AccountKind.passive),
    ("535", "Venituri anticipate curente", AccountKind.passive),
    ("537", "Finanțări și încasări cu destinație specială curente", AccountKind.passive),
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
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=UserRole.chief_accountant))
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
        db.commit()
        print(f"seed: creat {settings.demo_email} cu baza „{ws.name}”")


if __name__ == "__main__":
    run()
