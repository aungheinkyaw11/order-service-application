from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, strict=True)

    @field_validator("symbol")
    @classmethod
    def reject_blank_symbol(cls, value: str) -> str:
        if not value:
            raise ValueError("symbol must not be blank")
        return value


class OrderResponse(BaseModel):
    id: UUID
    symbol: str
    quantity: int
    status: Literal["pending", "filled"]
    created_at: datetime
    updated_at: datetime


class OrderCreatedResponse(BaseModel):
    id: UUID
    status: Literal["pending"] = "pending"
