"""Blueprint профиля — аватар, email, настройки, Telegram-привязка."""
import logging

from pydantic import ValidationError
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf

from extensions import db
from services.user_service import save_avatar, update_email_settings, update_telegram_settings
from schemas.profile import EmailSettingsRequest

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


# ── Страница профиля ──────────────────────────────────────────────────────────

@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile_page():
    if request.method == "POST":
        if "avatar" not in request.files:
            return jsonify({"status": "error", "message": "Нет файла."}), 400
        try:
            save_avatar(current_user, request.files["avatar"])
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
    return render_template("profile.html", csrf_token=generate_csrf())


# ── Email-уведомления ─────────────────────────────────────────────────────────

@profile_bp.route("/api/profile/email", methods=["POST"])
@login_required
def update_email():
    try:
        req = EmailSettingsRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    update_email_settings(current_user, req.email, req.email_notifications)
    return jsonify({"status": "success", "message": "Настройки уведомлений сохранены."})


# ── Telegram — привязка ───────────────────────────────────────────────────────

@profile_bp.route("/api/profile/telegram/status", methods=["GET"])
@login_required
def telegram_status():
    """Возвращает текущий статус Telegram-привязки."""
    from flask import current_app
    bot_username = current_app.config.get("TELEGRAM_BOT_USERNAME", "InvestTrackBot")
    return jsonify({
        "status": "success",
        "linked": bool(current_user.telegram_chat_id),
        "notifications": bool(current_user.telegram_notifications),
        "bot_username": bot_username,
    })


@profile_bp.route("/api/profile/telegram/link", methods=["POST"])
@login_required
def telegram_link():
    """Генерирует deep-link для привязки Telegram.

    Если TELEGRAM_BOT_TOKEN не задан, возвращает ошибку конфигурации.
    """
    from flask import current_app
    from services.telegram_service import generate_link_token, get_bot_deep_link

    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        return jsonify({
            "status": "error",
            "message": "Telegram-бот не настроен на этом сервере.",
        }), 503

    if current_user.telegram_chat_id:
        return jsonify({
            "status": "error",
            "message": "Telegram уже привязан. Сначала отвяжите текущий аккаунт.",
        }), 400

    token = generate_link_token(current_user.id)
    deep_link = get_bot_deep_link(token)
    return jsonify({
        "status": "success",
        "deep_link": deep_link,
        "message": "Перейдите по ссылке и нажмите Start в боте.",
    })


@profile_bp.route("/api/profile/telegram/unlink", methods=["POST"])
@login_required
def telegram_unlink():
    """Отвязывает Telegram от аккаунта пользователя."""
    if not current_user.telegram_chat_id:
        return jsonify({
            "status": "error",
            "message": "Telegram не привязан к вашему аккаунту.",
        }), 400

    current_user.telegram_chat_id = None
    current_user.telegram_notifications = False
    db.session.commit()
    return jsonify({
        "status": "success",
        "message": "Telegram успешно отвязан.",
    })


@profile_bp.route("/api/profile/telegram/notifications", methods=["POST"])
@login_required
def telegram_notifications():
    """Включает/выключает Telegram-уведомления (только при привязанном боте)."""
    if not current_user.telegram_chat_id:
        return jsonify({
            "status": "error",
            "message": "Telegram не привязан. Сначала привяжите аккаунт.",
        }), 400

    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))
    update_telegram_settings(current_user, enabled)
    state = "включены" if enabled else "выключены"
    return jsonify({
        "status": "success",
        "message": f"Telegram-уведомления {state}.",
    })
