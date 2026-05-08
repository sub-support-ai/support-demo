from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIFallbackEvent(Base):
    """Лог каждого случая, когда основной AI-вызов не сработал и пришлось
    отдавать fallback. Нужен для двух задач:

    1) Дашборд «Сбои AI за 24ч»: показывает админу, сколько раз и по какой
       причине AI был недоступен. Без этой картины тяжело отличить
       «Ollama тормозит» от «у нас сетевые проблемы» от «модель отдаёт
       мусорный JSON» — все они одинаково выглядят как «ответ из fallback».

    2) Алёрты: по росту fallback-rate можно завязать оповещение в Sentry
       или Prometheus задолго до того, как пользователи начнут жаловаться.

    Сознательно не добавляем response_time / payload_size / etc — для этого
    есть AILog.ai_response_time_ms (см. Блок 3). Здесь — только причина.
    """

    __tablename__ = "ai_fallback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Один из двух источников: get_ai_answer (chat) или classify_ticket (intake).
    # Подходящий FK заполняется, второй остаётся NULL.
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ticket_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Какой AI-вызов упал: "answer" (chat) или "classify" (intake).
    service: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Тип сбоя — один из стабильных кодов, чтобы агрегировать GROUP BY:
    #   timeout       — httpx.TimeoutException
    #   connect       — httpx.ConnectError / UnsupportedProtocol
    #   http_5xx      — httpx.HTTPStatusError (включая 4xx, в логике сейчас одинаково)
    #   broken_json   — ответ не парсится как JSON
    #   empty_response — успешный HTTP, но тело null/не-dict
    reason: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
