from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AILog(Base):
    """
    Журнал каждого решения локального Mistral (через AI Service). Три назначения:

    1. МЕТРИКИ ДЛЯ АКСЕЛЕРАТОРА
       Из этой таблицы считаем:
       - % диалогов решённых AI без тикета (цель: 70%)
       - % принятых AI-тикетов пользователями
       - % пользователей написавших свой вариант
       - динамику точности по времени
       Всё это — конкретные цифры для питч-дека.

    2. ДАТАСЕТ ДЛЯ ДООБУЧЕНИЯ
       Каждая строка с agent_corrected_category — обучающий пример.
       user_feedback = "not_helped" → сигнал что модель ошиблась.

    3. ОБЪЯСНИМОСТЬ
       Показываем комиссии: что модель решила, почему, как оценили.

    outcome — итог взаимодействия AI с пользователем:
      resolved_by_ai           — AI ответил, пользователь доволен
      escalated_ai_ticket      — AI создал тикет, пользователь принял
      escalated_user_ticket    — пользователь написал свой вариант тикета
      declined                 — пользователь отказался от помощи
    """
    __tablename__ = "ai_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    ticket_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Диалог из которого вырос этот лог
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Решение модели ─────────────────────────────────────────────────────────
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    predicted_category: Mapped[str] = mapped_column(String(100), nullable=False)
    predicted_priority: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    routed_to_agent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    ai_response_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ──────────────────────────────────────────────────────────────────────────

    # ── Итог взаимодействия ────────────────────────────────────────────────────
    # resolved_by_ai | escalated_ai_ticket | escalated_user_ticket | declined
    outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Пользователь отказался от тикета предложенного AI
    ticket_declined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Оценка пользователя: "helped" | "not_helped" | None (не оценил)
    user_feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # ──────────────────────────────────────────────────────────────────────────

    # ── Обратная связь от агента ───────────────────────────────────────────────
    routing_was_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    agent_corrected_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    agent_accepted_ai_response: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    correction_lag_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Время ответа AI Service в миллисекундах — питч-дек обещает "1,01 сек",
    # этот столбец даёт честную цифру из прода.
    ai_response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ──────────────────────────────────────────────────────────────────────────

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    ticket: Mapped[Optional["Ticket"]] = relationship("Ticket", back_populates="logs")
    routed_to_agent: Mapped[Optional["Agent"]] = relationship("Agent")
