from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AddBondRequest(BaseModel):
    isin: str = Field(..., min_length=12, max_length=12)
    amount: int = Field(..., gt=0)
    buy_price: float = Field(..., gt=0)
    purchase_date: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("isin")
    @classmethod
    def normalize_isin(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("purchase_date", mode="before")
    @classmethod
    def validate_date_format(cls, v: object) -> Optional[str]:
        if not v:
            return None
        try:
            date.fromisoformat(str(v))
        except ValueError:
            raise ValueError("Неверный формат даты. Используйте ГГГГ-ММ-ДД.")
        return str(v)


class SellBondRequest(BaseModel):
    sell_price: Optional[float] = Field(None, gt=0)
    broker_commission: Optional[float] = Field(None, ge=0)
    amount: Optional[int] = Field(None, gt=0)


class ScreenerRequest(BaseModel):
    min_ytm: Optional[float] = None
    max_ytm: Optional[float] = None
    maturity_from: Optional[str] = None
    maturity_to: Optional[str] = None
    # Stage 4 enhancements
    issuer_type: Optional[str] = None  # 'ofz' | 'muni' | 'corp'
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
