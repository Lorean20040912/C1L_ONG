import uuid

from sqlalchemy.orm import Session

from app.audit.models import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    entity: str,
    entity_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    """Adaugă o înregistrare în audit_log, în tranzacția curentă."""
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            old_values=old_values,
            new_values=new_values,
        )
    )
