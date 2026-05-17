"""Извлечение структурированных полей из истории диалога через LLM.

Зачем отдельный модуль (а не inline в conversations.py):
  - тестируемость: LLM-extraction нужно мокать в тестах эскалации;
  - переиспользование: те же поля могут понадобиться в pre-classify
    pipeline для тикетов, созданных вручную;
  - graceful fallback: если AI-сервис недоступен, мы НЕ хотим валить
    эскалацию — возвращаем результат keyword-эвристики, чтобы
    steps_tried в тикете было хоть каким-то полезным.

Промпт-стратегия:
  - Делаем синтетическое user-сообщение с инструкцией + диалогом.
  - LLM должен вернуть либо строку через `; ` либо литерал NONE.
  - Любой ответ длиннее 500 символов считаем «модель заболталась» —
    используем как есть, но обрезаем (агенту короткое резюме полезнее
    полного пересказа).

Конвенция возврата:
  - None → ничего полезного не извлечено (агент видит «не указано»).
  - str  → конкретные действия пользователя (для UI и для агента).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from app.config import get_settings
from app.models.message import Message
from app.services.ai_service_client import ai_service_headers

logger = logging.getLogger(__name__)

# Модель может вернуть в ответе любое из этих → считаем как «ничего».
_NONE_MARKERS = ("none", "ничего", "не пробовал", "n/a", "—", "-", "")
# Обрезаем длинные ответы — агенту короткое резюме полезнее простыни.
_MAX_STEPS_LENGTH = 500

# Ключевые слова keyword-fallback'а: сохраняем поведение прежней
# _extract_steps_tried для тестов и на случай недоступности AI-сервиса.
_HEURISTIC_KEYWORDS = (
    "пробовал",
    "пыталс",
    "перезагру",
    "переустанови",
    "проверял",
    "уже делал",
    "сделал",
)


def _extract_steps_tried_heuristic(messages: Iterable[Message]) -> str | None:
    """Keyword-эвристика — fallback при недоступности LLM.

    Сохраняет поведение прежней _extract_steps_tried в conversations.py,
    чтобы при отказе AI-сервиса эскалация не теряла информацию совсем.
    """
    found: list[str] = []
    for m in messages:
        if m.role != "user":
            continue
        text = m.content.strip()
        lower = text.lower()
        if any(k in lower for k in _HEURISTIC_KEYWORDS):
            found.append(text)
    if not found:
        return None
    return "\n".join(found)


def extract_steps_tried_heuristic(messages: Iterable[Message]) -> str | None:
    return _extract_steps_tried_heuristic(messages)


def _build_extract_prompt(dialog_text: str) -> str:
    """Промпт для LLM. Просим именно список через `; `, чтобы парсить было проще."""
    return (
        "Ты — ассистент службы поддержки. Прочитай переписку и извлеки только "
        "конкретные действия, которые пользователь УЖЕ выполнил для решения "
        "проблемы (перезагружал, проверял, переустанавливал, и т.п.).\n\n"
        "Правила ответа:\n"
        "  • Перечисли действия в одну строку через `; ` (точка с запятой + пробел).\n"
        "  • Если пользователь ничего не пробовал — ответь буквально словом `NONE`.\n"
        "  • Не добавляй вступлений, объяснений, эмодзи или markdown.\n"
        "  • Перечисляй короткими фразами (3–6 слов на действие).\n\n"
        f"Переписка:\n{dialog_text}"
    )


def _format_dialog(messages: Iterable[Message]) -> str:
    """Перепаковываем сообщения в текстовый формат для встраивания в промпт."""
    lines: list[str] = []
    for m in messages:
        prefix = "Пользователь" if m.role == "user" else "AI"
        lines.append(f"{prefix}: {m.content.strip()}")
    return "\n".join(lines)


def _looks_empty(answer: str) -> bool:
    cleaned = answer.strip().lower().rstrip(".!?")
    return cleaned in _NONE_MARKERS


async def _call_extract_endpoint(prompt: str) -> str | None:
    """Зовём /ai/answer с одним user-сообщением. Возвращаем text или None.

    Ошибки сети/таймаута/невалидного JSON — логируем и возвращаем None,
    чтобы внешний код мог fallback'нуться. Использовать тот же обработчик,
    что в conversation_ai.get_ai_answer, не стали — нам не нужны
    confidence/escalate/sources, а нужно избежать побочных эффектов
    (FALLBACK_REASON, AILog) от того пути.
    """
    settings = get_settings()
    url = settings.AI_SERVICE_URL.rstrip("/") + "/ai/answer"

    try:
        async with httpx.AsyncClient(timeout=settings.AI_SERVICE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers=ai_service_headers(),
                json={
                    # conversation_id произвольный (>=1) — для эндпоинта это
                    # просто метка в логах, не БД-FK. Используем 0+1=1 чтобы
                    # пройти валидацию ge=1 в схеме AI-сервиса.
                    "conversation_id": 1,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("LLM extract failed, fallback to heuristic: %s", exc)
        return None

    if not isinstance(data, dict):
        return None
    answer = data.get("answer")
    if not isinstance(answer, str):
        return None
    return answer


async def extract_steps_tried(messages: list[Message]) -> str | None:
    """Извлекает действия пользователя «что уже пробовали» из истории диалога.

    Pipeline:
      1) формируем extraction-промпт с текстом диалога;
      2) зовём /ai/answer (LLM);
      3) если LLM вернул NONE/пусто/ошибку → пробуем keyword-эвристику.

    Возврат — None или конкретная строка для Ticket.steps_tried.
    """
    user_messages = [m for m in messages if m.role == "user"]
    if not user_messages:
        return None

    dialog = _format_dialog(messages)
    prompt = _build_extract_prompt(dialog)

    answer = await _call_extract_endpoint(prompt)
    if answer is not None:
        if _looks_empty(answer):
            # Модель явно сказала «ничего не пробовал» — доверяем.
            return None
        steps = answer.strip()
        if len(steps) > _MAX_STEPS_LENGTH:
            steps = steps[: _MAX_STEPS_LENGTH - 1].rstrip() + "…"
        return steps

    # AI-сервис недоступен → последний шанс: keyword-эвристика.
    return _extract_steps_tried_heuristic(messages)
