from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.asset import AssetSummary

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

TicketQueueLiteral = Literal[
    "active",
    "new",
    "in_progress",
    "overdue",
    "unassigned",
    "pending_user",
    "resolved",
    "all",
]

# Статусы, которые оператор может выставить вручную.
# "new" / "pending_user" / "ai_processing" / "declined" никогда не проходят
# через state-machine агента — оставлять их в публичной схеме значит
# давать ложное ощущение, что они работают (они упадут с 409 из-за
# ALLOWED_OPERATOR_TRANSITIONS).
OperatorStatusLiteral = Literal["confirmed", "in_progress", "resolved", "closed"]

# Источник истины для списка отделов — app/constants/departments.py.
# Импортим Literal оттуда, чтобы Pydantic-валидация была согласована с
# CHECK-constraint в БД и AI-классификатором.
from app.constants.departments import DepartmentLiteral  # noqa: E402

EditableTicketPriorityLiteral = Literal["высокий", "средний", "низкий"]

TicketKindLiteral = Literal["incident", "service_request", "access_request", "security_incident"]


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
    # CMDB: ID актива из таблицы assets; дополняет affected_item, не заменяет
    asset_id: int | None = None
    request_type: str | None = Field(default=None, max_length=60)
    request_details: str | None = Field(default=None, max_length=2000)
    ticket_kind: TicketKindLiteral = "incident"


class TicketStatusUpdate(BaseModel):
    status: OperatorStatusLiteral


# ── Bulk-операции ────────────────────────────────────────────────────────────


# Допустимые действия в bulk-операции. Сейчас только переходы статуса —
# самое частое массовое действие у оператора («закрыть все вчерашние
# resolved», «взять в работу всю новую очередь»).
BulkActionLiteral = Literal["in_progress", "resolved", "closed"]


class TicketBulkRequest(BaseModel):
    """Массовое изменение статуса тикетов с защитой от рискованных операций."""

    ticket_ids: list[int] = Field(min_length=1, max_length=100)
    action: BulkActionLiteral
    # force=True позволяет admin'у обойти защиту (например, явно закрыть
    # переоткрытые тикеты пакетом). Agent'у недоступно — иначе защита
    # обходится случайным кликом.
    force: bool = False


class TicketBulkRejection(BaseModel):
    """Один отклонённый тикет — почему bulk не применился к нему."""

    ticket_id: int
    code: str  # машинный: has_reopens, low_csat, has_unread_user_msg, wrong_status, not_found, not_authorized
    reason: str  # человекочитаемый


class TicketBulkResponse(BaseModel):
    """Результат bulk-операции.

    Дизайн: partial-success. Применяем что можем, остальное возвращаем
    с указанием причины — UI показывает «Закрыто X · ⚠ Y требуют проверки».
    """

    requested_count: int
    applied_count: int
    applied_ticket_ids: list[int]
    rejected: list[TicketBulkRejection]


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
    asset_id: int | None = None
    request_type: str | None = Field(default=None, max_length=60)
    request_details: str | None = Field(default=None, max_length=2000)
    ticket_kind: TicketKindLiteral | None = None


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


class SimilarTicket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    department: str
    ai_category: str | None = None
    resolved_at: datetime | None = None


class TicketAiAssist(BaseModel):
    summary: str | None = None
    ai_response_draft: str | None = None
    similar_tickets: list[SimilarTicket] = []


class TicketRead(TicketBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    agent_id: int | None = None
    conversation_id: int | None = None
    asset_id: int | None = None
    asset: AssetSummary | None = None
    status: str
    department: str
    ticket_source: str
    ticket_kind: str
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


class TicketSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    department: str
    ai_priority: str | None
    ai_category: str | None
    requester_name: str | None
    requester_email: str | None
    created_at: datetime
    resolved_at: datetime | None
    sla_deadline_at: datetime | None
    is_sla_breached: bool
    reopen_count: int
    agent_id: int | None
    asset_id: int | None = None
    ticket_kind: str | None = None
