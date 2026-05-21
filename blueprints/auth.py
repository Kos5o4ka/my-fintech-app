from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db, limiter
from models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json() or {}
    user = User.query.filter_by(username=data.get("username", "").strip()).first()
    if not user or not check_password_hash(
        user.password_hash, data.get("password", "").strip()
    ):
        return jsonify({"status": "error", "message": "Неверный логин или пароль."}), 401
    login_user(user, remember=True)
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
    logout_user()
    return jsonify({"status": "success", "message": "Вы успешно вышли из системы."})


@auth_bp.route("/api/auth/change_password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json() or {}
    old_pw = data.get("old_password", "").strip()
    new_pw = data.get("new_password", "").strip()
    confirm_pw = data.get("confirm_password", "").strip()

    if not all([old_pw, new_pw, confirm_pw]):
        return jsonify({"status": "error", "message": "Все поля обязательны."}), 400

    if not check_password_hash(current_user.password_hash, old_pw):
        return jsonify({"status": "error", "message": "Неверный текущий пароль."}), 401

    if new_pw != confirm_pw:
        return jsonify({"status": "error", "message": "Новые пароли не совпадают."}), 400

    if len(new_pw) < 8:
        return jsonify({"status": "error", "message": "Новый пароль должен содержать не менее 8 символов."}), 400

    current_user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({"status": "success", "message": "Пароль успешно изменён."})
