"""Blueprint администрирования — тонкий HTTP-слой."""

import logging
import re

from flask import Blueprint, request, jsonify, abort, render_template
from flask_login import login_required, current_user

from app.extensions import limiter
from app.constants import MIN_PASSWORD_LEN
from app.utils import get_client_ip, get_user_agent
from app.services.admin_service import (
    get_all_users,
    find_user_by_username,
    create_user,
    delete_user,
    change_user_password,
)

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@login_required
def admin_page():
    if not current_user.is_admin:
        abort(403)
    return render_template("admin.html", active_page="admin")


@admin_bp.route("/api/admin/users", methods=["GET"])
@login_required
def get_all_users_route():
    if not current_user.is_admin:
        abort(403)
    return jsonify(get_all_users())


@admin_bp.route("/api/admin/add_user", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def admin_add_user():
    if not current_user.is_admin:
        abort(403)

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    is_admin = data.get("is_admin", False)

    if not username or not password:
        return jsonify(
            {"status": "error", "message": "Логин и пароль обязательны."}
        ), 400

    if not re.fullmatch(r"[A-Za-z0-9]{3,20}", username):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Логин должен содержать только латинские буквы и цифры, 3–20 символов.",
                }
            ),
            400,
        )

    if find_user_by_username(username):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Пользователь с таким логином уже существует.",
                }
            ),
            400,
        )

    new_user = create_user(username, password, is_admin)
    return (
        jsonify(
            {
                "status": "success",
                "message": f"Пользователь {username} успешно создан!",
                "user_id": new_user.id,
            }
        ),
        201,
    )


@admin_bp.route("/api/admin/delete_user/<int:user_id>", methods=["DELETE"])
@login_required
def delete_user_route(user_id):
    if not current_user.is_admin:
        abort(403)

    if user_id == current_user.id:
        return jsonify(
            {"status": "error", "message": "Вы не можете удалить сами себя."}
        ), 400

    user = delete_user(user_id)
    if user is None:
        abort(404)
    return jsonify(
        {
            "status": "success",
            "message": f"Пользователь {user.username} удален.",
        }
    )


@admin_bp.route("/api/admin/change_password/<int:user_id>", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def admin_change_password(user_id):
    if not current_user.is_admin:
        abort(403)

    data = request.get_json() or {}
    new_password = data.get("new_password", "").strip()

    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        return jsonify(
            {
                "status": "error",
                "message": f"Пароль должен содержать минимум {MIN_PASSWORD_LEN} символов.",
            }
        ), 400

    from app.services.admin_service import get_user_by_id

    target = get_user_by_id(user_id)
    if target is None:
        abort(404)

    if target.username == "root":
        return jsonify(
            {"status": "error", "message": "Пароль root-пользователя изменить нельзя."}
        ), 403

    change_user_password(
        user_id, new_password, current_user.id, get_client_ip(), get_user_agent()
    )
    return jsonify(
        {
            "status": "success",
            "message": f"Пароль пользователя «{target.username}» успешно изменён.",
        }
    )
