"""Сервис Telegram-бота — привязка аккаунта, OTP 2FA, уведомления."""
import logging
import secrets
from typing import Optional

import requests as http_requests
from flask import current_app

from extensions import cache

logger = logging.getLogger(__name__)

# TTL для одноразовых токенов
_LINK_TOKEN_TTL = 600   # 10 минут — для привязки аккаунта
_OTP_TTL = 300          # 5 минут — для кода 2FA
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
    send_message(
        chat_id,
        f"🔐 Код подтверждения для входа в InvestTrack:\n\n"
        f"<b>{code}</b>\n\n"
        f"Код действителен 5 минут. Никому не сообщайте его.",
        parse_mode="HTML",
    )
    return code


def verify_otp(chat_id: str, code: str) -> bool:
    """Проверяет OTP код. Одноразовый — удаляется после первой проверки."""
    stored = cache.get(f"tg_otp:{chat_id}")
    if stored is None:
        return False
    # Сравниваем через secrets.compare_digest для защиты от timing attacks
    is_valid = secrets.compare_digest(str(stored), str(code).strip())
    if is_valid:
        cache.delete(f"tg_otp:{chat_id}")
    return is_valid


# ── Pending 2FA сессия ────────────────────────────────────────────────────────

def create_pending_2fa(user_id: int, chat_id: str) -> str:
    """Создаёт pending-токен 2FA. Возвращает токен для клиента."""
    token = secrets.token_urlsafe(32)
    cache.set(f"tg_2fa:{token}", {"user_id": user_id, "chat_id": chat_id}, timeout=_PENDING_2FA_TTL)
    return token


def resolve_pending_2fa(token: str) -> Optional[dict]:
    """Возвращает {user_id, chat_id} по pending-токену (одноразовый)."""
    data = cache.get(f"tg_2fa:{token}")
    if data is not None:
        cache.delete(f"tg_2fa:{token}")
    return data


# ── Отправка сообщений ────────────────────────────────────────────────────────

def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Отправляет сообщение через Telegram Bot API.

    Возвращает True при успехе, False при ошибке.
    """
    bot_token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — сообщение не отправлено.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        resp = http_requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            logger.warning("Telegram API error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except http_requests.RequestException as exc:
        logger.error("Telegram send_message failed: %s", exc)
        return False


def get_bot_deep_link(token: str) -> str:
    """Формирует deep-link для открытия бота с параметром start."""
    bot_username = current_app.config.get("TELEGRAM_BOT_USERNAME", "InvestTrackBot")
    return f"https://t.me/{bot_username}?start={token}"
