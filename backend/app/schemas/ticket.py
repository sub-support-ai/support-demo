from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TicketStatusLiteral = Literal[
    "new",
    "pending_user",
    "confirmed",
    "in_progress",
    "resolved",
    "closed",
    "ai_processing",
    "declined",
]

DepartmentLiteral = Literal["IT", "HR", "finance"]
TicketPriorityLiteral = Literal["критический", "высокий", "средний", "низкий"]


class TicketBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    user_priority: int = Field(default=3, ge=1, le=5)


class TicketCreate(TicketBase):
    # user_id НЕ принимается из запроса — берём из JWT (current_user.id).
    # Иначе любой авторизованный пользователь создавал бы тикеты от чужого имени.
    # Пользователь может явно указать отдел; иначе AI классифицирует и
    # подставит через ai_result. При отсутствии подставляем "IT" по умолчанию.
    department: DepartmentLiteral | None = None


class TicketStatusUpdate(BaseModel):
    status: TicketStatusLiteral


class TicketDraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1)
    department: DepartmentLiteral | None = None
    ai_priority: TicketPriorityLiteral | None = None
    steps_tried: str | None = None


class TicketRead(TicketBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    agent_id: int | None = None
    conversation_id: int | None = None
    status: str
    department: str
    ticket_source: str
    steps_tried: str | None = None
    confirmed_by_user: bool

    ai_category: str | None = None
    # ai_priority в модели хранится как строка: "критический"|"высокий"|"средний"|"низкий"
    ai_priority: str | None = None
    ai_confidence: float | None = None
    ai_processed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
