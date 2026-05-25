import logging
import re

from flask import Blueprint, request, jsonify, abort, render_template
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from extensions import db, limiter
from models import User, AuditLog
from constants import MIN_PASSWORD_LEN
from utils import get_client_ip, get_user_agent

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
def get_all_users():
    if not current_user.is_admin:
        abort(403)
    users = User.query.all()
    return jsonify(
        [{"id": u.id, "username": u.username, "is_admin": u.is_admin} for u in users]
    )


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

    if User.query.filter_by(username=username).first():
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Пользователь с таким логином уже существует.",
                }
            ),
            400,
        )

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        is_admin=is_admin,
    )
    db.session.add(new_user)
    db.session.commit()
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
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)

    user_to_delete = db.session.get(User, user_id)
    if user_to_delete is None:
        abort(404)
    if user_to_delete.id == current_user.id:
        return jsonify(
            {"status": "error", "message": "Вы не можете удалить сами себя."}
        ), 400

    db.session.delete(user_to_delete)
    db.session.commit()
    return jsonify(
        {
            "status": "success",
            "message": f"Пользователь {user_to_delete.username} удален.",
        }
    )


@admin_bp.route("/api/admin/change_password/<int:user_id>", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def admin_change_password(user_id):
    if not current_user.is_admin:
        abort(403)

    target = db.session.get(User, user_id)
    if target is None:
        abort(404)

    if target.username == "root":
        return jsonify(
            {"status": "error", "message": "Пароль root-пользователя изменить нельзя."}
        ), 403

    data = request.get_json() or {}
    new_password = data.get("new_password", "").strip()

    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        return jsonify(
            {
                "status": "error",
                "message": f"Пароль должен содержать минимум {MIN_PASSWORD_LEN} символов.",
            }
        ), 400

    target.password_hash = generate_password_hash(new_password)
    log = AuditLog(
        action="admin_change_password",
        user_id=current_user.id,
        ip_address=get_client_ip(),
        user_agent=get_user_agent(),
        details=f"target_user_id={target.id} target_username={target.username}",
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(
        {
            "status": "success",
            "message": f"Пароль пользователя «{target.username}» успешно изменён.",
        }
    )
