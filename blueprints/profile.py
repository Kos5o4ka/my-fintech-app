"""Blueprint профиля — аватар, email, настройки, Telegram-привязка, activity."""
import logging

from pydantic import ValidationError
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf

from extensions import db
from models import AuditLog
from services.user_service import save_avatar, delete_avatar, update_telegram_settings

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


# ── Быстрая статистика для hero профиля ──────────────────────────────────────

@profile_bp.route("/api/profile/stats", methods=["GET"])
@login_required
def profile_stats():
    """Счётчики для hero-секции профиля: облигаций, стоимость, закрытые сделки."""
    from models import BondPortfolio
    active = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=False).all()
    sold   = BondPortfolio.query.filter_by(user_id=current_user.id, is_sold=True).count()
    total_value = sum(
        (float(b.last_price or b.buy_price)) * b.amount
        for b in active
    )
    return jsonify({
        "bond_count": len(active),
        "sold_count": sold,
        "total_value": round(total_value, 2),
    })


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


# ── Аватар — удаление ────────────────────────────────────────────────────────

@profile_bp.route("/api/profile/avatar", methods=["DELETE"])
@login_required
def delete_avatar_route():
    """Удаляет аватар пользователя с диска и сбрасывает avatar в None."""
    delete_avatar(current_user)
    return jsonify({"status": "success", "message": "Аватар успешно удалён."})


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
        "telegram_username": current_user.telegram_username or None,
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
    current_user.telegram_username = None
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


# ── Activity feed (Stage 4) ───────────────────────────────────────────────────

_ACTION_LABELS = {
    "login_ok":       ("✅", "Вход в систему"),
    "login_fail":     ("❌", "Неудачная попытка входа"),
    "login_2fa_sent": ("📲", "Отправлен 2FA-код"),
    "login_2fa_fail": ("⚠️", "Неверный 2FA-код"),
    "logout":         ("👋", "Выход из системы"),
    "change_password":("🔑", "Смена пароля"),
    "tg_link":        ("🔗", "Telegram привязан"),
    "tg_unlink":      ("🔓", "Telegram отвязан"),
}


@profile_bp.route("/api/profile/activity", methods=["GET"])
@login_required
def profile_activity():
    """Журнал действий текущего пользователя (последние 50 записей)."""
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 20
    query = (
        AuditLog.query
        .filter_by(user_id=current_user.id)
        .order_by(AuditLog.created_at.desc())
    )
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()

    entries = []
    for log in logs:
        icon, label = _ACTION_LABELS.get(log.action, ("🔔", log.action))
        entries.append({
            "id": log.id,
            "action": log.action,
            "label": label,
            "icon": icon,
            "ip_address": log.ip_address or "—",
            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "—",
            "details": log.details or "",
        })

    return jsonify({
        "status": "success",
        "entries": entries,
        "total": total,
        "page": page,
        "pages": -(-total // per_page),  # ceiling division
    })
