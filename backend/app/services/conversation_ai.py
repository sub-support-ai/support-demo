import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback
from app.models.message import Message
from app.services.ai_fallback import (
    FALLBACK_REASON_PAYLOAD_KEY,
    record_ai_fallback,
)
from app.services.ai_service_client import ai_service_headers
from app.services.knowledge_base import (
    LATENCY_PAYLOAD_KEY,
    KnowledgeSearchFilters,
    find_knowledge_answer,
)
from app.services.service_catalog import CatalogItem, detect_catalog_item, get_catalog_item

logger = logging.getLogger(__name__)

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


async def load_history_for_ai(
    db: AsyncSession,
    conversation_id: int,
) -> list[dict[str, str]]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    rows = list(result.scalars().all())
    rows.reverse()

    history: list[dict[str, str]] = []
    for message in rows:
        if message.role == "user":
            role = "user"
        elif message.role == "ai":
            role = "assistant"
        else:
            continue
        history.append({"role": role, "content": message.content})
    return history


async def get_ai_answer(
    conversation_id: int,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Спрашивает AI-сервис и возвращает payload с замеренной латенси.

    Латенси (полное время попытки, включая retry на second URL и timeout)
    кладётся в payload[LATENCY_PAYLOAD_KEY] в миллисекундах. Это поле потом
    уходит в AILog.ai_response_time_ms — питч-дек обещает «1,01 сек среднее»,
    и без честного замера эту цифру нечем подтвердить.
    """
    import httpx

    settings = get_settings()
    started = time.perf_counter()

    def _with_latency(payload: dict[str, Any]) -> dict[str, Any]:
        payload[LATENCY_PAYLOAD_KEY] = int((time.perf_counter() - started) * 1000)
        return payload

    fallback = {
        "answer": "[AI Service временно недоступен. Ваше сообщение сохранено, агент ответит вручную.]",
        "confidence": 0.0,
        "escalate": True,
        "sources": [],
        "model_version": settings.AI_MODEL_VERSION_FALLBACK,
    }

    service_urls = [settings.AI_SERVICE_URL.rstrip("/")]
    if service_urls[0] == "http://ai-service:8001":
        service_urls.append("http://localhost:8001")

    data: Any = None
    last_reason: str | None = None
    try:
        for service_url in service_urls:
            try:
                async with httpx.AsyncClient(timeout=settings.AI_SERVICE_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{service_url}/ai/answer",
                        headers=ai_service_headers(),
                        json={
                            "conversation_id": conversation_id,
                            "messages": messages,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
            except httpx.TimeoutException as exc:
                last_reason = "timeout"
                logger.warning(
                    "AI Service timeout: %s",
                    exc,
                    extra={"conversation_id": conversation_id, "ai_service_url": service_url},
                )
            except (httpx.ConnectError, httpx.UnsupportedProtocol) as exc:
                last_reason = "connect"
                logger.warning(
                    "AI Service connect error: %s",
                    exc,
                    extra={"conversation_id": conversation_id, "ai_service_url": service_url},
                )
            except httpx.HTTPStatusError as exc:
                last_reason = "http_5xx"
                logger.warning(
                    "AI Service HTTP error: %s",
                    exc,
                    extra={"conversation_id": conversation_id, "ai_service_url": service_url},
                )
        if data is None:
            fallback[FALLBACK_REASON_PAYLOAD_KEY] = last_reason or "connect"
            return _with_latency(fallback)
    except ValueError as exc:
        logger.warning(
            "AI Service returned invalid JSON: %s",
            exc,
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )
        fallback[FALLBACK_REASON_PAYLOAD_KEY] = "broken_json"
        return _with_latency(fallback)

    if not isinstance(data, dict):
        fallback[FALLBACK_REASON_PAYLOAD_KEY] = "empty_response"
        return _with_latency(fallback)

    data.setdefault("answer", "")
    data.setdefault("confidence", 0.5)
    data.setdefault("escalate", False)
    data.setdefault("sources", [])
    data.setdefault("model_version", settings.AI_MODEL_VERSION_FALLBACK)
    payload = _with_latency(data)
    logger.info(
        "AI Service responded",
        extra={
            "conversation_id": conversation_id,
            "ai_latency_ms": payload[LATENCY_PAYLOAD_KEY],
            "model_version": payload.get("model_version"),
            "ai_source": "llm",
        },
    )
    return payload


async def generate_ai_message(db: AsyncSession, conversation_id: int) -> Message:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    if conversation.status == "escalated":
        raise ValueError(f"Conversation {conversation_id} is already escalated")

    history = await load_history_for_ai(db, conversation_id)

    # ── Catalog-driven intake flow ────────────────────────────────────────────
    catalog_item = _resolve_catalog_item(conversation, history)
    if catalog_item is not None:
        ai_payload = await _run_intake_step(db, conversation, catalog_item, history)
    # ── Fallback: legacy keyword check → KB → LLM ────────────────────────────
    elif should_offer_support_draft(history):
        ai_payload = {
            "answer": build_intake_answer(),
            "confidence": 0.5,
            "escalate": True,
            "sources": [],
            "model_version": "intake-rules-v1",
        }
    else:
        ai_payload = await find_knowledge_answer(db, history)
        if ai_payload is None:
            ai_payload = await get_ai_answer(conversation_id, history)

    # Если AI ушёл в fallback — фиксируем причину для дашборда «Сбои AI».
    # KB-ответ и intake-rules сюда не попадают (там reason не выставляется).
    fallback_reason = ai_payload.get(FALLBACK_REASON_PAYLOAD_KEY)
    if fallback_reason:
        await record_ai_fallback(
            db,
            service="answer",
            reason=fallback_reason,
            conversation_id=conversation_id,
        )

    confidence = ai_payload.get("confidence")
    escalate = bool(ai_payload.get("escalate"))

    red_zone_threshold = get_settings().RAG_CONFIDENCE_RED_ZONE
    requires_escalation = (
        escalate
        or (confidence is not None and confidence < red_zone_threshold)
    )

    ai_message = Message(
        conversation_id=conversation_id,
        role="ai",
        content=ai_payload.get("answer", ""),
        ai_confidence=confidence,
        ai_escalate=escalate,
        sources=ai_payload.get("sources") or None,
        requires_escalation=requires_escalation,
    )
    db.add(ai_message)
    if conversation.status == "ai_processing":
        conversation.status = "active"

    await db.flush()

    if ai_payload.get("knowledge_article_id") is not None:
        article = await db.get(KnowledgeArticle, int(ai_payload["knowledge_article_id"]))
        if article is not None:
            article.view_count += 1
            db.add(
                KnowledgeArticleFeedback(
                    article_id=article.id,
                    conversation_id=conversation_id,
                    message_id=ai_message.id,
                    user_id=conversation.user_id,
                    query=ai_payload.get("knowledge_query") or "",
                    score=float(ai_payload.get("knowledge_score") or 0.0),
                    decision=ai_payload.get("knowledge_decision") or "answer",
                )
            )
        # Латенси из payload (find_knowledge_answer / get_ai_answer уже её
        # измерили). Если по какой-то причине поля нет — 0 как honest «не знаем»
        # вместо None, чтобы дашборд не ломался на NULL в AVG.
        latency_ms = int(ai_payload.get(LATENCY_PAYLOAD_KEY) or 0)
        db.add(
            AILog(
                ticket_id=None,
                conversation_id=conversation_id,
                model_version=ai_payload.get("model_version") or "knowledge-base-v1",
                predicted_category="knowledge_base",
                predicted_priority="низкий",
                confidence_score=float(confidence or 0.0),
                routed_to_agent_id=None,
                ai_response_draft=ai_payload.get("answer"),
                ai_response_time_ms=latency_ms,
                outcome="resolved_by_ai",
            )
        )

    await db.flush()
    await db.refresh(ai_message)
    return ai_message


def _resolve_catalog_item(
    conversation: Conversation,
    history: list[dict[str, str]],
) -> CatalogItem | None:
    """Возвращает активный CatalogItem для диалога.

    Если catalog_code уже привязан к разговору — берём его напрямую.
    Иначе пробуем определить по истории сообщений.
    """
    if conversation.catalog_code:
        return get_catalog_item(conversation.catalog_code)
    return detect_catalog_item(history)


async def _run_intake_step(
    db: AsyncSession,
    conversation: Conversation,
    item: CatalogItem,
    history: list[dict[str, str]],
) -> dict[str, Any]:
    """Один шаг сбора данных по catalog item.

    Логика:
      1. Если catalog_code ещё не записан — это первое обнаружение.
         Сначала пробуем KB с фильтром по отделу: вдруг есть готовый ответ.
         Если KB не отвечает или отправляет на эскалацию — начинаем опрос.
      2. Если catalog_code уже есть — продолжаем опрос.
         Берём последний user-ответ как значение последнего запрошенного поля.
      3. Когда все поля собраны — возвращаем payload с готовым резюме для черновика.
    """
    collected: dict[str, str] = dict(conversation.intake_fields or {})
    first_detection = conversation.catalog_code is None

    if first_detection:
        # Попробовать KB с фильтром по отделу каталога
        kb_filters = KnowledgeSearchFilters(department=item.kb_department) if item.kb_department else None
        kb_payload = await find_knowledge_answer(db, history, filters=kb_filters)
        if kb_payload and kb_payload.get("knowledge_decision") != "escalate":
            # KB нашёл хороший ответ — возвращаем его, intake не нужен
            return kb_payload

        # KB не помог — стартуем опрос
        conversation.catalog_code = item.code
        conversation.intake_fields = {}
        collected = {}
    else:
        # Записываем ответ пользователя на последний вопрос
        last_asked = collected.pop("_last_asked", None)
        if last_asked:
            last_user_msg = _last_user_message(history)
            if last_user_msg:
                collected[last_asked] = last_user_msg

    next_field = item.next_missing(collected)

    if next_field is None:
        # Все поля собраны — строим резюме для черновика
        conversation.intake_fields = collected
        return _build_draft_payload(item, collected)

    # Задаём следующий вопрос
    question = item.question_for(next_field)
    if first_detection and not collected:
        answer = f"Оформлю запрос «{item.title}». {question}"
    else:
        answer = question

    collected["_last_asked"] = next_field
    conversation.intake_fields = collected

    return {
        "answer": answer,
        "confidence": 1.0,
        "escalate": False,
        "sources": [],
        "model_version": "intake-rules-v1",
    }


def _last_user_message(history: list[dict[str, str]]) -> str | None:
    for msg in reversed(history):
        if msg.get("role") == "user":
            return msg.get("content", "").strip() or None
    return None


def _build_draft_payload(item: CatalogItem, collected: dict[str, str]) -> dict[str, Any]:
    lines = [f"**Черновик обращения: {item.title}**", ""]
    field_labels = {
        "username": "Заявитель",
        "office": "Офис / кабинет",
        "error_code": "Код ошибки",
        "affected_system": "Система",
        "operation": "Операция",
        "device_description": "Устройство",
        "software_name": "Программа",
        "justification": "Обоснование",
        "sender_email": "Адрес отправителя",
        "already_clicked": "Перешли по ссылке",
        "description": "Описание",
        "device_type": "Тип устройства",
        "serial_number": "Серийный номер",
        "circumstances": "Обстоятельства",
        "document_type": "Тип документа",
        "delivery_date": "Срок готовности",
        "purpose": "Назначение",
        "vacation_start": "Начало отпуска",
        "vacation_end": "Конец отпуска",
        "vacation_type": "Тип отпуска",
        "item_description": "Что закупить",
        "budget": "Бюджет",
    }
    for field_name in item.required_fields:
        label = field_labels.get(field_name, field_name)
        value = collected.get(field_name, "—")
        lines.append(f"- **{label}:** {value}")

    lines += [
        "",
        "Данные собраны. Подтвердите отправку или скорректируйте любое поле.",
    ]
    if item.is_emergency:
        lines.insert(0, "⚠️ Срочный запрос — будет обработан приоритетно.")
        lines.insert(1, "")

    return {
        "answer": "\n".join(lines),
        "confidence": 1.0,
        "escalate": True,
        "sources": [],
        "model_version": "intake-rules-v1",
        "catalog_code": item.code,
    }


def should_offer_support_draft(messages: list[dict[str, str]]) -> bool:
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


def build_intake_answer() -> str:
    return (
        "Соберу данные для черновика обращения. Из истории возьму описание проблемы "
        "и уже упомянутые действия. Уточните тип запроса, заявителя, офис, затронутый объект "
        "и конкретные детали по форме; "
        "после этого сформирую черновик для специалиста."
    )
