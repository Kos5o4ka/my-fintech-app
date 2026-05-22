from pydantic import BaseModel, Field
from constants import MIN_PASSWORD_LEN


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LEN)
    confirm_password: str = Field(..., min_length=1)
