"""Сервис пользователей — аватары, email, настройки."""
import logging
import os
from typing import Optional

import imghdr
from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from extensions import db
from models import User
from constants import ALLOWED_IMAGE_EXTS

logger = logging.getLogger(__name__)


def save_avatar(user: User, file: FileStorage) -> str:
    """Валидирует и сохраняет аватар пользователя.

    Возвращает имя файла. Вызывает ValueError при некорректном вводе.
    """
    if not file or file.filename == "":
        raise ValueError("Файл не выбран.")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError("Недопустимый формат файла. Разрешены: PNG, JPG, GIF, WEBP.")

    if not file.mimetype or not file.mimetype.startswith("image"):
        raise ValueError("Файл не является изображением.")

    header = file.read(512)
    file.seek(0)
    if imghdr.what(None, header) is None:
        raise ValueError("Невозможно распознать формат изображения.")

    filename = secure_filename(file.filename)
    unique_filename = f"user_{user.id}_{filename}"
    avatars_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(avatars_dir, exist_ok=True)
    file.save(os.path.join(avatars_dir, unique_filename))

    user.avatar = unique_filename
    db.session.commit()
    return unique_filename


def update_email_settings(
    user: User,
    email: Optional[str],
    email_notifications: bool,
) -> None:
    """Обновляет email и флаг email-уведомлений пользователя."""
    user.email = email
    user.email_notifications = email_notifications
    db.session.commit()
