"""Запись событий fallback'а AI-сервиса.

`get_ai_answer` (conversation_ai) и `classify_ticket` (ai_classifier) — чистые
функции, не получают db session, поэтому сами в БД не пишут. Они проставляют
reason в payload (служебный ключ FALLBACK_REASON_PAYLOAD_KEY), а вызывающие
их корутины (generate_ai_message, create_ticket) видят это поле и зовут
`record_ai_fallback`.

Reason-коды стабильны, см. AIFallbackEvent.reason — на них завязан
GROUP BY в /stats/ai/fallbacks и UI-виджет на дашборде.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_fallback_event import AIFallbackEvent

logger = logging.getLogger(__name__)

# Служебный ключ в payload — параллель LATENCY_PAYLOAD_KEY (Блок 3).
FALLBACK_REASON_PAYLOAD_KEY = "_fallback_reason"

ServiceKind = Literal["answer", "classify"]
FallbackReason = Literal[
    "timeout",
    "connect",
    "http_5xx",
    "broken_json",
    "empty_response",
]


async def record_ai_fallback(
    db: AsyncSession,
    *,
    service: ServiceKind,
    reason: FallbackReason,
    conversation_id: int | None = None,
    ticket_id: int | None = None,
) -> None:
    """Пишет событие fallback'а в ai_fallback_events.

    Транзакционно живёт в той же сессии, что и основная бизнес-логика
    (запись Message / Ticket): если основной flow откатится, событие тоже
    пропадёт — это корректно, иначе дашборд показывал бы события, которых
    с точки зрения пользователя не было.
    """
    db.add(
        AIFallbackEvent(
            conversation_id=conversation_id,
            ticket_id=ticket_id,
            service=service,
            reason=reason,
        )
    )
    logger.warning(
        "AI fallback recorded",
        extra={
            "ai_service": service,
            "ai_fallback_reason": reason,
            "conversation_id": conversation_id,
            "ticket_id": ticket_id,
        },
    )
