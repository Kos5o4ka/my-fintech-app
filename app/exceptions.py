"""Доменные исключения InvestTrack.

Service-слой бросает эти исключения, blueprint-слой их ловит и переводит в HTTP.
Это убирает "magic dicts" вида ``{"status": "error", "message": ...}`` из сервисов
и даёт типобезопасный контракт между слоями.

Иерархия:

    DomainError
    ├── NotFoundError          → HTTP 404
    ├── DomainValidationError  → HTTP 400 (бизнес-правила, не Pydantic)
    ├── AccessDeniedError      → HTTP 403
    ├── ConflictError          → HTTP 409
    └── ExternalServiceError   → HTTP 502
        └── AuthError          → HTTP 401 (просрочен токен и т.п.)

Использование в blueprint:

    try:
        result = service.do_thing()
    except DomainError as exc:
        return jsonify(exc.to_dict()), exc.http_status
"""

from __future__ import annotations


class DomainError(Exception):
    """Базовое исключение бизнес-слоя."""

    http_status: int = 400
    code: str = "domain_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        payload = {"status": "error", "code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(DomainError):
    http_status = 404
    code = "not_found"


class DomainValidationError(DomainError):
    """Нарушение бизнес-правила (не путать с Pydantic ValidationError)."""

    http_status = 400
    code = "validation_error"


class AccessDeniedError(DomainError):
    http_status = 403
    code = "access_denied"


class ConflictError(DomainError):
    """Состояние гонок/уникальности нарушено."""

    http_status = 409
    code = "conflict"


class ExternalServiceError(DomainError):
    """Внешний сервис (MOEX, ЦБ РФ, T-Invest, Telegram) недоступен или вернул ошибку."""

    http_status = 502
    code = "external_service_error"


class AuthError(ExternalServiceError):
    http_status = 401
    code = "auth_error"
