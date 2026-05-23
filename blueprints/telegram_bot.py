"""Blueprint Telegram-бота — webhook для обработки команд от бота."""
import logging

from flask import Blueprint, request, jsonify, current_app, abort

from extensions import db
from models import User
from services.telegram_service import verify_link_token, send_message

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.route("/api/telegram/webhook", methods=["POST"])
@telegram_bp.route("/api/telegram/webhook/<secret>", methods=["POST"])
def webhook(secret=None):
    """Обрабатывает входящие обновления от Telegram.

    Эндпоинт освобождён от CSRF — Telegram не отправляет CSRF-токен.
    Безопасность обеспечивается секретным токеном в URL.
    """
    # Проверяем, что токен в конфиге задан
    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        return jsonify({"ok": False}), 503

    # Проверка секретного ключа вебхука для защиты от спуфинга
    expected_secret = current_app.config.get("TELEGRAM_WEBHOOK_SECRET")
    if expected_secret and secret != expected_secret:
        abort(403)

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return jsonify({"ok": True})

    # /start <token> — привязка аккаунта
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            token = parts[1].strip()
            _handle_link(chat_id, token)
        else:
            send_message(
                chat_id,
                "👋 Привет! Я бот InvestTrack.\n\n"
                "Чтобы привязать аккаунт, откройте профиль в InvestTrack → "
                "Уведомления → Telegram и нажмите «Привязать».",
            )

    # /stop — отвязка аккаунта
    elif text.startswith("/stop"):
        _handle_unlink(chat_id)

    # /help
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


def _handle_link(chat_id: str, token: str) -> None:
    """Привязывает Telegram chat_id к пользователю по токену."""
    user_id = verify_link_token(token)
    if user_id is None:
        send_message(
            chat_id,
            "❌ Ссылка устарела или недействительна.\n"
            "Получите новую ссылку в профиле InvestTrack.",
        )
        return

    user = db.session.get(User, user_id)
    if user is None:
        send_message(chat_id, "❌ Пользователь не найден.")
        return

    # Проверяем, не занят ли chat_id другим аккаунтом
    existing = User.query.filter_by(telegram_chat_id=chat_id).first()
    if existing and existing.id != user_id:
        send_message(
            chat_id,
            "⚠️ Этот Telegram-аккаунт уже привязан к другому профилю.\n"
            "Сначала отвяжите его командой /stop.",
        )
        return

    user.telegram_chat_id = chat_id
    user.telegram_notifications = True
    db.session.commit()

    send_message(
        chat_id,
        f"✅ Аккаунт <b>{user.username}</b> успешно привязан!\n\n"
        f"Теперь вы будете получать:\n"
        f"• Уведомления о купонных выплатах\n"
        f"• Коды подтверждения при входе (2FA)\n\n"
        f"Управление уведомлениями — в профиле InvestTrack.",
    )
    logger.info("Telegram linked: user_id=%s chat_id=%s", user_id, chat_id)


def _handle_unlink(chat_id: str) -> None:
    """Отвязывает Telegram от аккаунта по chat_id."""
    user = User.query.filter_by(telegram_chat_id=chat_id).first()
    if not user:
        send_message(chat_id, "Этот аккаунт не привязан к InvestTrack.")
        return

    user.telegram_chat_id = None
    user.telegram_notifications = False
    db.session.commit()

    send_message(
        chat_id,
        f"✅ Аккаунт <b>{user.username}</b> успешно отвязан от бота.\n"
        f"Уведомления в Telegram отключены.",
    )
    logger.info("Telegram unlinked: user_id=%s chat_id=%s", user.id, chat_id)
