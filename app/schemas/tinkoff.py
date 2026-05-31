"""Pydantic v2 схемы для эндпоинтов T-Invest интеграции."""

from pydantic import BaseModel, Field, field_validator


class TinkoffTokenIn(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    sandbox: bool = False

    @field_validator("token")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        # Токены T-Invest по контракту начинаются с `t.`
        if not v.startswith("t."):
            raise ValueError("Токен должен начинаться с 't.'")
        return v


class TinkoffSyncIn(BaseModel):
    account_id: str | None = Field(default=None, max_length=50)
    sandbox: bool = False
