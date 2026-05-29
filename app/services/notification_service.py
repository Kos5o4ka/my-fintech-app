"""Сервис уведомлений — рассылка, site notifications."""

import logging

from app.extensions import db
from app.models import SiteNotification, User
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)


def broadcast(
    admin_user_id: int,
    recipients: str | list[int],
    channels: list[str],
    title: str,
    body: str,
) -> dict:
    """Отправляет уведомление выбранным пользователям через выбранные каналы."""
    if recipients == "all":
        users = User.query.all()
    else:
        users = User.query.filter(User.id.in_(recipients)).all()

    sent_site = 0
    sent_tg = 0

    for u in users:
        if "site" in channels:
            db.session.add(SiteNotification(user_id=u.id, title=title, body=body))
            sent_site += 1

        if "telegram" in channels and u.telegram_chat_id and u.telegram_notifications:
            try:
                from app.services.telegram_service import send_message  # avoid circular
                send_message(u.telegram_chat_id, f"📢 <b>{title}</b>\n\n{body}")
                sent_tg += 1
            except Exception as exc:
                logger.warning("Broadcast TG failed for user %s: %s", u.id, exc)

    log_action(
        "admin_broadcast",
        user_id=admin_user_id,
        category="account",
        details={"recipients": len(users), "channels": channels, "site": sent_site, "tg": sent_tg},
    )
    db.session.commit()
    return {"sent_site": sent_site, "sent_tg": sent_tg, "total_users": len(users)}


def get_unread_count(user_id: int) -> int:
    return SiteNotification.query.filter_by(user_id=user_id, is_read=False).count()


def get_notifications(user_id: int, page: int = 1, per_page: int = 20) -> tuple[list, int]:
    query = SiteNotification.query.filter_by(user_id=user_id).order_by(
        SiteNotification.created_at.desc()
    )
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total


def mark_read(user_id: int, ids: list[int] | None = None, all_: bool = False) -> int:
    query = SiteNotification.query.filter_by(user_id=user_id, is_read=False)
    if not all_ and ids:
        query = query.filter(SiteNotification.id.in_(ids))
    count = query.update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    return count
