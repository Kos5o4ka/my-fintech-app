import logging
import os

import imghdr
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

from extensions import db

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profile", __name__)


def _allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile_page():
    if request.method == "POST":
        if "avatar" not in request.files:
            return jsonify({"status": "error", "message": "Нет файла."}), 400

        file = request.files["avatar"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "Файл не выбран."}), 400

        if not _allowed_file(file.filename):
            return (
                jsonify({"status": "error", "message": "Недопустимый формат файла. Разрешены: PNG, JPG, GIF, WEBP."}),
                400,
            )

        if not file.mimetype or not file.mimetype.startswith("image"):
            return jsonify({"status": "error", "message": "Файл не является изображением."}), 400

        header = file.read(512)
        file.seek(0)
        if imghdr.what(None, header) is None:
            return jsonify({"status": "error", "message": "Невозможно распознать формат изображения."}), 400

        filename = secure_filename(file.filename)
        unique_filename = f"user_{current_user.id}_{filename}"
        avatars_dir = current_app.config["UPLOAD_FOLDER"]
        os.makedirs(avatars_dir, exist_ok=True)
        file.save(os.path.join(avatars_dir, unique_filename))

        current_user.avatar = unique_filename
        db.session.commit()

    return render_template("profile.html", csrf_token=generate_csrf())


@profile_bp.route("/api/profile/email", methods=["POST"])
@login_required
def update_email():
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    notifications = bool(data.get("email_notifications", False))
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        return jsonify({"status": "error", "message": "Неверный формат email."}), 400
    current_user.email = email if email else None
    current_user.email_notifications = notifications
    db.session.commit()
    return jsonify({"status": "success", "message": "Настройки уведомлений сохранены."})
