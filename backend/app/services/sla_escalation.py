from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.services.notifications import create_notification, notify_active_admins
from app.services.sla import OPEN_STATUSES


async def find_senior_agent_for_ticket(
    db: AsyncSession,
    ticket: Ticket,
) -> Agent | None:
    result = await db.execute(
        select(Agent)
        .where(Agent.department == ticket.department)
        .where(Agent.is_active.is_(True))
        .order_by(Agent.ai_routing_score.desc(), Agent.active_ticket_count.asc(), Agent.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def escalate_overdue_ticket(
    db: AsyncSession,
    ticket: Ticket,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(UTC)
    senior_agent = await find_senior_agent_for_ticket(db, ticket)
    if senior_agent is None:
        return False

    previous_agent_id = ticket.agent_id
    if previous_agent_id != senior_agent.id:
        if previous_agent_id is not None:
            # Атомарный декремент — нет race condition при параллельной
            # эскалации нескольких тикетов. WHERE count > 0 предотвращает
            # уход в отрицательные значения.
            await db.execute(
                update(Agent)
                .where(Agent.id == previous_agent_id)
                .where(Agent.active_ticket_count > 0)
                .values(active_ticket_count=Agent.active_ticket_count - 1)
            )

        # Атомарный инкремент старшего агента.
        await db.execute(
            update(Agent)
            .where(Agent.id == senior_agent.id)
            .values(active_ticket_count=Agent.active_ticket_count + 1)
        )
        ticket.agent_id = senior_agent.id

    ticket.sla_escalated_at = current_time
    ticket.sla_escalation_count += 1

    if senior_agent.user_id is not None:
        await create_notification(
            db,
            user_id=senior_agent.user_id,
            event_type="ticket.sla_overdue",
            title="SLA запроса просрочен",
            body=f"{ticket.department}: {ticket.title}",
            target_type="ticket",
            target_id=ticket.id,
        )
    else:
        await notify_active_admins(
            db,
            event_type="ticket.sla_overdue_unassigned",
            title="SLA просрочен, но у агента нет учетной записи",
            body=f"{ticket.department}: {ticket.title}",
            target_type="ticket",
            target_id=ticket.id,
        )

    if previous_agent_id == senior_agent.id:
        content = (
            "SLA просрочен. Запрос уже назначен старшему специалисту отдела, "
            "повторное переназначение не требуется."
        )
    else:
        content = (
            "SLA просрочен. Запрос автоматически эскалирован старшему специалисту "
            f"отдела: {senior_agent.username}."
        )

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
    await db.flush()

    # Автоматизация: правила, привязанные к эскалации SLA
    # (например: добавить тег, уведомить отдел, изменить приоритет).
    # Вызываем после flush, чтобы правила видели обновлённое состояние тикета.
    try:
        from app.services.automation import TRIGGER_TICKET_ESCALATED, run_automation

        await run_automation(TRIGGER_TICKET_ESCALATED, ticket, db)
    except Exception:
        pass  # не блокируем основную эскалацию

    return True


async def escalate_overdue_tickets(
    db: AsyncSession,
    limit: int = 50,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(UTC)
    result = await db.execute(
        select(Ticket)
        .where(
            Ticket.status.in_(tuple(OPEN_STATUSES)),
            Ticket.confirmed_by_user.is_(True),
            Ticket.sla_deadline_at.is_not(None),
            Ticket.sla_deadline_at < current_time,
            Ticket.sla_escalated_at.is_(None),
        )
        .order_by(Ticket.sla_deadline_at.asc(), Ticket.id.asc())
        # skip_locked: параллельный cron-воркер пропустит уже обрабатываемые
        # тикеты, вместо того чтобы эскалировать их дважды.
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    tickets = result.scalars().all()

    escalated = 0
    for ticket in tickets:
        if await escalate_overdue_ticket(db, ticket, current_time):
            escalated += 1
    return escalated
