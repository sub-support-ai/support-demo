"""
Движок правил автоматизации.

Публичный API:
    run_automation(trigger, ticket, db)
        — загружает все активные правила для данного trigger,
          оценивает условия, применяет действия совпавших правил.

Условия (conditions):
    field:  имя атрибута модели Ticket (department, ai_priority, ...)
    op:     eq | neq | contains | not_contains |
            gte | lte | gt | lt | in | is_empty | is_not_empty
    value:  скалярное значение или список (для op=in)

Действия (actions):
    type: set_ai_priority      — меняет ticket.ai_priority и пересчитывает SLA
    type: override_sla_minutes — устанавливает новый дедлайн SLA (от сейчас)
    type: add_comment          — добавляет системный комментарий к тикету
    type: reassign_department  — меняет отдел и перероутит на нового агента
    type: escalate_to_senior   — немедленная эскалация к старшему агенту
    type: set_field            — устанавливает произвольное строковое поле
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

# ── Триггеры ──────────────────────────────────────────────────────────────────

TRIGGER_TICKET_CONFIRMED = "ticket_confirmed"
TRIGGER_TICKET_REOPENED = "ticket_reopened"
TRIGGER_TICKET_NO_REPLY = "ticket_no_reply"
TRIGGER_TICKET_ESCALATED = "ticket_escalated"

ALL_TRIGGERS = {
    TRIGGER_TICKET_CONFIRMED,
    TRIGGER_TICKET_REOPENED,
    TRIGGER_TICKET_NO_REPLY,
    TRIGGER_TICKET_ESCALATED,
}


# ── Оценка условий ────────────────────────────────────────────────────────────


def _get_field_value(ticket: Ticket, field: str) -> Any:
    """Возвращает значение поля тикета. Безопасно: None если поля нет."""
    return getattr(ticket, field, None)


def _evaluate_condition(condition: dict, ticket: Ticket) -> bool:
    """Возвращает True если одно условие выполнено для данного тикета."""
    field = condition.get("field", "")
    op = condition.get("op", "eq")
    expected = condition.get("value")

    actual = _get_field_value(ticket, field)

    try:
        if op == "eq":
            return (
                str(actual).lower() == str(expected).lower()
                if actual is not None
                else expected is None
            )
        if op == "neq":
            return str(actual).lower() != str(expected).lower()
        if op == "contains":
            return expected is not None and str(expected).lower() in str(actual or "").lower()
        if op == "not_contains":
            return expected is None or str(expected).lower() not in str(actual or "").lower()
        if op == "gte":
            return float(actual or 0) >= float(expected)
        if op == "lte":
            return float(actual or 0) <= float(expected)
        if op == "gt":
            return float(actual or 0) > float(expected)
        if op == "lt":
            return float(actual or 0) < float(expected)
        if op == "in":
            if not isinstance(expected, list):
                return False
            return str(actual).lower() in [str(v).lower() for v in expected]
        if op == "is_empty":
            return actual is None or str(actual).strip() == ""
        if op == "is_not_empty":
            return actual is not None and str(actual).strip() != ""
    except (TypeError, ValueError):
        logger.warning(
            "Automation: ошибка оценки условия",
            extra={"field": field, "op": op, "actual": actual, "expected": expected},
        )
        return False

    logger.warning("Automation: неизвестный оператор условия", extra={"op": op})
    return False


def evaluate_conditions(conditions: list[dict], ticket: Ticket) -> bool:
    """Возвращает True если ВСЕ условия (AND) выполнены."""
    if not conditions:
        return True  # нет условий → всегда срабатывает
    return all(_evaluate_condition(c, ticket) for c in conditions)


# ── Применение действий ───────────────────────────────────────────────────────


async def _execute_action(action: dict, ticket: Ticket, db: AsyncSession) -> None:
    action_type = action.get("type", "")
    value = action.get("value")

    if action_type == "set_ai_priority":
        _set_priority(ticket, str(value))

    elif action_type == "override_sla_minutes":
        _override_sla(ticket, int(value))

    elif action_type == "add_comment":
        await _add_system_comment(ticket, str(value), db)

    elif action_type == "reassign_department":
        await _reassign_department(ticket, str(value), db)

    elif action_type == "escalate_to_senior":
        await _escalate_to_senior(ticket, db)

    elif action_type == "set_field":
        field_name = action.get("field")
        if field_name and hasattr(ticket, field_name):
            setattr(ticket, field_name, value)
        else:
            logger.warning(
                "Automation: set_field — поле не найдено",
                extra={"field": field_name},
            )

    else:
        logger.warning("Automation: неизвестный тип действия", extra={"type": action_type})


def _set_priority(ticket: Ticket, priority: str) -> None:
    from app.services.sla import start_ticket_sla

    ticket.ai_priority = priority
    # Пересчитываем SLA-дедлайн под новый приоритет, если SLA уже стартовал
    if ticket.sla_started_at is not None:
        start_ticket_sla(ticket, started_at=ticket.sla_started_at)
    logger.info(
        "Automation: приоритет изменён",
        extra={"ticket_id": ticket.id, "priority": priority},
    )


def _override_sla(ticket: Ticket, minutes: int) -> None:
    now = datetime.now(UTC)
    ticket.sla_deadline_at = now + timedelta(minutes=minutes)
    if ticket.sla_started_at is None:
        ticket.sla_started_at = now
    logger.info(
        "Automation: SLA переопределён",
        extra={"ticket_id": ticket.id, "minutes": minutes},
    )


async def _add_system_comment(ticket: Ticket, content: str, db: AsyncSession) -> None:
    from app.models.ticket_comment import TicketComment

    db.add(
        TicketComment(
            ticket_id=ticket.id,
            author_id=ticket.user_id,
            author_username="system",
            author_role="system",
            content=content,
            internal=True,
        )
    )
    logger.info(
        "Automation: системный комментарий добавлен",
        extra={"ticket_id": ticket.id},
    )


async def _reassign_department(ticket: Ticket, department: str, db: AsyncSession) -> None:
    from app.services.routing import assign_agent, unassign_agent

    old_dept = ticket.department
    ticket.department = department

    # Освобождаем текущего агента и назначаем нового из нужного отдела
    if ticket.agent_id is not None:
        await unassign_agent(db, ticket)
        ticket.agent_id = None

    if ticket.status not in ("pending_user", "declined"):
        await assign_agent(db, ticket)

    logger.info(
        "Automation: отдел переназначен",
        extra={"ticket_id": ticket.id, "from": old_dept, "to": department},
    )


async def _escalate_to_senior(ticket: Ticket, db: AsyncSession) -> None:
    from app.services.sla_escalation import escalate_overdue_ticket

    escalated = await escalate_overdue_ticket(db, ticket)
    if escalated:
        logger.info(
            "Automation: эскалация к старшему агенту",
            extra={"ticket_id": ticket.id},
        )


# ── Главная точка входа ───────────────────────────────────────────────────────


async def run_automation(
    trigger: str,
    ticket: Ticket,
    db: AsyncSession,
) -> int:
    """
    Запускает все активные правила для данного trigger и тикета.

    Порядок: по полю priority ASC (меньше = раньше).
    Все совпавшие правила выполняются — не только первое.

    Возвращает количество сработавших правил.
    """
    from app.models.automation_rule import AutomationRule

    result = await db.execute(
        select(AutomationRule)
        .where(AutomationRule.trigger == trigger)
        .where(AutomationRule.is_active.is_(True))
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
    )
    rules = result.scalars().all()

    if not rules:
        return 0

    fired = 0
    for rule in rules:
        try:
            if not evaluate_conditions(rule.conditions, ticket):
                continue

            logger.info(
                "Automation: правило сработало",
                extra={"rule_id": rule.id, "rule_name": rule.name, "ticket_id": ticket.id},
            )

            for action in rule.actions:
                await _execute_action(action, ticket, db)

            fired += 1

        except Exception:
            logger.exception(
                "Automation: ошибка выполнения правила",
                extra={"rule_id": rule.id, "ticket_id": ticket.id},
            )

    return fired
