import json
import logging
import time

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

AI_SERVICE_URL = settings.AI_SERVICE_URL

_CLASSIFICATION_FALLBACK = {
    "category": "other",
    "department": "IT",
    "priority": "средний",
    "confidence": 0.0,
    "draft_response": "[AI Service недоступен — требует агента]",
    "model_version": settings.AI_MODEL_VERSION_FALLBACK,
}

_VALID_DEPARTMENTS = {"IT", "HR", "finance"}
_PRIORITY_RANK = {
    "низкий": 0,
    "средний": 1,
    "высокий": 2,
    "критический": 3,
}
_CRITICAL_TERMS = (
    "авар",
    "критич",
    "простой",
    "у всех",
    "весь отдел",
    "вся команда",
    "массов",
    "сервер не работает",
    "база недоступ",
    "1с не работает",
    "касса не работает",
)
_HIGH_TERMS = (
    "сроч",
    "не работает",
    "не могу работать",
    "слом",
    "порван",
    "перегор",
    "недоступ",
    "заблок",
    "не включается",
    "не запускается",
    "надо заменить",
    "нужно заменить",
)
_LOW_TERMS = (
    "как сделать",
    "как обновить",
    "хочу обновить",
    "обновить программу",
    "обновить приложение",
    "как установить",
    "как настроить",
    "инструкция",
    "подскажите",
    "где скачать",
)


def _infer_priority_from_text(title: str, body: str) -> str | None:
    text = f"{title}\n{body}".lower()
    if any(term in text for term in _CRITICAL_TERMS):
        return "критический"
    if any(term in text for term in _HIGH_TERMS):
        return "высокий"
    if any(term in text for term in _LOW_TERMS):
        return "низкий"
    return None


def _choose_priority(current: object, inferred: str | None) -> str:
    current_priority = current if isinstance(current, str) else None
    if current_priority not in _PRIORITY_RANK:
        current_priority = _CLASSIFICATION_FALLBACK["priority"]
    if inferred is None:
        return current_priority
    if inferred == "низкий":
        return inferred
    return (
        inferred
        if _PRIORITY_RANK[inferred] > _PRIORITY_RANK[current_priority]
        else current_priority
    )


async def classify_ticket(ticket_id: int, title: str, body: str) -> dict:
    """
    Отправляет тикет в AI Service, получает классификацию от Mistral.

    В ответ кладём `response_time_ms` — длительность вызова в миллисекундах.
    Используется в AILog.ai_response_time_ms для метрик (питч-дек обещает
    среднее время 1,01 сек — честно считаем по этому полю).
    """
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{AI_SERVICE_URL}/ai/classify",
                json={
                    "ticket_id": ticket_id,
                    "title": title,
                    "body": body,
                },
            )
            response.raise_for_status()
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    "AI Service вернул невалидный JSON для classify",
                    extra={"ticket_id": ticket_id},
                    exc_info=True,
                )
                data = dict(_CLASSIFICATION_FALLBACK)

    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.HTTPStatusError,
        httpx.UnsupportedProtocol,
    ) as e:
        logger.warning(
            "AI Service недоступен или ответ с ошибкой: %s",
            e,
            extra={"ticket_id": ticket_id},
        )
        data = dict(_CLASSIFICATION_FALLBACK)

    if not isinstance(data, dict):
        data = dict(_CLASSIFICATION_FALLBACK)

    data.setdefault("category", _CLASSIFICATION_FALLBACK["category"])
    data.setdefault("priority", _CLASSIFICATION_FALLBACK["priority"])
    data.setdefault("confidence", _CLASSIFICATION_FALLBACK["confidence"])
    data.setdefault("draft_response", _CLASSIFICATION_FALLBACK["draft_response"])
    data.setdefault("model_version", settings.AI_MODEL_VERSION_FALLBACK)

    department = data.get("department") or _CLASSIFICATION_FALLBACK["department"]
    if department not in _VALID_DEPARTMENTS:
        department = _CLASSIFICATION_FALLBACK["department"]
    data["department"] = department
    data["priority"] = _choose_priority(
        data.get("priority"),
        _infer_priority_from_text(title, body),
    )

    data["response_time_ms"] = int((time.perf_counter() - started) * 1000)
    return data
