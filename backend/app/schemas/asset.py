from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Литеральные типы — синхронизированы с app/models/asset.py ASSET_TYPES
AssetTypeLiteral = Literal[
    "laptop",
    "desktop",
    "monitor",
    "printer",
    "phone",
    "network_device",
    "server",
    "peripheral",
    "software",
    "service",
    "other",
]

AssetStatusLiteral = Literal["active", "in_repair", "decommissioned", "lost"]


class AssetCreate(BaseModel):
    asset_type: AssetTypeLiteral
    name: str = Field(..., min_length=1, max_length=200)
    serial_number: str | None = Field(default=None, max_length=100)
    owner_user_id: int | None = None
    office: str | None = Field(default=None, max_length=100)
    status: AssetStatusLiteral = "active"
    notes: str | None = None


class AssetUpdate(BaseModel):
    """Все поля опциональны — PATCH-семантика."""

    asset_type: AssetTypeLiteral | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    serial_number: str | None = Field(default=None, max_length=100)
    owner_user_id: int | None = None
    office: str | None = Field(default=None, max_length=100)
    status: AssetStatusLiteral | None = None
    notes: str | None = None


class AssetSummary(BaseModel):
    """Встраивается в TicketRead — минимальный набор полей для отображения в UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    serial_number: str | None
    status: str
    office: str | None


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    serial_number: str | None
    owner_user_id: int | None
    office: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
