"""Date demonstrative pentru dezvoltare: `python -m app.seed`.

Creează utilizatorul din DEMO_EMAIL / DEMO_PASSWORD (dacă sunt setate în .env)
și o bază cu o organizație fictivă și câteva conturi. Rulat de mai multe ori,
nu dublează nimic.
"""

from sqlalchemy import select

from app.auth.models import OrganizationMember, User
from app.catalogs.models import Account
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import AccountKind, EntityType, UserRole
from app.core.security import hash_password
from app.workspaces.models import Organization, Workspace

DEMO_ACCOUNTS = [
    ("123", "Mijloace fixe", AccountKind.active),
    ("211", "Materiale", AccountKind.active),
    ("242", "Conturi curente în monedă națională", AccountKind.active),
    ("521", "Datorii comerciale curente", AccountKind.passive),
    ("531", "Datorii față de personal", AccountKind.passive),
    ("535", "Venituri anticipate curente", AccountKind.passive),
    ("713", "Cheltuieli administrative", AccountKind.active),
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
        for code, name, kind in DEMO_ACCOUNTS:
            db.add(Account(organization_id=org.id, code=code, name=name, account_kind=kind))
        db.commit()
        print(f"seed: creat {settings.demo_email} cu baza „{ws.name}”")


if __name__ == "__main__":
    run()
