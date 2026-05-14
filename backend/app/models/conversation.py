from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Текущий статус диалога
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )

    # Причина отказа — заполняется только при status = "declined"
    decline_reason: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    # Intake flow: catalog_code — код типа обращения из service_catalog
    # intake_fields — собранные поля + служебный ключ _last_asked
    catalog_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    intake_fields: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    user: Mapped["User"] = relationship("User")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation"
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket", back_populates="conversation"
    )
