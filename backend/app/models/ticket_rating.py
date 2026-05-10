"""Модель оценки тикета пользователем (CSAT).

Пользователь ставит оценку 1–5 звёзд после того, как тикет перешёл
в статус resolved или closed. Одна запись на тикет — повторная оценка
перезаписывает предыдущую (UPSERT через unique constraint на ticket_id).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TicketRating(Base):
    """CSAT-оценка (1–5) от пользователя после закрытия тикета."""

    __tablename__ = "ticket_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Один тикет — одна оценка (уникальный FK → позволяет UPSERT по ticket_id)
    ticket_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Оценка 1–5 (Customer Satisfaction Score)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)

    # Необязательный текстовый комментарий к оценке
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="rating")
    user: Mapped["User"] = relationship("User")
