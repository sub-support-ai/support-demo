from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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

# Статусы, которые оператор может выставить вручную.
# "new" / "pending_user" / "ai_processing" / "declined" никогда не проходят
# через state-machine агента — оставлять их в публичной схеме значит
# давать ложное ощущение, что они работают (они упадут с 409 из-за
# ALLOWED_OPERATOR_TRANSITIONS).
OperatorStatusLiteral = Literal["confirmed", "in_progress", "resolved", "closed"]

DepartmentLiteral = Literal["IT", "HR", "finance"]
EditableTicketPriorityLiteral = Literal["высокий", "средний", "низкий"]


class TicketBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10_000)
    user_priority: int = Field(default=3, ge=2, le=5)


class TicketCreate(TicketBase):
    # user_id НЕ принимается из запроса — берём из JWT (current_user.id).
    # Иначе любой авторизованный пользователь создавал бы тикеты от чужого имени.
    # Пользователь может явно указать отдел; иначе AI классифицирует и
    # подставит через ai_result. При отсутствии подставляем "IT" по умолчанию.
    department: DepartmentLiteral | None = None
    office: str | None = Field(default=None, max_length=100)
    affected_item: str | None = Field(default=None, max_length=150)
    request_type: str | None = Field(default=None, max_length=60)
    request_details: str | None = Field(default=None, max_length=2000)


class TicketStatusUpdate(BaseModel):
    status: OperatorStatusLiteral


class TicketDraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=10_000)
    department: DepartmentLiteral | None = None
    ai_priority: EditableTicketPriorityLiteral | None = None
    requester_name: str | None = Field(default=None, max_length=100)
    requester_email: EmailStr | None = None
    steps_tried: str | None = Field(default=None, max_length=5_000)
    office: str | None = Field(default=None, max_length=100)
    affected_item: str | None = Field(default=None, max_length=150)
    request_type: str | None = Field(default=None, max_length=60)
    request_details: str | None = Field(default=None, max_length=2000)


class TicketCommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    internal: bool = True


class TicketCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_id: int | None = None
    author_username: str
    author_role: str
    content: str
    internal: bool
    created_at: datetime


class TicketFeedbackPayload(BaseModel):
    feedback: Literal["helped", "not_helped"]
    reopen: bool = False


class TicketReroutePayload(BaseModel):
    """Перенаправление тикета в другой отдел агентом."""
    department: DepartmentLiteral
    reason: str = Field(min_length=1, max_length=500, description="Причина перенаправления")


class TicketRatingCreate(BaseModel):
    """Оценка тикета пользователем (CSAT 1–5 звёзд)."""
    rating: int = Field(ge=1, le=5, description="Оценка от 1 до 5")
    comment: str | None = Field(default=None, max_length=1000)


class TicketRatingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    user_id: int
    rating: int
    comment: str | None = None
    created_at: datetime


class TicketRead(TicketBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    agent_id: int | None = None
    conversation_id: int | None = None
    status: str
    department: str
    ticket_source: str
    requester_name: str | None = None
    requester_email: str | None = None
    office: str | None = None
    affected_item: str | None = None
    request_type: str | None = None
    request_details: str | None = None
    steps_tried: str | None = None
    confirmed_by_user: bool
    sla_started_at: datetime | None = None
    sla_deadline_at: datetime | None = None
    sla_escalated_at: datetime | None = None
    sla_escalation_count: int = 0
    is_sla_breached: bool = False
    reopen_count: int = 0

    ai_category: str | None = None
    # ai_priority в модели хранится как строка: "критический"|"высокий"|"средний"|"низкий"
    ai_priority: str | None = None
    ai_confidence: float | None = None
    ai_processed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    first_response_at: datetime | None = None
