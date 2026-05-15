"""
Модель правил автоматизации.

AutomationRule описывает «если … то …» логику, которая срабатывает
при определённых событиях над тикетом:

    trigger     — когда проверять (ticket_confirmed, ticket_reopened,
                  ticket_no_reply, ticket_escalated)
    conditions  — JSON-список условий на поля тикета (все AND)
    actions     — JSON-список действий, которые применяются при совпадении

Пример:
    {
      "trigger": "ticket_confirmed",
      "conditions": [
        {"field": "department", "op": "eq", "value": "security"},
        {"field": "request_type", "op": "contains", "value": "Фишинг"}
      ],
      "actions": [
        {"type": "set_ai_priority", "value": "критический"},
        {"type": "override_sla_minutes", "value": 15},
        {"type": "add_comment",
         "value": "Автоматика: фишинг → SOC flow, SLA 15 мин."}
      ]
    }

priority — порядок выполнения (меньше = раньше). Все совпавшие правила
           выполняются подряд, конфликты разрешаются приоритетом.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Чем меньше число -- тем раньше выполняется правило
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # Когда проверять правило
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # JSON-список условий. Каждое условие -- dict с ключами:
    #   "field" (str)  -- имя поля Ticket (department, ai_priority, ...)
    #   "op"    (str)  -- eq | neq | contains | not_contains |
    #                     gte | lte | gt | lt | in | is_empty | is_not_empty
    #   "value" (any)  -- значение для сравнения
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # JSON-список действий. Каждое действие -- dict с ключами:
    #   "type"  (str)  -- set_ai_priority | override_sla_minutes |
    #                     add_comment | reassign_department |
    #                     escalate_to_senior | set_field
    #   "value" (any)  -- аргумент действия
    #   "field" (str)  -- для set_field -- имя поля (опционально)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
