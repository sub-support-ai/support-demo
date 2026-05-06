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
from typing import Any

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

# ── Бизнес-константы ──────────────────────────────────────────────────────────
#
# RED_ZONE_THRESHOLD: уверенность модели, ниже которой ответ AI считается
# ненадёжным и НЕ показывается пользователю как окончательный — клиент
# обязан предложить эскалацию на агента (1-click тикет).
#
# Значение 0.6 задаётся планом проекта ("точка поддержки", iteration 1).
# Это НЕ та же 0.8, что в routing.py: там порог решает, какому агенту
# дать тикет (свободному vs старшему); здесь — показывать ли draft вообще.
RED_ZONE_THRESHOLD = 0.6

# Сколько последних сообщений отдавать в AI как контекст. Защита от
# "разрастания контекста": длинный диалог → большой prompt → таймауты,
# деньги, ухудшение качества (модель путается). 20 — компромисс между
# сохранением темы и стоимостью.
MAX_HISTORY_MESSAGES = 20

SUPPORT_DRAFT_INTENT_TERMS = (
    "тикет", "заявк", "черновик", "обращен", "запрос", "техподдерж", "тех поддерж",
    "специалист", "саппорт", "support",
)
SUPPORT_DRAFT_ACTION_TERMS = (
    "созда", "сформир", "оформ", "заведи", "завести", "отправ", "эскал",
)
URGENT_TERMS = (
    "срочно", "авар", "критич", "опасн", "горит", "дым", "искр",
)
PHYSICAL_INCIDENT_TERMS = (
    "провод", "кабел", "розетк", "удлинител", "электр", "питани", "сломал",
    "сломался", "порвал", "порвался", "оторвал", "поврежд",
)


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
    score: float | None = None
    decision: str | None = None


class MessageRead(BaseModel):
    """Данные одного сообщения в ответе.

    Для AI-сообщений дополнительно отдаём:
      - sources              — что AI цитировал;
      - ai_confidence        — насколько модель уверена;
      - ai_escalate          — модель сама попросила эскалацию;
      - requires_escalation  — итоговый флаг "красной зоны": True, если
                               уверенность < RED_ZONE_THRESHOLD или AI
                               выставил escalate. Клиент использует этот
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


class EscalationContext(BaseModel):
    requester_name: str = Field(min_length=1, max_length=100)
    requester_email: EmailStr
    office: str = Field(min_length=1, max_length=100)
    affected_item: str = Field(min_length=1, max_length=150)
    request_type: str | None = Field(default=None, max_length=50)
    request_details: str | None = None

    @field_validator("requester_name", "office", "affected_item")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value

    @field_validator("request_type", "request_details")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("requester_email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


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
    response_model=list[MessageRead],
    status_code=status.HTTP_201_CREATED,
    summary="Отправить сообщение в диалог",
    description="Добавляет сообщение пользователя и получает ответ от AI. "
                "Возвращает оба сообщения. Для AI-сообщения возвращаются "
                "источники (sources), уверенность модели и флаг "
                "requires_escalation — клиент по нему решает, предлагать ли "
                "эскалацию на агента.",
)
async def add_message(
    conversation_id: int,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    if conversation.status == "ai_processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Дождитесь ответа по предыдущему сообщению.",
        )

    # Сохраняем сообщение пользователя
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    await db.flush()
    await db.refresh(user_message)

    conversation.status = "ai_processing"
    await enqueue_ai_response_job(db, conversation_id)
    await db.flush()

    return [user_message]


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
        ticket_id=0,  # ещё не создан
        title=title,
        body=classify_body,
    )

    department = ai_result.get("department") or "IT"
    # Pydantic-схема Ticket.department принимает только {"IT","HR","finance"};
    # AI-Lead может вернуть "other" — приземляем в "IT" как безопасный default.
    if department not in {"IT", "HR", "finance"}:
        department = "IT"

    # Извлекаем steps_tried из истории — что пользователь уже пробовал.
    # Простая эвристика на ключевые фразы; полноценное извлечение через
    # LLM — отдельная задача (iteration 2). Здесь — минимально полезно.
    steps_tried = _extract_steps_tried(messages)
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

async def _load_history_for_ai(
    db: AsyncSession,
    conversation_id: int,
) -> list[dict[str, str]]:
    """Загрузить последние MAX_HISTORY_MESSAGES сообщений в формате AI-Lead.

    AI-Lead принимает messages вида [{"role": "user"|"assistant", "content": "..."}].
    Наша внутренняя роль "ai" мапится в "assistant" — это стандарт OpenAI/Ollama,
    AI-Lead на нём построен (см. ai_module/answerer.py).

    role="system" мы НЕ отдаём — на стороне AI-Lead такие сообщения от
    клиента отбрасываются ради защиты от prompt injection (см. тест
    test_generate_answer_filters_client_system_messages в AI-Lead).

    Сортируем по (created_at, id) DESC — id гарантирует детерминированный
    порядок, когда несколько сообщений вставлены в одну транзакцию и имеют
    одинаковый created_at (server_default=func.now() возвращает время
    начала транзакции, а не каждой вставки).
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    rows = list(result.scalars().all())
    rows.reverse()  # снова в хронологический порядок

    history: list[dict[str, str]] = []
    for m in rows:
        if m.role == "user":
            role = "user"
        elif m.role == "ai":
            role = "assistant"
        else:
            # Любой другой role (включая случайно попавший "system") пропускаем.
            continue
        history.append({"role": role, "content": m.content})
    return history


async def _get_ai_answer(
    conversation_id: int,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Запрашивает ответ у AI Service.

    Возвращает dict с ключами answer/confidence/escalate/sources/model_version.
    Если сервис недоступен — возвращает безопасный fallback с requires_escalation,
    чтобы клиент сразу предложил пользователю эскалацию вместо тишины.

    Контракт (то, что мы ожидаем от AI-Lead — см. docs/ai-lead-contract.md):
      Запрос:
        {"conversation_id": int, "messages": list[{role, content}]}
      Ответ:
        {answer, confidence, escalate, sources?, model_version?}

      AI-Lead — внешний сервис, его поддерживает другая команда. На текущий
      момент (origin/ml1/AI-Lead) он ещё принимает старую single-message
      схему {"message": str}. Запрос на обновление контракта зафиксирован
      в docs/ai-lead-contract.md. До тех пор интеграция вернёт 422 от
      AI-Lead → отработает наш fallback ниже, пользователь сразу попадёт
      в красную зону и увидит кнопку эскалации.

      sources / model_version читаются через setdefault — отсутствие любого
      из них не ломает RestAPI.
    """
    import httpx
    from app.config import get_settings

    settings = get_settings()
    fallback = {
        "answer": "[AI Service временно недоступен. "
                  "Ваше сообщение сохранено, агент ответит вручную.]",
        "confidence": 0.0,  # принудительно красная зона → escalation
        "escalate": True,
        "sources": [],
        "model_version": settings.AI_MODEL_VERSION_FALLBACK,
    }

    service_urls = [settings.AI_SERVICE_URL.rstrip("/")]
    if service_urls[0] == "http://ai-service:8001":
        service_urls.append("http://localhost:8001")

    try:
        data: Any = None
        for service_url in service_urls:
            try:
                async with httpx.AsyncClient(timeout=settings.AI_SERVICE_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{service_url}/ai/answer",
                        json={
                            "conversation_id": conversation_id,
                            "messages": messages,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.HTTPStatusError,
                httpx.UnsupportedProtocol,
            ) as e:
                logger.warning(
                    "AI Service недоступен или ответ с ошибкой: %s",
                    e,
                    extra={
                        "conversation_id": conversation_id,
                        "ai_service_url": service_url,
                    },
                )
        if data is None:
            return fallback
    except (
        ValueError
    ) as e:
        logger.warning(
            "AI Service вернул невалидный JSON: %s",
            e,
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )
        return fallback

    # Если AI-Lead вернул не dict (защита от случайного String/None) — fallback.
    if not isinstance(data, dict):
        return fallback

    # Подставляем безопасные дефолты, чтобы вызывающий код не падал на None.
    data.setdefault("answer", "")
    data.setdefault("confidence", 0.5)
    data.setdefault("escalate", False)
    data.setdefault("sources", [])
    data.setdefault("model_version", settings.AI_MODEL_VERSION_FALLBACK)
    return data


def _should_offer_support_draft(messages: list[dict[str, str]]) -> bool:
    """Определяет, нужно ли показывать сбор контекста и создание черновика."""
    user_messages = [
        message.get("content", "").strip().lower()
        for message in messages
        if message.get("role") == "user" and message.get("content", "").strip()
    ]
    if not user_messages:
        return False

    latest = user_messages[-1]
    combined = "\n".join(user_messages)

    has_draft_action = any(term in latest for term in SUPPORT_DRAFT_ACTION_TERMS)
    has_draft_object = any(term in latest for term in SUPPORT_DRAFT_INTENT_TERMS)
    if has_draft_action and has_draft_object:
        return True

    has_urgent_context = any(term in combined for term in URGENT_TERMS)
    has_physical_incident = any(term in combined for term in PHYSICAL_INCIDENT_TERMS)
    if has_urgent_context and has_physical_incident:
        return True

    return False


def _build_intake_answer() -> str:
    return (
        "Соберу данные для черновика обращения. Из истории возьму описание проблемы "
        "и уже упомянутые действия. Уточните тип запроса, заявителя, офис, затронутый объект "
        "и конкретные детали по форме; "
        "после этого сформирую черновик для специалиста."
    )


def _extract_steps_tried(messages: list[Message]) -> str | None:
    """Эвристика: достаём из user-сообщений то, что похоже на "уже пробовал".

    Полноценное извлечение через LLM — отдельная задача (iteration 2).
    Здесь — минимально полезный baseline по ключевым фразам.

    Возвращаем None, если ничего не нашли — лучше пусто, чем мусор:
    None в БД явно показывает агенту "пользователь ничего не упомянул",
    в то время как пустая строка выглядела бы как "пробовал, но забыл что".
    """
    keywords = (
        "пробовал", "пыталс", "перезагру", "переустанови",
        "проверял", "уже делал", "сделал",
    )
    found: list[str] = []
    for m in messages:
        if m.role != "user":
            continue
        text = m.content.strip()
        lower = text.lower()
        if any(k in lower for k in keywords):
            found.append(text)
    if not found:
        return None
    return "\n".join(found)
