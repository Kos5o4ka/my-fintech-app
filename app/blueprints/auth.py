"""Blueprint аутентификации — вход, выход, смена пароля, 2FA через Telegram."""

import logging

from pydantic import ValidationError
from flask import Blueprint, request, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import limiter
from app.schemas.auth import ChangePasswordRequest
from app.utils import get_client_ip, get_user_agent
from app.services.auth_service import (
    find_user_by_username,
    get_user_by_id,
    verify_password,
    set_password,
    audit_log,
    commit,
)

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


def _audit(action: str, user_id=None, details=None) -> None:
    audit_log(action, user_id, get_client_ip(), get_user_agent(), details)


@auth_bp.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    user = find_user_by_username(username)

    if not user or not verify_password(user, password):
        _audit("login_fail", details={"username": username[:50]})
        commit()
        return jsonify(
            {"status": "error", "message": "Неверный логин или пароль."}
        ), 401

    if user.telegram_chat_id:
        from app.services.telegram_service import generate_otp, create_pending_2fa

        token = create_pending_2fa(user.id, user.telegram_chat_id)
        generate_otp(user.telegram_chat_id)
        _audit("login_2fa_sent", user_id=user.id)
        commit()
        return jsonify(
            {
                "status": "2fa_required",
                "token": token,
                "message": "Код подтверждения отправлен в Telegram.",
            }
        )

    session.permanent = True
    login_user(user, remember=True)
    _audit("login_ok", user_id=user.id)
    from app.services.telegram_service import refresh_tg_username

    refresh_tg_username(user)
    commit()
    return jsonify(
        {
            "status": "success",
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            },
        }
    )


@auth_bp.route("/api/auth/verify_2fa", methods=["POST"])
@limiter.limit("10 per minute")
def verify_2fa():
    data = request.get_json() or {}
    token = data.get("token", "").strip()
    code = data.get("code", "").strip()

    if not token or not code:
        return jsonify({"status": "error", "message": "Токен и код обязательны."}), 400

    from app.services.telegram_service import resolve_pending_2fa, verify_otp

    pending = resolve_pending_2fa(token)
    if not pending:
        return jsonify(
            {
                "status": "error",
                "message": "Сессия истекла. Войдите заново.",
            }
        ), 401

    chat_id = pending["chat_id"]
    user_id = pending["user_id"]

    if not verify_otp(chat_id, code):
        _audit("login_2fa_fail", user_id=user_id)
        commit()
        return jsonify(
            {"status": "error", "message": "Неверный или просроченный код."}
        ), 401

    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"status": "error", "message": "Пользователь не найден."}), 404

    session.permanent = True
    login_user(user, remember=True)
    _audit("login_ok", user_id=user.id, details={"method": "2fa_telegram"})
    from app.services.telegram_service import refresh_tg_username

    refresh_tg_username(user)
    commit()
    return jsonify(
        {
            "status": "success",
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            },
        }
    )


@auth_bp.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    user_id = current_user.id if current_user.is_authenticated else None
    _audit("logout", user_id=user_id)
    commit()
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

    if not verify_password(current_user, req.old_password):
        return jsonify({"status": "error", "message": "Неверный текущий пароль."}), 401

    if req.new_password != req.confirm_password:
        return jsonify(
            {"status": "error", "message": "Новые пароли не совпадают."}
        ), 400

    set_password(current_user, req.new_password)
    _audit("change_password", user_id=current_user.id)
    commit()
    return jsonify({"status": "success", "message": "Пароль успешно изменён."})
