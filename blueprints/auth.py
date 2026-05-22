import logging

from pydantic import ValidationError
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter
from models import User
from schemas.auth import ChangePasswordRequest
from constants import MIN_PASSWORD_LEN

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json() or {}
    user = User.query.filter_by(username=data.get("username", "").strip()).first()
    if not user or not check_password_hash(user.password_hash, data.get("password", "").strip()):
        return jsonify({"status": "error", "message": "Неверный логин или пароль."}), 401
    login_user(user, remember=True)
    return jsonify({"status": "success", "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin}})


@auth_bp.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
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
    db.session.commit()
    return jsonify({"status": "success", "message": "Пароль успешно изменён."})
