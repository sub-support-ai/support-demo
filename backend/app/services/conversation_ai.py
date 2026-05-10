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
from app.services.knowledge_base import LATENCY_PAYLOAD_KEY, find_knowledge_answer

logger = logging.getLogger(__name__)

# Лимиты на историю, передаваемую в LLM:
#  - MESSAGES — потолок по штукам (защита от диалогов на 200 сообщений).
#  - TOKENS   — потолок по бюджету токенов (защита от длинных простыней).
#
# AI-сервис принимает list[ChatMessage] с каждым content до 10000 символов,
# но контекстное окно Mistral-7B ~8k токенов; если сложить 20 сообщений
# по 2000 символов, мы переполним окно и модель отрежет начало (или упадёт).
# Соответственно: берём ПОСЛЕДНИЕ 20 сообщений, но если их суммарный
# объём в токенах превышает MAX_HISTORY_TOKENS — выкидываем самые старые,
# пока не уложимся. Самый свежий user-message сохраняем всегда — без него
# у модели нет точки отсчёта.
MAX_HISTORY_MESSAGES = 20
# 1 русский токен ≈ 2-3 символа, английский ≈ 4. Используем оценку 1 токен ≈ 3 символа
# (см. estimate_token_count в knowledge_embeddings — там по словам, что грубее).
# 4096 токенов на историю = ~12'288 символов: оставляет ~3-4k токенов для
# system-промпта + RAG-контекста + ответа модели.
MAX_HISTORY_TOKENS = 4096
_CHARS_PER_TOKEN = 3

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


# Поля, которые мы соглашаемся хранить в Message.sources. Всё, что приходит
# от AI-сервиса/KB вне этого whitelist'а — отбрасываем: фронтовая схема
# SourceRead типизирована, и неизвестные поля только добавят шум в JSON.
_SOURCE_FIELDS = {
    "title", "url", "article_id", "chunk_id",
    "snippet", "retrieval", "score", "decision",
}
# Sources на одно AI-сообщение лимитируются: 5 ссылок — потолок UX'а.
# Всё, что больше, перегружает чат и обычно не релевантно.
_MAX_SOURCES = 5


def _normalize_sources(raw: object) -> list[dict] | None:
    """Приводит ai_payload['sources'] к консистентному формату для БД.

    Зачем нормализуем:
      - LLM возвращает {title, url}; KB-build возвращает 8 полей; intake/fallback
        возвращают [] (или вообще не возвращают). Сохраняя как есть, JSON-колонка
        обрастает полиморфизмом, и фронт ломается на неожиданном формате.
      - Без `title` source бесполезен (UI рендерит «Источник: <title>»),
        такие записи режем.
      - Дубликаты по `article_id` — частые при гибридном поиске (FTS+semantic
        нашли одну и ту же статью в разных чанках); merge оставляет одну.

    Возвращаем None, если после нормализации список пуст — это
    отличает «AI не присылал источников вообще» от «список приехал, но
    после фильтра остался пустым» (оба → None в БД, но при отладке хорошо
    видеть, что в логах source_input был непустым).
    """
    if not isinstance(raw, list):
        return None

    seen_article_ids: set[int] = set()
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        # Дедуплицируем по article_id (если есть — KB-источники).
        article_id = item.get("article_id")
        if isinstance(article_id, int):
            if article_id in seen_article_ids:
                continue
            seen_article_ids.add(article_id)
        # Оставляем только whitelisted-поля. Если score пришёл строкой
        # ("0.85") — приведение в float делать не будем, фронт сам справится
        # с union[float | str | None]. Главное — не пропускать мусор.
        normalized = {k: v for k, v in item.items() if k in _SOURCE_FIELDS}
        normalized["title"] = title.strip()
        cleaned.append(normalized)
        if len(cleaned) >= _MAX_SOURCES:
            break
    return cleaned or None


def _estimate_tokens(text: str) -> int:
    """Грубая оценка токенов для русско-английских текстов.

    Точный токенайзер (tiktoken/sentencepiece) тянуть в backend не хочется —
    это +30 МБ в Docker-образ ради метрики «сколько примерно». Оценка
    `len(text) / 3` стабильно даёт верхнюю границу для русского текста
    и нижнюю для английского — нам важно не переоценить и обрезать
    лишнее, поэтому занижаем символы на токен (округление вверх).
    """
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


async def load_history_for_ai(
    db: AsyncSession,
    conversation_id: int,
) -> list[dict[str, str]]:
    """История диалога для LLM с учётом токенного бюджета.

    Алгоритм:
      1) Берём последние MAX_HISTORY_MESSAGES сообщений из БД (DESC).
      2) Идём от свежих к старым, копим бюджет MAX_HISTORY_TOKENS.
      3) Как только следующее сообщение не влезает — отбрасываем его и всё,
         что старше (середину диалога не вырезаем — это ломает связность).
      4) Разворачиваем в хронологический порядок для модели.

    Самый свежий user-message — всегда в выдаче, даже если он один превышает
    бюджет (модель сама обрежет, но мы не хотим тихо удалять последний вопрос
    пользователя — он точно нужен).
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    rows = list(result.scalars().all())  # DESC: [last, ..., first]

    # Копим с самого свежего, отбрасываем старые при переполнении бюджета.
    budget = MAX_HISTORY_TOKENS
    kept_desc: list[Message] = []
    for index, message in enumerate(rows):
        if message.role not in {"user", "ai"}:
            continue
        cost = _estimate_tokens(message.content)
        if cost <= budget or index == 0:
            # Первое (самое свежее) сообщение — всегда оставляем, даже если
            # оно одно перебирает бюджет: без него у LLM нет вопроса.
            kept_desc.append(message)
            budget -= cost
        else:
            break

    kept = list(reversed(kept_desc))
    history: list[dict[str, str]] = []
    for message in kept:
        role = "user" if message.role == "user" else "assistant"
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
        sources=_normalize_sources(ai_payload.get("sources")),
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
