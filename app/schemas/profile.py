from pydantic import BaseModel, Field, field_validator


class SettingsUpdate(BaseModel):
    theme: str = "system"
    notif_time: str = "09:00"
    notif_timezone: str = "Europe/Moscow"
    oferta_advance_days: int = 14

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, v: str) -> str:
        if v not in ("system", "light", "dark"):
            return "system"
        return v

    @field_validator("notif_time")
    @classmethod
    def validate_notif_time(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            return "09:00"
        return v

    @field_validator("notif_timezone")
    @classmethod
    def validate_notif_timezone(cls, v: str) -> str:
        if len(v) > 64:
            return "Europe/Moscow"
        return v

    @field_validator("oferta_advance_days")
    @classmethod
    def validate_oferta_days(cls, v: int) -> int:
        if v not in (0, 7, 14, 30):
            return 14
        return v


class Disable2FARequest(BaseModel):
    method: str = Field(..., pattern=r"^(otp|password)$")
    code: str | None = None
    password: str | None = None


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = Field(default=False, alias="all")
