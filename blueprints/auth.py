from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user
from werkzeug.security import check_password_hash
from extensions import limiter
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
