"""Blueprint аутентификации — вход, выход, смена пароля, 2FA через Telegram."""
import logging
from typing import Optional

from pydantic import ValidationError
from flask import Blueprint, request, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter
from models import User, AuditLog
from schemas.auth import ChangePasswordRequest
from constants import MIN_PASSWORD_LEN

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _get_client_ip() -> str:
    """Возвращает IP клиента с учётом X-Forwarded-For (за reverse proxy)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def _get_user_agent() -> str:
    return (request.headers.get("User-Agent") or "")[:255]


def _refresh_tg_username(user) -> None:
    """Обновляет telegram_username пользователя через Telegram API (без commit)."""
    if not user.telegram_chat_id:
        return
    try:
        from services.telegram_service import get_telegram_username
        username = get_telegram_username(user.telegram_chat_id)
        if username is not None and user.telegram_username != username:
            user.telegram_username = username
    except Exception as exc:
        logger.warning("Could not refresh telegram username for user %s: %s", user.id, exc)


def _audit(action: str, user_id: Optional[int] = None, details: Optional[str] = None) -> None:
    """Записывает событие в журнал аудита (без commit — вызывать до commit сессии)."""
    try:
        log = AuditLog(
            action=action,
            user_id=user_id,
            ip_address=_get_client_ip(),
            user_agent=_get_user_agent(),
            details=details,
        )
        db.session.add(log)
    except Exception as exc:
        logger.error("Audit log error: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password_hash, password):
        _audit("login_fail", details=f"username={username[:50]}")
        db.session.commit()
        return jsonify({"status": "error", "message": "Неверный логин или пароль."}), 401

    # Если у пользователя привязан Telegram — включаем 2FA
    if user.telegram_chat_id:
        from services.telegram_service import generate_otp, create_pending_2fa
        token = create_pending_2fa(user.id, user.telegram_chat_id)
        generate_otp(user.telegram_chat_id)
        _audit("login_2fa_sent", user_id=user.id)
        db.session.commit()
        return jsonify({
            "status": "2fa_required",
            "token": token,
            "message": "Код подтверждения отправлен в Telegram.",
        })

    # Обычный вход без 2FA
    session.permanent = True
    login_user(user, remember=True)
    _audit("login_ok", user_id=user.id)
    _refresh_tg_username(user)
    db.session.commit()
    return jsonify({
        "status": "success",
        "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin},
    })


@auth_bp.route("/api/auth/verify_2fa", methods=["POST"])
@limiter.limit("10 per minute")
def verify_2fa():
    """Завершает вход после успешной проверки OTP-кода из Telegram."""
    data = request.get_json() or {}
    token = data.get("token", "").strip()
    code = data.get("code", "").strip()

    if not token or not code:
        return jsonify({"status": "error", "message": "Токен и код обязательны."}), 400

    from services.telegram_service import resolve_pending_2fa, verify_otp
    pending = resolve_pending_2fa(token)
    if not pending:
        return jsonify({
            "status": "error",
            "message": "Сессия истекла. Войдите заново.",
        }), 401

    chat_id = pending["chat_id"]
    user_id = pending["user_id"]

    if not verify_otp(chat_id, code):
        _audit("login_2fa_fail", user_id=user_id)
        db.session.commit()
        return jsonify({"status": "error", "message": "Неверный или просроченный код."}), 401

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"status": "error", "message": "Пользователь не найден."}), 404

    session.permanent = True
    login_user(user, remember=True)
    _audit("login_ok", user_id=user.id, details="2fa=telegram")
    _refresh_tg_username(user)
    db.session.commit()
    return jsonify({
        "status": "success",
        "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin},
    })


@auth_bp.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    user_id = current_user.id if current_user.is_authenticated else None
    _audit("logout", user_id=user_id)
    db.session.commit()
    logout_user()
    return jsonify({"status": "success", "message": "Вы успешно вышли из системы."})


@auth_bp.route("/api/auth/change_password", methods=["POST"])
@login_required
def change_password():
    try:
        req = ChangePasswordRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    if not check_password_hash(current_user.password_hash, req.old_password):
        return jsonify({"status": "error", "message": "Неверный текущий пароль."}), 401

    if req.new_password != req.confirm_password:
        return jsonify({"status": "error", "message": "Новые пароли не совпадают."}), 400

    current_user.password_hash = generate_password_hash(req.new_password)
    _audit("change_password", user_id=current_user.id)
    db.session.commit()
    return jsonify({"status": "success", "message": "Пароль успешно изменён."})
