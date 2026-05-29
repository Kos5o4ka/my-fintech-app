"""Blueprint профиля — тонкий HTTP-слой."""

import logging

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.security import check_password_hash

from app.services.user_service import (
    save_avatar,
    delete_avatar,
    update_telegram_settings,
    get_profile_stats,
    get_activity_log,
    unlink_telegram,
    update_user_settings,
    enable_2fa,
    disable_2fa,
)
from app.services.telegram_service import (
    generate_otp,
    verify_otp,
)
from app.services.notification_service import (
    get_unread_count,
    get_notifications,
    mark_read,
)

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)

_ACTION_LABELS = {
    "login_ok": ("✅", "Вход в систему"),
    "login_fail": ("❌", "Неудачная попытка входа"),
    "login_2fa_sent": ("📲", "Отправлен 2FA-код"),
    "login_2fa_fail": ("⚠️", "Неверный 2FA-код"),
    "logout": ("👋", "Выход из системы"),
    "change_password": ("🔑", "Смена пароля"),
    "tg_link": ("🔗", "Telegram привязан"),
    "tg_unlink": ("🔓", "Telegram отвязан"),
    "settings_update": ("⚙️", "Настройки изменены"),
    "bond_add": ("📈", "Добавлена позиция"),
    "bond_sell": ("💰", "Продажа"),
    "bond_delete": ("🗑️", "Удаление позиции"),
    "import_ok": ("📥", "Импорт отчёта"),
    "import_fail": ("⚠️", "Ошибка импорта"),
    "alert_triggered": ("🔔", "Сработал алёрт"),
    "portfolio_reset": ("♻️", "Сброс портфеля"),
    # Наследие старых версий (Legacy logs)
    "portfolio_import": ("📥", "Импорт отчёта (legacy)"),
    "portfolio_add_bond": ("📈", "Добавлена позиция (legacy)"),
    "admin_broadcast": ("📢", "Админ рассылка"),
}


# ── Profile ──────────────────────────────────────────────────────────────────


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


# ── Telegram ─────────────────────────────────────────────────────────────────


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
            {"status": "error", "message": "Telegram-бот не настроен на этом сервере."}
        ), 503

    if current_user.telegram_chat_id:
        return jsonify(
            {"status": "error", "message": "Telegram уже привязан. Сначала отвяжите текущий аккаунт."}
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
            {"status": "error", "message": "Telegram не привязан к вашему аккаунту."}
        ), 400

    unlink_telegram(current_user)
    return jsonify({"status": "success", "message": "Telegram успешно отвязан."})


@profile_bp.route("/api/profile/telegram/notifications", methods=["POST"])
@login_required
def telegram_notifications():
    if not current_user.telegram_chat_id:
        return jsonify(
            {"status": "error", "message": "Telegram не привязан. Сначала привяжите аккаунт."}
        ), 400

    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))
    update_telegram_settings(current_user, enabled)
    state = "включены" if enabled else "выключены"
    return jsonify({"status": "success", "message": f"Telegram-уведомления {state}."})


# ── Tinkoff Token ──────────────────────────────────────────────────────────────


@profile_bp.route("/api/profile/tinkoff_token", methods=["POST"])
@login_required
def save_tinkoff_token():
    from app.extensions import db
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    
    current_user.tinkoff_token = token if token else None
    db.session.commit()
    
    msg = "Токен сохранён." if token else "Токен удалён."
    return jsonify({"status": "success", "message": msg})


# ── Settings ─────────────────────────────────────────────────────────────────


@profile_bp.route("/api/profile/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify({
        "status": "success",
        "theme": current_user.theme or "system",
        "notif_time": current_user.notif_time or "09:00",
        "notif_timezone": current_user.notif_timezone or "Europe/Moscow",
        "oferta_advance_days": current_user.oferta_advance_days if current_user.oferta_advance_days is not None else 14,
    })


@profile_bp.route("/api/profile/settings", methods=["POST"])
@login_required
def save_settings():
    from pydantic import ValidationError
    from app.schemas.profile import SettingsUpdate

    data = request.get_json(silent=True) or {}
    try:
        settings = SettingsUpdate(**data)
    except ValidationError:
        return jsonify({"status": "error", "message": "Некорректные данные."}), 400

    update_user_settings(
        current_user,
        theme=settings.theme,
        notif_time=settings.notif_time,
        notif_timezone=settings.notif_timezone,
        oferta_advance_days=settings.oferta_advance_days,
    )
    return jsonify({"status": "success", "message": "Настройки сохранены."})


# ── 2FA ──────────────────────────────────────────────────────────────────────


@profile_bp.route("/api/profile/2fa/send-otp", methods=["POST"])
@login_required
def send_2fa_otp():
    if not current_user.telegram_chat_id:
        return jsonify({"status": "error", "message": "Telegram не привязан."}), 400
    generate_otp(current_user.telegram_chat_id)
    return jsonify({"status": "success", "message": "Код отправлен в Telegram."})


@profile_bp.route("/api/profile/2fa/disable", methods=["POST"])
@login_required
def disable_2fa_route():
    data = request.get_json(silent=True) or {}
    method = data.get("method")

    if method == "otp":
        if not current_user.telegram_chat_id:
            return jsonify({"status": "error", "message": "Telegram не привязан."}), 400
        if not verify_otp(current_user.telegram_chat_id, str(data.get("code", "")).strip()):
            return jsonify({"status": "error", "message": "Неверный или просроченный код."}), 400
    elif method == "password":
        if not check_password_hash(current_user.password_hash, data.get("password", "")):
            return jsonify({"status": "error", "message": "Неверный пароль."}), 400
    else:
        return jsonify({"status": "error", "message": "Укажите метод: otp или password."}), 400

    disable_2fa(current_user)
    return jsonify({"status": "success", "message": "2FA отключена. При входе код больше не требуется."})


@profile_bp.route("/api/profile/2fa/enable", methods=["POST"])
@login_required
def enable_2fa_route():
    if not current_user.telegram_chat_id:
        return jsonify({"status": "error", "message": "Для 2FA нужно привязать Telegram."}), 400
    enable_2fa(current_user)
    return jsonify({"status": "success", "message": "2FA включена. Код будет приходить при каждом входе."})


# ── Activity ─────────────────────────────────────────────────────────────────


@profile_bp.route("/api/profile/activity", methods=["GET"])
@login_required
def profile_activity():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 20
    category = request.args.get("category", "").strip() or None
    if category and category not in ("account", "portfolio"):
        category = None
    entries_raw, total = get_activity_log(current_user.id, page, per_page, category)

    entries = []
    for log in entries_raw:
        icon, label = _ACTION_LABELS.get(log.action, ("🔔", log.action))
        
        details_str = log.details or ""
        if isinstance(details_str, str) and details_str.startswith("{") and details_str.endswith("}"):
            import json
            try:
                d = json.loads(details_str)
                if isinstance(d, dict):
                    if d.get("method") == "2fa_telegram":
                        details_str = "Метод: Telegram 2FA"
                    elif "username" in d:
                        details_str = f"Логин: {d['username']}"
                    elif "error" in d:
                        details_str = f"Ошибка: {d['error']}"
                    else:
                        parts = [f"{k}: {v}" for k, v in d.items()]
                        details_str = ", ".join(parts)
            except Exception:
                pass
        elif isinstance(details_str, dict):
            d = details_str
            if d.get("method") == "2fa_telegram":
                details_str = "Метод: Telegram 2FA"
            elif "username" in d:
                details_str = f"Логин: {d['username']}"
            elif "error" in d:
                details_str = f"Ошибка: {d['error']}"
            else:
                details_str = ", ".join([f"{k}: {v}" for k, v in d.items()])

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
                "details": details_str,
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


# ── Site notifications ───────────────────────────────────────────────────────


@profile_bp.route("/api/notifications/unread_count", methods=["GET"])
@login_required
def notif_unread_count():
    return jsonify({"count": get_unread_count(current_user.id)})


@profile_bp.route("/api/notifications", methods=["GET"])
@login_required
def notif_list():
    page = max(request.args.get("page", 1, type=int), 1)
    items, total = get_notifications(current_user.id, page)
    return jsonify({
        "status": "success",
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "—",
            }
            for n in items
        ],
        "total": total,
        "page": page,
    })


@profile_bp.route("/api/notifications/read", methods=["POST"])
@login_required
def notif_mark_read():
    data = request.get_json(silent=True) or {}
    if data.get("all"):
        count = mark_read(current_user.id, all_=True)
    else:
        ids = data.get("ids", [])
        count = mark_read(current_user.id, ids=ids)
    return jsonify({"status": "success", "marked": count})
