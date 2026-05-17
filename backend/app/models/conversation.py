from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.ticket import Ticket
    from app.models.user import User


class Conversation(Base):
    """
    Диалог пользователя с AI-ассистентом.

    Жизненный цикл status:
      active       — диалог идёт прямо сейчас
      resolved     — AI ответил и помог, проблема закрыта
      escalated    — создан тикет и отправлен в отдел
      user_writing — пользователь пишет свой вариант тикета
                     (отказался от предложения AI)
      declined     — пользователь отказался от помощи и закрыл чат

    decline_reason — причина отказа (только когда status = "declined"):
      solved_myself  — разобрался сам
      dont_need_help — не нужна помощь
      None           — закрыл без объяснений
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Текущий статус диалога
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)

    # Причина отказа — заполняется только при status = "declined"
    decline_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ПСЕВДО-СТРИМИНГ: текущая стадия обработки AI-ответа.
    # Значения: thinking / searching / found_kb / generating / None (idle).
    ai_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Intake flow: код типа обращения из service_catalog + собранные поля
    catalog_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intake_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Агрегированное состояние сбора данных для черновика (офис, тип, поля и т.д.).
    # Пересчитывается после каждого AI-ответа в generate_ai_message.
    # Используется фронтом для отображения прогресса заполнения формы запроса.
    intake_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    user: Mapped[User] = relationship("User")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="conversation")
    tickets: Mapped[list[Ticket]] = relationship("Ticket", back_populates="conversation")
