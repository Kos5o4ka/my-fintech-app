import logging

from pydantic import ValidationError
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf

from services.user_service import save_avatar, update_email_settings
from schemas.profile import EmailSettingsRequest

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


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


@profile_bp.route("/api/profile/email", methods=["POST"])
@login_required
def update_email():
    try:
        req = EmailSettingsRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        first_error = e.errors()[0]["msg"].replace("Value error, ", "")
        return jsonify({"status": "error", "message": first_error}), 400

    update_email_settings(current_user, req.email, req.email_notifications)
    return jsonify({"status": "success", "message": "Настройки уведомлений сохранены."})
