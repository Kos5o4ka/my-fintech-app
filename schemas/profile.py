from typing import Optional

from pydantic import BaseModel, field_validator


class EmailSettingsRequest(BaseModel):
    email: Optional[str] = None
    email_notifications: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, v: object) -> Optional[str]:
        if not v:
            return None
        v = str(v).strip()
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("Неверный формат email.")
        return v or None
