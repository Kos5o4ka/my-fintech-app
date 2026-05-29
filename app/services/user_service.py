"""Сервис пользователей — аватары, email, настройки."""

import logging
import os
import uuid
from typing import Optional

from flask import current_app
from PIL import Image, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import User
from app.constants import ALLOWED_IMAGE_EXTS, MAX_AVATAR_BYTES

logger = logging.getLogger(__name__)

# Максимальный размер аватара после ресайза
_MAX_AVATAR_DIMENSION = 400


def save_avatar(user: User, file: FileStorage) -> str:
    """Валидирует, ре-энкодирует (Pillow) и сохраняет аватар пользователя.

    - Проверяет расширение и MIME-тип
    - Открывает через Pillow (защита от XXE/zip-бомб, стриппинг EXIF)
    - Конвертирует в JPEG, caps to 400×400, сохраняет под UUID-именем
    - Удаляет предыдущий аватар

    Возвращает имя нового файла. Вызывает ValueError при некорректном вводе.
    """
    if not file or file.filename == "":
        raise ValueError("Файл не выбран.")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError("Недопустимый формат файла. Разрешены: PNG, JPG, GIF, WEBP.")

    if not file.mimetype or not file.mimetype.startswith("image"):
        raise ValueError("Файл не является изображением.")

    # Читаем данные для проверки размера
    data = file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("Файл слишком большой. Максимальный размер — 5 МБ.")

    # Открываем через Pillow — проверка, что это реальное изображение + стриппинг EXIF
    try:
        from io import BytesIO

        img = Image.open(BytesIO(data))
        img.verify()  # проверяет целостность файла
        # После verify() нужно переоткрыть (файл "потреблён")
        img = Image.open(BytesIO(data))
    except UnidentifiedImageError:
        raise ValueError("Невозможно распознать формат изображения.")
    except Exception:
        raise ValueError("Повреждённый или неподдерживаемый файл изображения.")

    # Конвертируем в RGB (GIF, PNG с прозрачностью → белый фон)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize: вписываем в квадрат _MAX_AVATAR_DIMENSION × _MAX_AVATAR_DIMENSION
    if img.width > _MAX_AVATAR_DIMENSION or img.height > _MAX_AVATAR_DIMENSION:
        img.thumbnail((_MAX_AVATAR_DIMENSION, _MAX_AVATAR_DIMENSION), Image.LANCZOS)

    # UUID-имя → нет привязки к username, нет path traversal
    new_filename = f"{uuid.uuid4().hex}.jpg"
    avatars_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(avatars_dir, exist_ok=True)

    # Сохраняем как JPEG с удалением EXIF (Pillow не копирует EXIF по умолчанию)
    from io import BytesIO as _IO

    buf = _IO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    buf.seek(0)

    new_path = os.path.join(avatars_dir, new_filename)
    with open(new_path, "wb") as f:
        f.write(buf.read())

    # Удаляем предыдущий аватар (если существует)
    old_filename = user.avatar
    if old_filename:
        old_path = os.path.join(avatars_dir, old_filename)
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError as exc:
            logger.warning("Не удалось удалить старый аватар %s: %s", old_path, exc)

    user.avatar = new_filename
    db.session.commit()
    return new_filename


def delete_avatar(user: User) -> None:
    """Удаляет аватар пользователя с диска и обнуляет user.avatar."""
    if user.avatar:
        avatars_dir = current_app.config["UPLOAD_FOLDER"]
        old_path = os.path.join(avatars_dir, user.avatar)
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError as exc:
            logger.warning("Не удалось удалить аватар %s: %s", old_path, exc)
    user.avatar = None
    db.session.commit()


def update_email_settings(
    user: User,
    email: Optional[str],
    email_notifications: bool,
) -> None:
    """Обновляет email и флаг email-уведомлений пользователя."""
    user.email = email
    user.email_notifications = email_notifications
    db.session.commit()


def update_telegram_settings(user: User, telegram_notifications: bool) -> None:
    """Обновляет флаг Telegram-уведомлений пользователя."""
    user.telegram_notifications = telegram_notifications
    db.session.commit()


def unlink_telegram(user: User) -> None:
    """Отвязывает Telegram от аккаунта пользователя."""
    user.telegram_chat_id = None
    user.telegram_notifications = False
    user.telegram_username = None
    db.session.commit()


def get_profile_stats(user_id: int) -> dict:
    """Счётчики для hero-секции профиля."""
    from app.models import BondPortfolio
    from app.services.portfolio_service import build_portfolio_list

    active = BondPortfolio.query.filter_by(user_id=user_id, is_sold=False).all()
    sold_count = BondPortfolio.query.filter_by(user_id=user_id, is_sold=True).count()
    _, total_value = build_portfolio_list(active)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return {
        "bond_count": len(active),
        "sold_count": sold_count,
        "total_value": round(total_value, 2),
    }


def get_activity_log(
    user_id: int, page: int, per_page: int, category: str | None = None
) -> tuple[list, int]:
    """Возвращает (записи аудита, total). Фильтр по category: account|portfolio."""
    from app.models import AuditLog

    query = AuditLog.query.filter_by(user_id=user_id)
    if category:
        query = query.filter_by(category=category)
    query = query.order_by(AuditLog.created_at.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return logs, total


def update_user_settings(user: User, **kwargs) -> None:
    """Обновляет настройки пользователя (theme, notif_time, etc.)."""
    for key in ("theme", "notif_time", "notif_timezone", "oferta_advance_days"):
        if key in kwargs:
            setattr(user, key, kwargs[key])
    from app.services.audit_service import log_action
    log_action("settings_update", user_id=user.id, category="account")
    db.session.commit()


def enable_2fa(user: User) -> None:
    """Включает 2FA для пользователя."""
    user.two_fa_enabled = True
    db.session.commit()


def disable_2fa(user: User) -> None:
    """Отключает 2FA для пользователя."""
    user.two_fa_enabled = False
    db.session.commit()
