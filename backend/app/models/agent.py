from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    # Только для статической типизации (избегаем циклических импортов на runtime)
    from app.models.ticket import Ticket
    from app.models.user import User


class Agent(Base):
    """
    Сотрудник отдела — обрабатывает тикеты от пользователей.

    Отделён от User намеренно: у агента есть принадлежность к отделу
    и метрики которые AI использует при роутинге тикетов.

    department        — отдел агента. Полный список — в
                        app/constants/departments.py (IT, HR, finance,
                        procurement, security, facilities, documents).
                        AI направляет тикет в нужный отдел на основе
                        классификации диалога локальным Mistral (через AI Service).

    active_ticket_count — сколько тикетов сейчас в работе у агента.
                          AI не направляет новые тикеты перегруженным агентам.

    ai_routing_score  — качество AI-роутинга (0.0–1.0).
                        Считается из ai_logs: как часто агент соглашался
                        с решением модели. Растёт по мере дообучения.
    """

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Отдел агента — основа для умной маршрутизации
    department: Mapped[str] = mapped_column(String(20), nullable=False, default="IT")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    active_ticket_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_routing_score: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="agent")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="agent_profile")
