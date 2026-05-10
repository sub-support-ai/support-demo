"""
Роутер диалогов (conversations).

Эндпоинты:
  POST /api/v1/conversations/
      — создать новый диалог. Привязывается к текущему пользователю из JWT.

  GET  /api/v1/conversations/
      — список диалогов текущего пользователя.

  POST /api/v1/conversations/{id}/messages
      — добавить сообщение в диалог. Принимает текст, возвращает
        сообщение пользователя + ответ AI с метаданными
        (sources, confidence, escalate, requires_escalation).

  GET  /api/v1/conversations/{id}/messages
      — получить всю историю сообщений диалога.

  POST /api/v1/conversations/{id}/escalate
      — 1-click autofill: AI собирает из истории диалога title/body/
        category/priority/steps_tried, создаёт черновик тикета (status=
        "pending_user", confirmed_by_user=False) и переводит диалог
        в status="escalated". Пользователю остаётся один клик "Отправить".
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticleFeedback
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketRead
from app.services.ai_jobs import enqueue_ai_response_job
from app.services.audit import log_event
from app.services.routing import assign_agent
from app.services.ticket_body import (
    build_context_block,
    clean_optional_text,
    clean_text_with_fallback,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ── Схемы запросов/ответов (определены здесь чтобы не плодить файлы) ──────────

class ConversationRead(BaseModel):
    """Данные диалога в ответе."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class MessageCreate(BaseModel):
    """Тело запроса при отправке сообщения."""
    content: str


class SourceRead(BaseModel):
    """Источник из RAG, на который опирался AI при ответе."""
    title: str
    url: str | None = None
    article_id: int | None = None
    chunk_id: int | None = None
    snippet: str | None = None
    retrieval: str | None = None
    score: float | None = None
    decision: str | None = None


class MessageRead(BaseModel):
    """Данные одного сообщения в ответе.

    Для AI-сообщений дополнительно отдаём:
      - sources              — что AI цитировал;
      - ai_confidence        — насколько модель уверена;
      - ai_escalate          — модель сама попросила эскалацию;
      - requires_escalation  — итоговый флаг "красной зоны": True, если
                               фоновая обработка решила, что нужна эскалация.
                               Клиент использует этот
                               флаг, чтобы НЕ показывать ответ как
                               окончательный, а предложить 1-click
                               эскалацию через POST /escalate.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str       # "user" или "ai"
    content: str
    sources: list[SourceRead] | None = None
    ai_confidence: float | None = None
    ai_escalate: bool | None = None
    requires_escalation: bool | None = None


class AddMessageResponse(BaseModel):
    """Ответ на отправку сообщения в диалог.

    AI-ответ генерируется асинхронно через job-очередь. HTTP-запрос возвращает
    управление сразу после сохранения user_message — без ожидания LLM. Клиент
    получает:

      user_message       — только что сохранённое сообщение пользователя.
      conversation_status — "ai_processing" (модель ещё работает) или "active"
                           (если по какой-то причине AI-job не создалась —
                           деградация, но не блокировка).
      ai_job_id          — id задачи в очереди ai_jobs. Опционально использовать
                           для GET /jobs/{id}, чтобы наблюдать прогресс. Когда
                           job в статусе "done"/"failed" — AI-ответ уже в
                           GET /messages.
      poll_hint          — путь, по которому клиент должен поллить, чтобы
                           забрать AI-ответ. Указан явно, чтобы фронт не
                           догадывался об URL'е.

    Рекомендованный паттерн на клиенте:
      1. POST /messages → получить ai_job_id, conversation_status="ai_processing".
      2. Поллить GET /messages раз в ~1 сек, пока conversation.status не станет
         "active" (т.е. появится AI-сообщение). Таймаут на клиенте — разумный
         (60 сек), после чего показать «AI не успел, попробуйте ещё раз».
    """

    user_message: "MessageRead"
    conversation_status: str
    ai_job_id: int | None = None
    poll_hint: str


class EscalationContext(BaseModel):
    requester_name: str = Field(min_length=1, max_length=100)
    requester_email: EmailStr
    office: str = Field(min_length=1, max_length=100)
    affected_item: str = Field(min_length=1, max_length=150)
    request_type: str | None = Field(default=None, max_length=60)
    request_details: str | None = Field(default=None, max_length=2000)

    @field_validator("requester_name", "office", "affected_item")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value

    @field_validator("requester_email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("request_type", "request_details")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class EscalatePayload(BaseModel):
    context: EscalationContext


# ── POST /conversations/ — создать диалог ─────────────────────────────────────

@router.post(
    "/",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Начать новый диалог",
    description="Создаёт новый диалог для авторизованного пользователя. "
                "user_id берётся из JWT токена автоматически.",
)
async def create_conversation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = Conversation(
        user_id=current_user.id,
        status="active",
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


# ── GET /conversations/ — список диалогов текущего пользователя ───────────────

@router.get(
    "/",
    response_model=list[ConversationRead],
    summary="Список диалогов пользователя",
    description="Возвращает все диалоги авторизованного пользователя.",
)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    return result.scalars().all()


# ── Хелпер: загрузка диалога с проверкой доступа ──────────────────────────────

async def _get_conversation_for_user(
    conversation_id: int,
    db: AsyncSession,
    current_user: User,
) -> Conversation:
    """Загрузить диалог и убедиться, что текущий пользователь — его владелец.

    404 (а не 403) при отсутствии доступа: не палим существование ID
    перебором — та же логика, что в get_ticket_for_user в tickets.py.
    """
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if conversation is None or conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Диалог не найден",
        )
    return conversation


# ── POST /conversations/{id}/messages — добавить сообщение ────────────────────

@router.post(
    "/{conversation_id}/messages",
    response_model=AddMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Отправить сообщение в диалог",
    description=(
        "Сохраняет сообщение пользователя и ставит задачу на генерацию "
        "AI-ответа в очередь (ai_jobs). HTTP-запрос возвращается сразу — "
        "AI-ответ обрабатывается фоновым воркером.\n\n"
        "Клиент получает `ai_job_id`, `conversation_status` и `poll_hint`. "
        "Чтобы получить AI-ответ, клиент должен поллить GET /messages пока "
        "не появится сообщение с role=ai (или conversation.status снова "
        "станет 'active')."
    ),
)
async def add_message(
    conversation_id: int,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AddMessageResponse:
    conversation = await _get_conversation_for_user(
        conversation_id, db, current_user
    )

    if conversation.status == "escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Диалог уже эскалирован в тикет. Подтвердите черновик "
                "или начните новый диалог."
            ),
        )
    if conversation.status == "ai_processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Дождитесь ответа перед созданием черновика.",
        )

    # PII-маскировка контента до сохранения: содержимое сообщений живёт долго
    # и попадает в RAG / эскалацию / outbound-логи. Здесь же — единственное
    # место, где user-input приходит в чат, поэтому маскировка тут.
    from app.services.pii import mask_pii  # ленивый импорт — pii нужен только здесь

    # Сохраняем сообщение пользователя (с маскировкой)
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=mask_pii(payload.content),
    )
    db.add(user_message)
    await db.flush()
    await db.refresh(user_message)

    conversation.status = "ai_processing"
    job = await enqueue_ai_response_job(db, conversation_id)
    await db.flush()

    return AddMessageResponse(
        user_message=MessageRead.model_validate(user_message),
        conversation_status=conversation.status,
        ai_job_id=job.id,
        poll_hint=f"/api/v1/conversations/{conversation_id}/messages",
    )


# ── GET /conversations/{id}/messages — история сообщений ──────────────────────

@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageRead],
    summary="История сообщений диалога",
    description="Возвращает все сообщения диалога в хронологическом порядке.",
)
async def get_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_conversation_for_user(conversation_id, db, current_user)

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return result.scalars().all()


# ── POST /conversations/{id}/escalate — 1-click autofill ─────────────────────

class EscalateResponse(BaseModel):
    """Ответ при эскалации диалога в тикет.

    ticket — созданный pre-filled тикет (status=pending_user,
             confirmed_by_user=False). Пользователь видит черновик и
             одним кликом подтверждает отправку.
    """
    ticket: TicketRead
    conversation_id: int


@router.post(
    "/{conversation_id}/escalate",
    response_model=EscalateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="1-click эскалация диалога в тикет",
    description=(
        "AI читает историю диалога, классифицирует проблему "
        "(category/priority), извлекает что пользователь уже пробовал "
        "(steps_tried) и создаёт черновик тикета с conversation_id. "
        "Тикет создаётся со status=pending_user и confirmed_by_user=False — "
        "пользователь видит pre-filled форму и одним кликом подтверждает. "
        "Диалог переходит в status=escalated."
    ),
)
async def escalate_conversation(
    conversation_id: int,
    request: Request,
    payload: EscalatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ai_classifier import classify_ticket
    from datetime import datetime, timezone
    from app.config import get_settings

    conversation = await _get_conversation_for_user(
        conversation_id, db, current_user
    )
    if conversation.status == "escalated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Диалог уже эскалирован в тикет. Подтвердите черновик "
                "или начните новый диалог."
            ),
        )

    # Подтягиваем все сообщения диалога — без лимита: для классификации
    # нам нужен максимум контекста (диалог короткий, обычно 5-15 сообщений).
    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    messages = list(msg_result.scalars().all())

    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя эскалировать пустой диалог",
        )

    # Собираем title и body для классификатора:
    #   title — первое сообщение пользователя (обычно это и есть суть);
    #   body  — вся история одной строкой "роль: текст".
    user_msgs = [m for m in messages if m.role == "user"]
    if not user_msgs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В диалоге нет сообщений пользователя — нечего эскалировать",
        )

    title = user_msgs[0].content[:255]  # Ticket.title VARCHAR(255)
    classify_body = "\n\n".join(m.content for m in user_msgs)
    body_parts = []
    for m in messages:
        prefix = "Пользователь" if m.role == "user" else "AI"
        body_parts.append(f"{prefix}: {m.content}")

    # Классифицируем
    ai_result = await classify_ticket(
        ticket_id=None,
        title=title,
        body=classify_body,
    )

    from app.constants.departments import DEPARTMENTS_SET

    department = ai_result.get("department") or "IT"
    # AI-классификатор обучен на 7-отдельной таксономии (см.
    # app/constants/departments.py), но иногда возвращает "other" или новый,
    # не предусмотренный класс — приземляем в "IT" как безопасный default
    # (а не теряем тикет в 422).
    if department not in DEPARTMENTS_SET:
        department = "IT"

    # Извлекаем steps_tried из истории через LLM — `services/ai_extract.py`.
    # При недоступности AI-сервиса автоматически fallback'нется на
    # keyword-эвристику (то же поведение, что было раньше, но как
    # последний рубеж — а не основной способ).
    from app.services.ai_extract import extract_steps_tried
    steps_tried = await extract_steps_tried(messages)
    requester_name = clean_text_with_fallback(
        payload.context.requester_name,
        current_user.username,
    )
    requester_email = clean_text_with_fallback(
        payload.context.requester_email,
        current_user.email,
    )
    office = clean_optional_text(payload.context.office)
    affected_item = clean_optional_text(payload.context.affected_item)
    request_type = clean_optional_text(payload.context.request_type)
    request_details = clean_optional_text(payload.context.request_details)

    form_lines: list[str] = []
    if request_type:
        form_lines.append(f"Тип запроса: {request_type}")
    if request_details:
        form_lines.append(f"Уточнение формы: {request_details}")

    body = build_context_block(
        requester_name=requester_name,
        requester_email=requester_email,
        office=office,
        affected_item=affected_item,
        creator_name=current_user.username,
        creator_email=current_user.email,
    )
    if form_lines:
        body += "\n\nФорма запроса:\n" + "\n".join(form_lines)
    body += "\n\n" + "\n\n".join(body_parts)

    settings = get_settings()
    ticket = Ticket(
        user_id=current_user.id,
        conversation_id=conversation_id,
        title=title,
        body=body,
        requester_name=requester_name,
        requester_email=requester_email,
        office=office,
        affected_item=affected_item,
        request_type=request_type,
        request_details=request_details,
        steps_tried=steps_tried,
        # Пользователь не выставлял приоритет вручную — берём середину.
        # ai_priority используется в роутинге, user_priority остаётся 3.
        user_priority=3,
        department=department,
        status="pending_user",  # ждёт подтверждения "одним кликом"
        ticket_source="ai_generated",
        confirmed_by_user=False,
        ai_category=ai_result.get("category"),
        ai_priority=ai_result.get("priority"),
        ai_confidence=ai_result.get("confidence"),
        ai_processed_at=datetime.now(timezone.utc),
    )
    db.add(ticket)
    await db.flush()

    feedback_result = await db.execute(
        select(KnowledgeArticleFeedback)
        .where(
            KnowledgeArticleFeedback.conversation_id == conversation_id,
            KnowledgeArticleFeedback.escalated_ticket_id.is_(None),
        )
        .order_by(KnowledgeArticleFeedback.created_at.desc(), KnowledgeArticleFeedback.id.desc())
    )
    for feedback in feedback_result.scalars().all():
        feedback.escalated_ticket_id = ticket.id

    # Назначаем агента сразу — даже на pending_user тикет, чтобы старший
    # уже мог посмотреть на черновик и при подтверждении взять в работу.
    await assign_agent(db, ticket)
    await db.flush()

    # Логируем решение AI — outcome="escalated_ai_ticket": AI сам предложил
    # тикет, пользователь ещё не подтвердил, но факт эскалации зафиксирован.
    db.add(AILog(
        ticket_id=ticket.id,
        conversation_id=conversation_id,
        model_version=(
            ai_result.get("model_version")
            or settings.AI_MODEL_VERSION_FALLBACK
        ),
        predicted_category=ai_result.get("category") or "неизвестно",
        predicted_priority=ai_result.get("priority") or "средний",
        confidence_score=float(ai_result.get("confidence") or 0.0),
        routed_to_agent_id=ticket.agent_id,
        ai_response_draft=ai_result.get("draft_response"),
        ai_response_time_ms=ai_result.get("response_time_ms"),
        outcome="escalated_ai_ticket",
    ))

    # Переводим диалог в "escalated" — UI скрывает поле ввода и
    # показывает ссылку на созданный тикет.
    conversation.status = "escalated"

    await db.refresh(ticket)

    await log_event(
        db,
        action="conversation.escalate",
        user_id=current_user.id,
        target_type="conversation",
        target_id=conversation_id,
        request=request,
        details={
            "ticket_id": ticket.id,
            "department": ticket.department,
            "ai_confidence": ticket.ai_confidence,
            "office": ticket.office,
            "affected_item": ticket.affected_item,
            "request_type": ticket.request_type,
        },
    )

    return EscalateResponse(
        ticket=TicketRead.model_validate(ticket),
        conversation_id=conversation_id,
    )


# ── Внутренние функции ────────────────────────────────────────────────────────
#
# _extract_steps_tried переехал в app/services/ai_extract.py (LLM + heuristic
# fallback). Здесь больше нет приватных хелперов — всё живёт в сервисах.
