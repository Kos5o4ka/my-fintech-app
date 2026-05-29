"""Сервис администрирования — CRUD пользователей, аудит."""

import logging
from typing import Optional

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User, AuditLog

logger = logging.getLogger(__name__)


def get_all_users() -> list[dict]:
    users = User.query.all()
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin, "avatar": u.avatar} for u in users]


def find_user_by_username(username: str) -> Optional[User]:
    return User.query.filter_by(username=username).first()


def create_user(username: str, password: str, is_admin: bool = False) -> User:
    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=is_admin,
    )
    db.session.add(new_user)
    db.session.commit()
    return new_user


def get_user_by_id(user_id: int) -> Optional[User]:
    return db.session.get(User, user_id)


def delete_user(user_id: int) -> Optional[User]:
    """Возвращает удалённого пользователя или None если не найден."""
    user = db.session.get(User, user_id)
    if user is None:
        return None
    db.session.delete(user)
    db.session.commit()
    return user


def change_user_password(
    user_id: int, new_password: str, admin_user_id: int, ip: str, user_agent: str
) -> Optional[User]:
    """Меняет пароль + записывает в аудит. Возвращает None если не найден."""
    target = db.session.get(User, user_id)
    if target is None:
        return None
    target.password_hash = generate_password_hash(new_password)
    log = AuditLog(
        action="admin_change_password",
        user_id=admin_user_id,
        ip_address=ip,
        user_agent=user_agent,
        details={"target_user_id": target.id, "target_username": target.username},
    )
    db.session.add(log)
    db.session.commit()
    return target
