"""Централизованный сервис аудит-лога."""

from app.extensions import db
from app.models import AuditLog


def log_action(
    action: str,
    user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
    category: str = "account",
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        category=category,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )
    db.session.add(entry)
    return entry
