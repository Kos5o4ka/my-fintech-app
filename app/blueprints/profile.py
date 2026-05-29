"""Blueprint профиля — тонкий HTTP-слой."""

import logging

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf

from app.services.user_service import (
    save_avatar,
    delete_avatar,
    update_telegram_settings,
    get_profile_stats,
    get_activity_log,
    unlink_telegram,
)

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/api/profile/stats", methods=["GET"])
@login_required
def profile_stats():
    stats = get_profile_stats(current_user.id)
    return jsonify(stats)


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


@profile_bp.route("/api/profile/avatar", methods=["DELETE"])
@login_required
def delete_avatar_route():
    delete_avatar(current_user)
    return jsonify({"status": "success", "message": "Аватар успешно удалён."})


@profile_bp.route("/api/profile/telegram/status", methods=["GET"])
@login_required
def telegram_status():
    from flask import current_app

    bot_username = current_app.config.get("TELEGRAM_BOT_USERNAME", "InvestTrackBot")
    return jsonify(
        {
            "status": "success",
            "linked": bool(current_user.telegram_chat_id),
            "notifications": bool(current_user.telegram_notifications),
            "bot_username": bot_username,
            "telegram_username": current_user.telegram_username or None,
        }
    )


@profile_bp.route("/api/profile/telegram/link", methods=["POST"])
@login_required
def telegram_link():
    from flask import current_app
    from app.services.telegram_service import generate_link_token, get_bot_deep_link

    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        return jsonify(
            {
                "status": "error",
                "message": "Telegram-бот не настроен на этом сервере.",
            }
        ), 503

    if current_user.telegram_chat_id:
        return jsonify(
            {
                "status": "error",
                "message": "Telegram уже привязан. Сначала отвяжите текущий аккаунт.",
            }
        ), 400

    token = generate_link_token(current_user.id)
    deep_link = get_bot_deep_link(token)
    return jsonify(
        {
            "status": "success",
            "deep_link": deep_link,
            "message": "Перейдите по ссылке и нажмите Start в боте.",
        }
    )


@profile_bp.route("/api/profile/telegram/unlink", methods=["POST"])
@login_required
def telegram_unlink_route():
    if not current_user.telegram_chat_id:
        return jsonify(
            {
                "status": "error",
                "message": "Telegram не привязан к вашему аккаунту.",
            }
        ), 400

    unlink_telegram(current_user)
    return jsonify(
        {
            "status": "success",
            "message": "Telegram успешно отвязан.",
        }
    )


@profile_bp.route("/api/profile/telegram/notifications", methods=["POST"])
@login_required
def telegram_notifications():
    if not current_user.telegram_chat_id:
        return jsonify(
            {
                "status": "error",
                "message": "Telegram не привязан. Сначала привяжите аккаунт.",
            }
        ), 400

    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))
    update_telegram_settings(current_user, enabled)
    state = "включены" if enabled else "выключены"
    return jsonify(
        {
            "status": "success",
            "message": f"Telegram-уведомления {state}.",
        }
    )


_ACTION_LABELS = {
    "login_ok": ("✅", "Вход в систему"),
    "login_fail": ("❌", "Неудачная попытка входа"),
    "login_2fa_sent": ("📲", "Отправлен 2FA-код"),
    "login_2fa_fail": ("⚠️", "Неверный 2FA-код"),
    "logout": ("👋", "Выход из системы"),
    "change_password": ("🔑", "Смена пароля"),
    "tg_link": ("🔗", "Telegram привязан"),
    "tg_unlink": ("🔓", "Telegram отвязан"),
}


@profile_bp.route("/api/profile/2fa/send-otp", methods=["POST"])
@login_required
def send_2fa_otp():
    """Отправляет OTP-код в Telegram для подтверждения отключения 2FA."""
    if not current_user.telegram_chat_id:
        return jsonify({"status": "error", "message": "Telegram не привязан."}), 400
    from app.services.telegram_service import generate_otp
    generate_otp(current_user.telegram_chat_id)
    return jsonify({"status": "success", "message": "Код отправлен в Telegram."})


@profile_bp.route("/api/profile/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """Отключает 2FA. Требует OTP из Telegram или пароль."""
    from werkzeug.security import check_password_hash
    from app.extensions import db
    data = request.get_json(silent=True) or {}
    method = data.get("method")

    if method == "otp":
        if not current_user.telegram_chat_id:
            return jsonify({"status": "error", "message": "Telegram не привязан."}), 400
        from app.services.telegram_service import verify_otp
        if not verify_otp(current_user.telegram_chat_id, str(data.get("code", "")).strip()):
            return jsonify({"status": "error", "message": "Неверный или просроченный код."}), 400
    elif method == "password":
        if not check_password_hash(current_user.password_hash, data.get("password", "")):
            return jsonify({"status": "error", "message": "Неверный пароль."}), 400
    else:
        return jsonify({"status": "error", "message": "Укажите метод: otp или password."}), 400

    current_user.two_fa_enabled = False
    db.session.commit()
    return jsonify({"status": "success", "message": "2FA отключена. При входе код больше не требуется."})


@profile_bp.route("/api/profile/2fa/enable", methods=["POST"])
@login_required
def enable_2fa():
    """Включает 2FA (не требует подтверждения)."""
    from app.extensions import db
    if not current_user.telegram_chat_id:
        return jsonify({"status": "error", "message": "Для 2FA нужно привязать Telegram."}), 400
    current_user.two_fa_enabled = True
    db.session.commit()
    return jsonify({"status": "success", "message": "2FA включена. Код будет приходить при каждом входе."})


@profile_bp.route("/api/profile/activity", methods=["GET"])
@login_required
def profile_activity():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 20
    entries_raw, total = get_activity_log(current_user.id, page, per_page)

    entries = []
    for log in entries_raw:
        icon, label = _ACTION_LABELS.get(log.action, ("🔔", log.action))
        entries.append(
            {
                "id": log.id,
                "action": log.action,
                "label": label,
                "icon": icon,
                "ip_address": log.ip_address or "—",
                "created_at": log.created_at.strftime("%Y-%m-%d %H:%M")
                if log.created_at
                else "—",
                "details": log.details or "",
            }
        )

    return jsonify(
        {
            "status": "success",
            "entries": entries,
            "total": total,
            "page": page,
            "pages": -(-total // per_page),
        }
    )
