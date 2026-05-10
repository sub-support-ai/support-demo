"""Промоут решённого тикета в черновик KB-статьи.

Сценарий: агент закрыл тикет с подробным решением в комментариях. Это
знание не должно остаться в одном тикете — оно должно стать статьёй
KB, чтобы следующий пользователь с такой же проблемой получил ответ
от AI без поднятия агента.

Pipeline:
  1) Загружаем тикет + последние агентские комментарии (внутренние и
     внешние, потому что решение часто пишется и в публичный ответ
     пользователю, и во внутреннюю заметку).
  2) Скармливаем в LLM с промптом «извлеки структурированную статью KB».
  3) Парсим JSON-ответ, валидируем.
  4) Создаём KnowledgeArticle с is_active=False и source_url=
     `ticket://{id}` — это draft, который админ ревьюит и публикует
     (вручную или batch'ом).

Почему is_active=False по умолчанию:
  - LLM-извлечение из тикета — heuristic, может содержать неточности.
  - Содержимое тикета может содержать конфиденциальные детали (имена
    клиентов, IP-адреса, внутренние процедуры).
  - Без человеческого ревью статья не должна попадать в выдачу AI.

Возможные расширения (todo):
  - Batch-промоут: «промоутни всё с helped=true за месяц».
  - Дедупликация: проверять similarity к существующим статьям, чтобы не
    плодить дубликаты вроде «VPN не работает / VPN не подключается».
  - Auto-publish для admin-флага «trusted agent».
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants.departments import DEPARTMENTS_SET
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.services.ai_service_client import ai_service_headers
from app.services.knowledge_ingestion import upsert_knowledge_article

logger = logging.getLogger(__name__)


_PROMOTION_TIMEOUT_SECONDS = 30.0
# Сколько последних комментариев агента берём в промпт. Решение обычно
# в последних 1–3 комментариях. Брать всю историю — переполнение контекста.
_MAX_AGENT_COMMENTS = 5


def _build_prompt(ticket: Ticket, agent_comments: list[TicketComment]) -> str:
    """Промпт для извлечения структурированной KB-статьи.

    Просим строго JSON: title/problem/steps/keywords/when_to_escalate.
    Эти поля — минимум, который потом проходит через
    upsert_knowledge_article. Остальные поля (symptoms, applies_to)
    можно дополнить вручную при ревью админом.
    """
    comments_block = "\n\n".join(
        f"[{'внутренний' if c.internal else 'публичный'} {c.created_at:%Y-%m-%d %H:%M}]\n"
        f"{c.content}"
        for c in agent_comments
    )

    return (
        "Ты помогаешь команде поддержки превратить решённый тикет в статью базы "
        "знаний. По описанию тикета и комментариям агентов извлеки структурированный "
        "ответ. Верни СТРОГО JSON без markdown-обёртки.\n\n"
        "Поля:\n"
        '  "title": краткий заголовок проблемы (5–12 слов)\n'
        '  "problem": одно предложение с описанием проблемы пользователя\n'
        '  "steps": массив 3–7 строк — конкретные шаги решения (повелительное наклонение)\n'
        '  "when_to_escalate": одно предложение — когда пользователю всё-таки создавать тикет\n'
        '  "keywords": строка из 8–15 поисковых синонимов через пробел\n\n'
        "Правила:\n"
        "  • Только то, что реально упоминается в тикете. НЕ выдумывай шаги.\n"
        "  • Удаляй конфиденциальное: имена клиентов, IP, внутренние URL.\n"
        "  • Если тикет невозможно обобщить (slishком частный случай) — верни "
        '`{"error": "too_specific"}`.\n\n'
        f"Тикет #{ticket.id}\n"
        f"Отдел: {ticket.department}\n"
        f"Тема: {ticket.title}\n"
        f"Описание: {ticket.body[:2000]}\n"
        + (f"Что пробовали: {ticket.steps_tried}\n" if ticket.steps_tried else "")
        + f"\nКомментарии агентов:\n{comments_block}"
    )


async def _ask_llm(prompt: str) -> dict[str, Any] | None:
    """Зовёт /ai/answer и парсит JSON. None при любой ошибке."""
    settings = get_settings()
    url = settings.AI_SERVICE_URL.rstrip("/") + "/ai/answer"

    try:
        async with httpx.AsyncClient(timeout=_PROMOTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers=ai_service_headers(),
                json={
                    "conversation_id": 1,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("KB promotion LLM call failed: %s", exc)
        return None

    if not isinstance(data, dict):
        return None
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None

    # LLM может обернуть в ```json ... ``` — снимаем.
    raw = answer.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("KB promotion: LLM вернул невалидный JSON: %s", exc)
        return None


def _validate_extracted(data: dict[str, Any]) -> dict[str, Any] | None:
    """Чистит и валидирует ответ LLM.

    Возвращает dict, готовый к upsert_knowledge_article, или None.
    """
    if data.get("error") == "too_specific":
        return None
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    problem = data.get("problem") if isinstance(data.get("problem"), str) else None
    when_to_escalate = (
        data.get("when_to_escalate") if isinstance(data.get("when_to_escalate"), str) else None
    )
    keywords = data.get("keywords") if isinstance(data.get("keywords"), str) else None
    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list):
        return None
    steps = [str(s).strip() for s in steps_raw if str(s).strip()]
    if not steps:
        return None

    # body — собираем человекочитаемый текст из problem + steps. Это тело
    # уйдёт в FTS, поэтому пишем содержательно, не плейсхолдер.
    body_parts = []
    if problem:
        body_parts.append(problem)
    body_parts.append("Шаги решения:")
    body_parts.extend(f"  {i}. {step}" for i, step in enumerate(steps, start=1))
    if when_to_escalate:
        body_parts.append(f"\nКогда создавать запрос: {when_to_escalate}")

    return {
        "title": title.strip(),
        "problem": problem.strip() if problem else None,
        "steps": steps,
        "when_to_escalate": when_to_escalate.strip() if when_to_escalate else None,
        "keywords": keywords.strip() if keywords else None,
        "body": "\n".join(body_parts),
    }


async def promote_ticket_to_kb_draft(
    db: AsyncSession,
    ticket: Ticket,
    *,
    requested_by_user_id: int | None,
) -> dict[str, Any] | None:
    """Создаёт черновик KB-статьи из решённого тикета.

    Возвращает dict с {article_id, title, status} или None, если LLM не
    смог извлечь структурированный ответ (например, тикет слишком
    специфичный).

    Контракт стороны вызова:
      - тикет должен быть в статусе resolved/closed (вызывающий код
        проверяет — мы здесь просто доверяем);
      - department тикета должен быть валидным (см. constants.departments).
        Если нет — статья создастся с department=None, админ выберет
        при ревью.
    """
    # Подгружаем последние комментарии агента (любого, не только
    # текущего assigned'а: тикет могли передавать).
    comments_result = await db.execute(
        select(TicketComment)
        .where(
            TicketComment.ticket_id == ticket.id,
            TicketComment.author_role.in_(("agent", "admin")),
        )
        .order_by(TicketComment.created_at.desc(), TicketComment.id.desc())
        .limit(_MAX_AGENT_COMMENTS)
    )
    agent_comments = list(reversed(comments_result.scalars().all()))
    if not agent_comments:
        logger.info("Ticket %d has no agent comments — nothing to promote", ticket.id)
        return None

    prompt = _build_prompt(ticket, agent_comments)
    extracted = await _ask_llm(prompt)
    if extracted is None:
        return None

    cleaned = _validate_extracted(extracted)
    if cleaned is None:
        return None

    # Department — из тикета, если он валидный. Иначе None (админ
    # выберет при ревью).
    department = ticket.department if ticket.department in DEPARTMENTS_SET else None

    article_data = {
        **cleaned,
        "department": department,
        "request_type": ticket.request_type,
        # is_active=False — критично: статья НЕ должна попадать в
        # AI-выдачу до ревью админом.
        "is_active": False,
        # access_scope=internal — черновик виден только агентам/админам
        # на фронте, не пользователям.
        "access_scope": "internal",
        "owner": "auto-extracted from ticket",
        "source_url": f"ticket://{ticket.id}",
    }

    article, created = await upsert_knowledge_article(
        db,
        article_data,
        requested_by_user_id=requested_by_user_id,
    )
    return {
        "article_id": article.id,
        "title": article.title,
        "is_active": article.is_active,
        "created": created,
    }
