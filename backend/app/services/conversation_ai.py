import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback
from app.models.message import Message
from app.services.ai_service_client import ai_service_headers
from app.services.knowledge_base import find_knowledge_answer

logger = logging.getLogger(__name__)

RED_ZONE_THRESHOLD = 0.6
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
    import httpx

    settings = get_settings()
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

    try:
        data: Any = None
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
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.HTTPStatusError,
                httpx.UnsupportedProtocol,
            ) as exc:
                logger.warning(
                    "AI Service unavailable or returned an error: %s",
                    exc,
                    extra={
                        "conversation_id": conversation_id,
                        "ai_service_url": service_url,
                    },
                )
        if data is None:
            return fallback
    except ValueError as exc:
        logger.warning(
            "AI Service returned invalid JSON: %s",
            exc,
            extra={"conversation_id": conversation_id},
            exc_info=True,
        )
        return fallback

    if not isinstance(data, dict):
        return fallback

    data.setdefault("answer", "")
    data.setdefault("confidence", 0.5)
    data.setdefault("escalate", False)
    data.setdefault("sources", [])
    data.setdefault("model_version", settings.AI_MODEL_VERSION_FALLBACK)
    return data


async def generate_ai_message(db: AsyncSession, conversation_id: int) -> Message:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    if conversation.status == "escalated":
        raise ValueError(f"Conversation {conversation_id} is already escalated")

    history = await load_history_for_ai(db, conversation_id)
    if should_offer_support_draft(history):
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

    confidence = ai_payload.get("confidence")
    escalate = bool(ai_payload.get("escalate"))

    requires_escalation = (
        escalate
        or (confidence is not None and confidence < RED_ZONE_THRESHOLD)
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
                ai_response_time_ms=0,
                outcome="resolved_by_ai",
            )
        )

    await db.flush()
    await db.refresh(ai_message)
    return ai_message


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
