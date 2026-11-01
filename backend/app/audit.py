from sqlalchemy.orm import Session

from .models import AuditLog, User


def write_audit(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id=None,
    details: dict | None = None,
) -> None:
    db.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
    ))
