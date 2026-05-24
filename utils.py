"""Общие утилиты — переиспользуются в нескольких blueprints."""
from flask import request


def get_client_ip() -> str:
    """Возвращает IP клиента с учётом X-Forwarded-For (за reverse proxy)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def get_user_agent() -> str:
    """Возвращает User-Agent, обрезанный до 255 символов."""
    return (request.headers.get("User-Agent") or "")[:255]
