from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.ai_log import AILog
    from app.models.asset import Asset
    from app.models.conversation import Conversation
    from app.models.response import Response
    from app.models.ticket_comment import TicketComment
    from app.models.ticket_rating import TicketRating
    from app.models.user import User


class Ticket(Base):
    """
    Заявка в отдел — создаётся автоматически AI или вручную пользователем.

    Жизненный цикл статуса:
      new            → тикет создан, ждёт подтверждения пользователя
      pending_user   → AI предложил тикет, ждём подтверждения
      confirmed      → пользователь подтвердил, тикет отправлен в отдел
      in_progress    → агент взял в работу
      resolved       → агент решил проблему
      closed         → закрыт

    ticket_source — кто и как создал тикет:
      "ai_generated"  — AI сформировал автоматически из диалога
      "user_written"  — пользователь написал сам после отказа от AI-варианта
      "ai_assisted"   — пользователь написал, AI помог с отделом и приоритетом

    department — куда направить тикет. Полный список — в
      app/constants/departments.py (IT, HR, finance, procurement,
      security, facilities, documents). AI определяет автоматически,
      пользователь может изменить.

    confirmed_by_user — подтвердил ли пользователь отправку.
      False = тикет создан но ещё не отправлен (ждёт подтверждения)
      True  = пользователь нажал "Отправить", тикет ушёл в отдел

    steps_tried — что пользователь уже пробовал.
      AI извлекает это из диалога автоматически.
      Помогает агенту не предлагать то что уже не помогло.

    AI-поля заполняются после классификации диалога локальным Mistral
    (через AI Service, self-hosted):
      ai_category     — категория проблемы
      ai_priority     — приоритет: "критический"|"высокий"|"средний"|"низкий"
      ai_confidence   — уверенность модели (0.0–1.0)
                        если < 0.8 → помечаем для проверки агентом
      ai_processed_at — когда AI обработал (метрика скорости пайплайна)
    """

    __tablename__ = "tickets"
    __table_args__ = (
        # Ускоряет запросы агента к «своим» тикетам по статусу и SLA-воркер.
        Index("ix_tickets_agent_id_status", "agent_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Агент назначается после подтверждения пользователем
    agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Из какого диалога создан тикет
    conversation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Ссылка на CMDB-объект; NULL — когда актив не внесён в базу.
    # affected_item остаётся как free-text fallback для старых тикетов и
    # объектов, которых ещё нет в CMDB.
    asset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    requester_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requester_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    affected_item: Mapped[str | None] = mapped_column(String(150), nullable=True)
    request_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    request_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Что пользователь уже пробовал — AI извлекает из диалога
    steps_tried: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Куда направить тикет — AI предлагает, пользователь может изменить
    department: Mapped[str] = mapped_column(String(20), nullable=False, default="IT")

    status: Mapped[str] = mapped_column(
        String(30), default="pending_user", nullable=False, index=True
    )
    ticket_kind: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="incident",
        server_default=text("'incident'"),
        index=True,
    )

    # Кто и как создал тикет
    ticket_source: Mapped[str] = mapped_column(String(20), default="ai_generated", nullable=False)

    # Подтвердил ли пользователь отправку (1 клик)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Приоритет выставленный пользователем (1–5) — если писал вручную
    user_priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # ── AI-поля (локальный Mistral через AI Service) ─────────────────────────
    # Заполняются после классификации обращения. AI Service крутится в
    # контейнере рядом (Ollama / llama.cpp), данные не выходят за периметр
    # заказчика — требование безопасности для self-hosted развёртывания.
    ai_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Текстовый приоритет от модели: критический|высокий|средний|низкий
    ai_priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ──────────────────────────────────────────────────────────────────────────

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Время первого ответа агента — для метрики TTFR (Time To First Response).
    # Проставляется при создании первого комментария агента/системы к тикету.
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    sla_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    sla_escalation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="tickets")
    asset: Mapped[Optional["Asset"]] = relationship(
        "Asset", back_populates="tickets", lazy="selectin"
    )
    agent: Mapped[Optional["Agent"]] = relationship("Agent", back_populates="tickets")
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="tickets"
    )
    responses: Mapped[list["Response"]] = relationship("Response", back_populates="ticket")
    logs: Mapped[list["AILog"]] = relationship("AILog", back_populates="ticket")
    comments: Mapped[list["TicketComment"]] = relationship(
        "TicketComment",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )
    rating: Mapped[Optional["TicketRating"]] = relationship(
        "TicketRating",
        back_populates="ticket",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def is_sla_breached(self) -> bool:
        from app.services.sla import is_sla_breached

        return is_sla_breached(self)
