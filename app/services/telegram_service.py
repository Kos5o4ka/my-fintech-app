"""Сервис Telegram-бота — привязка аккаунта, OTP 2FA, уведомления."""

import logging
import secrets
from typing import Optional

import requests as http_requests
from flask import current_app

from app.extensions import cache

logger = logging.getLogger(__name__)

# TTL для одноразовых токенов
_LINK_TOKEN_TTL = 600  # 10 минут — для привязки аккаунта
_OTP_TTL = 300  # 5 минут — для кода 2FA
_PENDING_2FA_TTL = 300  # 5 минут — для ожидающего входа (2FA сессия)


# ── Привязка аккаунта ─────────────────────────────────────────────────────────


def generate_link_token(user_id: int) -> str:
    """Создаёт одноразовый токен для привязки Telegram.

    Пользователь отправляет боту /start <token>.
    Токен действителен 10 минут.
    """
    token = secrets.token_urlsafe(32)
    cache.set(f"tg_link:{token}", user_id, timeout=_LINK_TOKEN_TTL)
    return token


def verify_link_token(token: str) -> Optional[int]:
    """Возвращает user_id по токену привязки (одноразовый — сразу удаляется)."""
    user_id = cache.get(f"tg_link:{token}")
    if user_id is not None:
        cache.delete(f"tg_link:{token}")
    return user_id


# ── OTP 2FA ───────────────────────────────────────────────────────────────────


def generate_otp(chat_id: str) -> str:
    """Генерирует 6-значный OTP, сохраняет в кэше и отправляет через бота.

    Возвращает код (для логов/тестов, в продакшне не используется напрямую).
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(f"tg_otp:{chat_id}", code, timeout=_OTP_TTL)
    # copy_text button (Telegram Bot API 6.7+, client 10.6+)
    reply_markup = {
        "inline_keyboard": [[
            {"text": "📋 Скопировать код", "copy_text": {"text": code}}
        ]]
    }
    send_message(
        chat_id,
        f"🔐 Код подтверждения для входа в InvestTrack:\n\n"
        f"<code>{code}</code>\n\n"
        f"⏱ Код действителен 5 минут. Никому не сообщайте его.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    return code


def verify_otp(chat_id: str, code: str) -> bool:
    """Проверяет OTP код. Одноразовый — удаляется сразу при первой проверке."""
    stored = cache.get(f"tg_otp:{chat_id}")
    if stored is None:
        return False
    # Удаляем код сразу из кэша (сгорает при любой попытке проверки)
    cache.delete(f"tg_otp:{chat_id}")
    # Сравниваем через secrets.compare_digest для защиты от timing attacks
    return secrets.compare_digest(str(stored), str(code).strip())


# ── Pending 2FA сессия ────────────────────────────────────────────────────────


def create_pending_2fa(user_id: int, chat_id: str) -> str:
    """Создаёт pending-токен 2FA. Возвращает токен для клиента."""
    token = secrets.token_urlsafe(32)
    cache.set(
        f"tg_2fa:{token}",
        {"user_id": user_id, "chat_id": chat_id},
        timeout=_PENDING_2FA_TTL,
    )
    return token


def resolve_pending_2fa(token: str) -> Optional[dict]:
    """Возвращает {user_id, chat_id} по pending-токену (одноразовый)."""
    data = cache.get(f"tg_2fa:{token}")
    if data is not None:
        cache.delete(f"tg_2fa:{token}")
    return data


# ── Отправка сообщений ────────────────────────────────────────────────────────


def send_message(
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
) -> bool:
    """Отправляет сообщение через Telegram Bot API.

    Возвращает True при успехе, False при ошибке.
    """
    bot_token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — сообщение не отправлено.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = http_requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            logger.warning(
                "Telegram API error %s: %s", resp.status_code, resp.text[:200]
            )
            return False
        return True
    except http_requests.RequestException as exc:
        logger.error("Telegram send_message failed: %s", exc)
        return False


def refresh_tg_username(user) -> None:
    """Обновляет telegram_username пользователя через Telegram API (без commit).

    Вызывается после успешного входа. Пропускает запрос если chat_id не задан.
    """
    if not user.telegram_chat_id:
        return
    try:
        username = get_telegram_username(user.telegram_chat_id)
        if username is not None and user.telegram_username != username:
            user.telegram_username = username
    except Exception as exc:
        logger.warning(
            "Could not refresh telegram username for user %s: %s", user.id, exc
        )


def get_bot_deep_link(token: str) -> str:
    """Формирует deep-link для открытия бота с параметром start."""
    bot_username = current_app.config.get("TELEGRAM_BOT_USERNAME", "InvestTrackBot")
    return f"https://t.me/{bot_username}?start={token}"


# ── Webhook helpers (вынесены из blueprints/telegram_bot.py) ─────────────────


def refresh_username_by_chat(chat_id: str, tg_username: str) -> bool:
    """Обновляет @username по chat_id, если изменился. Возвращает True при изменении."""
    from app.extensions import db
    from app.models import User

    user = User.query.filter_by(telegram_chat_id=chat_id).first()
    if user and user.telegram_username != tg_username:
        user.telegram_username = tg_username
        db.session.commit()
        logger.info(
            "Telegram username updated: user_id=%s chat_id=%s username=%s",
            user.id, chat_id, tg_username,
        )
        return True
    return False


def link_chat_to_user(chat_id: str, link_token: str, tg_username: Optional[str] = None) -> str:
    """Привязывает chat_id к пользователю по одноразовому link-токену.

    Возвращает код результата: 'ok' | 'bad_token' | 'no_user' | 'chat_taken'.
    """
    from app.extensions import db
    from app.models import User

    user_id = verify_link_token(link_token)
    if user_id is None:
        return "bad_token"

    user = db.session.get(User, user_id)
    if user is None:
        return "no_user"

    existing = User.query.filter_by(telegram_chat_id=chat_id).first()
    if existing and existing.id != user_id:
        return "chat_taken"

    user.telegram_chat_id = chat_id
    user.telegram_notifications = True
    if tg_username:
        user.telegram_username = tg_username
    db.session.commit()
    logger.info(
        "Telegram linked: user_id=%s chat_id=%s username=%s",
        user_id, chat_id, tg_username,
    )
    return "ok"


def unlink_chat(chat_id: str) -> Optional[str]:
    """Отвязывает chat_id. Возвращает username пользователя или None если не найден."""
    from app.extensions import db
    from app.models import User

    user = User.query.filter_by(telegram_chat_id=chat_id).first()
    if not user:
        return None
    username = user.username
    user.telegram_chat_id = None
    user.telegram_notifications = False
    user.telegram_username = None
    db.session.commit()
    logger.info("Telegram unlinked: user_id=%s chat_id=%s", user.id, chat_id)
    return username


def get_telegram_username(chat_id: str) -> Optional[str]:
    """Запрашивает актуальный @username через Telegram getChat API.

    Возвращает строку без '@', либо None если не удалось получить.
    """
    bot_token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return None
    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    try:
        resp = http_requests.post(url, json={"chat_id": chat_id}, timeout=10)
        if resp.ok:
            result = resp.json().get("result", {})
            return result.get("username") or None
    except http_requests.RequestException as exc:
        logger.warning("get_telegram_username failed for chat_id=%s: %s", chat_id, exc)
    return None
