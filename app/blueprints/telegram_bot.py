"""Blueprint Telegram-бота — webhook для входящих обновлений.

Слой: HTTP-парсинг → telegram_service. Никаких прямых обращений к БД.
"""

import logging

from flask import Blueprint, abort, current_app, jsonify, request

from app.services.telegram_service import (
    link_chat_to_user,
    refresh_username_by_chat,
    send_message,
    unlink_chat,
)

logger = logging.getLogger(__name__)
telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.route("/api/telegram/webhook", methods=["POST"])
@telegram_bp.route("/api/telegram/webhook/<secret>", methods=["POST"])
def webhook(secret=None):
    """Обрабатывает входящие обновления от Telegram.

    Освобождён от CSRF — Telegram не отправляет CSRF-токен. Безопасность
    обеспечивается секретным токеном в URL (``TELEGRAM_WEBHOOK_SECRET``).
    """
    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        return jsonify({"ok": False}), 503

    expected_secret = current_app.config.get("TELEGRAM_WEBHOOK_SECRET")
    if expected_secret and secret != expected_secret:
        abort(403)

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    tg_username = message.get("from", {}).get("username")

    if not chat_id or not text:
        return jsonify({"ok": True})

    if tg_username:
        refresh_username_by_chat(chat_id, tg_username)

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            _reply_link(chat_id, parts[1].strip(), tg_username)
        else:
            send_message(
                chat_id,
                "👋 Привет! Я бот InvestTrack.\n\n"
                "Чтобы привязать аккаунт, откройте профиль в InvestTrack → "
                "Уведомления → Telegram и нажмите «Привязать».",
            )
    elif text.startswith("/stop"):
        _reply_unlink(chat_id)
    elif text.startswith("/help"):
        send_message(
            chat_id,
            "📋 <b>Команды бота InvestTrack:</b>\n\n"
            "/start — привязать аккаунт\n"
            "/stop — отвязать аккаунт\n"
            "/help — это сообщение",
        )
    else:
        send_message(
            chat_id,
            "Я понимаю только /start, /stop и /help.\n"
            "Для управления уведомлениями откройте InvestTrack → Профиль.",
        )

    return jsonify({"ok": True})


def _reply_link(chat_id: str, link_token: str, tg_username: str | None) -> None:
    result = link_chat_to_user(chat_id, link_token, tg_username)
    if result == "bad_token":
        send_message(
            chat_id,
            "❌ Ссылка устарела или недействительна.\n"
            "Получите новую ссылку в профиле InvestTrack.",
        )
    elif result == "no_user":
        send_message(chat_id, "❌ Пользователь не найден.")
    elif result == "chat_taken":
        send_message(
            chat_id,
            "⚠️ Этот Telegram-аккаунт уже привязан к другому профилю.\n"
            "Сначала отвяжите его командой /stop.",
        )
    else:
        # Чтобы вывести имя — повторно достанем пользователя; экономим запрос:
        # link_chat_to_user уже привязал, безопасно прочитать чистым SELECT.
        from app.models import User
        user = User.query.filter_by(telegram_chat_id=chat_id).first()
        name = user.username if user else "—"
        send_message(
            chat_id,
            f"✅ Аккаунт <b>{name}</b> успешно привязан!\n\n"
            f"Теперь вы будете получать:\n"
            f"• Уведомления о купонных выплатах\n"
            f"• Коды подтверждения при входе (2FA)\n\n"
            f"Управление уведомлениями — в профиле InvestTrack.",
        )


def _reply_unlink(chat_id: str) -> None:
    username = unlink_chat(chat_id)
    if username is None:
        send_message(chat_id, "Этот аккаунт не привязан к InvestTrack.")
    else:
        send_message(
            chat_id,
            f"✅ Аккаунт <b>{username}</b> успешно отвязан от бота.\n"
            f"Уведомления в Telegram отключены.",
        )
