"""LLM-rewriting запроса к KB для повышения recall.

Зачем:
  - пользователь пишет "почта легла", в KB есть статья
    "Outlook: не подключается к Exchange-серверу" — keyword/semantic search
    может не свести их вместе;
  - LLM, видя весь контекст диалога, переписывает в один точный поисковый
    запрос с техническими терминами ("Outlook Exchange connection error");
  - на multi-turn диалогах с уточнениями ("какая ОС?", "win10") rewrite
    добавляет в запрос факты, которые keyword-склейка теряет.

Когда НЕ использовать:
  - на короткой первой реплике пользователя rewrite чаще запутывает,
    чем помогает (LLM додумывает термины, которых пользователь не имел в виду);
  - на запросе уже в форме «как настроить X» — rewrite добавит шум.

Поэтому функция feature-flag'нута через KB_QUERY_REWRITE_ENABLED. Включать
после A/B-теста на метриках recall@1 / helped %.

Контракт:
  - возвращает строку либо None;
  - None означает «модель ничего полезного не вернула, используй fallback»
    (вызывающий код сам пойдёт по обычному _build_kb_query).
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.services.ai_service_client import ai_service_headers

logger = logging.getLogger(__name__)

# Лимит на rewrite — отдельный таймаут, потому что AI_SERVICE_TIMEOUT_SECONDS
# может быть 60-180 сек (для больших ответов LLM), а тут нам нужно быстрее
# отвалиться на fallback, чем заставлять пользователя ждать.
_REWRITE_TIMEOUT_SECONDS = 5.0
_REWRITE_MAX_OUTPUT_CHARS = 500


def _build_rewrite_prompt(user_messages: list[str], assistant_messages: list[str]) -> str:
    dialog_lines: list[str] = []
    # Чередуем user/assistant в исходном порядке (плюс-минус).
    # Простая эвристика: интерливим по очереди; если разная длина — допишем
    # хвост user-сообщений.
    pairs = list(zip(user_messages, assistant_messages, strict=False))
    for user, assistant in pairs:
        dialog_lines.append(f"Пользователь: {user}")
        dialog_lines.append(f"Бот: {assistant}")
    # Хвост user-сообщений, если их больше чем assistant.
    for user in user_messages[len(pairs):]:
        dialog_lines.append(f"Пользователь: {user}")
    dialog = "\n".join(dialog_lines)

    return (
        "Ты — поисковый ассистент службы поддержки. Прочитай переписку клиента "
        "с ботом и переформулируй проблему клиента в один короткий поисковый "
        "запрос (5–15 слов) для базы знаний.\n\n"
        "Правила:\n"
        "  • Только сам запрос, без вступлений, кавычек и markdown.\n"
        "  • Включи технические термины, если они уместны (название ПО, протокол, код ошибки).\n"
        "  • НЕ добавляй слов, которых нет в смысле переписки.\n"
        "  • Если переписка слишком короткая или непонятная — повтори последнее сообщение клиента.\n\n"
        f"Переписка:\n{dialog}"
    )


async def rewrite_query_for_kb(
    user_messages: list[str],
    assistant_messages: list[str],
) -> str | None:
    """Просит LLM переформулировать диалог в один поисковый запрос.

    Возвращает строку или None при ошибке/feature-flag-disabled.

    На ошибку HTTP/timeout/JSON просто возвращаем None — вызывающий код
    использует свой fallback (обычно `_build_kb_query`).
    """
    settings = get_settings()
    if not settings.KB_QUERY_REWRITE_ENABLED:
        return None
    if not user_messages:
        return None

    prompt = _build_rewrite_prompt(user_messages, assistant_messages)
    url = settings.AI_SERVICE_URL.rstrip("/") + "/ai/answer"

    try:
        async with httpx.AsyncClient(timeout=_REWRITE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers=ai_service_headers(),
                json={
                    "conversation_id": 1,  # синтетика, не FK в БД
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Query rewrite failed, fallback to raw query: %s", exc)
        return None

    if not isinstance(data, dict):
        return None
    answer = data.get("answer")
    if not isinstance(answer, str):
        return None

    rewritten = answer.strip()
    if not rewritten or len(rewritten) > _REWRITE_MAX_OUTPUT_CHARS:
        return None
    return rewritten
