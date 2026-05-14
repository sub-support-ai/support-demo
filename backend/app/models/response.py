from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Response(Base):
    """
    Ответ на тикет. Два типа:

    source = "ai"    — черновик от локального Mistral (через AI Service),
                       создаётся автоматически.
    source = "agent" — финальный ответ агента. Агент либо принимает
                       AI-черновик, либо пишет свой.

    is_sent = True   — этот ответ был отправлен пользователю.

    ai_draft_id      — ссылка на AI-черновик который агент видел.
                       Нужна для ai_logs: сравниваем предложение модели
                       с финальным ответом → датасет для дообучения.
    """

    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )

    # "ai" или "agent"
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Какой AI-черновик видел агент перед тем как написать свой ответ
    ai_draft_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("responses.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # БАГ 6 ИСПРАВЛЕН: добавлен updated_at — нужен чтобы отслеживать
    # когда агент редактировал черновик перед отправкой
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="responses")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")
