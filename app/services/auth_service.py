"""Сервис аутентификации — login, audit, 2FA."""

import logging
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User, AuditLog

logger = logging.getLogger(__name__)


def find_user_by_username(username: str) -> Optional[User]:
    return User.query.filter_by(username=username).first()


def get_user_by_id(user_id: int) -> Optional[User]:
    return db.session.get(User, user_id)


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)


def set_password(user: User, new_password: str) -> None:
    user.password_hash = generate_password_hash(new_password)


def audit_log(
    action: str,
    user_id: Optional[int] = None,
    ip: str = "",
    user_agent: str = "",
    details: Optional[dict] = None,
) -> None:
    try:
        log = AuditLog(
            action=action,
            user_id=user_id,
            ip_address=ip,
            user_agent=user_agent,
            details=details,
        )
        db.session.add(log)
    except Exception as exc:
        logger.error("Audit log error: %s", exc)


def commit() -> None:
    db.session.commit()
