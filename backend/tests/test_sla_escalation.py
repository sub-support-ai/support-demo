from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.user import User
from app.security import hash_password
from app.services.sla import is_sla_breached
from app.services.sla_escalation import escalate_overdue_tickets


async def _create_user(db: AsyncSession, suffix: str, role: str = "user") -> User:
    user = User(
        email=f"sla-{suffix}@example.com",
        username=f"sla_{suffix}",
        hashed_password=hash_password("Secret123!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _create_agent(
    db: AsyncSession,
    suffix: str,
    *,
    routing_score: float,
    active_ticket_count: int,
    department: str = "IT",
) -> Agent:
    user = await _create_user(db, f"agent-{suffix}", role="agent")
    agent = Agent(
        user_id=user.id,
        email=user.email,
        username=user.username,
        hashed_password=user.hashed_password,
        department=department,
        ai_routing_score=routing_score,
        active_ticket_count=active_ticket_count,
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return agent


class _FakeTicket:
    def __init__(self, deadline, status="confirmed"):
        self.sla_deadline_at = deadline
        self.status = status


def test_sla_breach_check_handles_naive_deadline():
    now_aware = datetime.now(timezone.utc)
    deadline_naive = (now_aware - timedelta(minutes=1)).replace(tzinfo=None)
    assert is_sla_breached(_FakeTicket(deadline=deadline_naive), now=now_aware) is True


def test_sla_breach_check_handles_aware_deadline():
    now = datetime.now(timezone.utc)
    deadline = now - timedelta(minutes=1)
    assert is_sla_breached(_FakeTicket(deadline=deadline), now=now) is True


@pytest.mark.asyncio
async def test_sla_escalation_reassigns_overdue_ticket_to_senior_agent(
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc)
    requester = await _create_user(db_session, "requester")
    regular_agent = await _create_agent(
        db_session,
        "regular",
        routing_score=0.25,
        active_ticket_count=1,
    )
    senior_agent = await _create_agent(
        db_session,
        "senior",
        routing_score=0.95,
        active_ticket_count=0,
    )
    ticket = Ticket(
        user_id=requester.id,
        agent_id=regular_agent.id,
        title="Overdue equipment request",
        body="Monitor is not working",
        requester_name=requester.username,
        requester_email=requester.email,
        office="HQ",
        affected_item="Monitor",
        department="IT",
        status="confirmed",
        ticket_source="ai_generated",
        confirmed_by_user=True,
        user_priority=3,
        ai_priority="high",
        ai_confidence=0.9,
        sla_started_at=now - timedelta(hours=10),
        sla_deadline_at=now - timedelta(hours=1),
    )
    db_session.add(ticket)
    await db_session.flush()

    escalated = await escalate_overdue_tickets(db_session, now=now)

    assert escalated == 1
    assert ticket.agent_id == senior_agent.id
    assert ticket.sla_escalated_at == now
    assert ticket.sla_escalation_count == 1

    await db_session.refresh(regular_agent)
    await db_session.refresh(senior_agent)
    assert regular_agent.active_ticket_count == 0
    assert senior_agent.active_ticket_count == 1

    comments = (
        await db_session.execute(
            select(TicketComment).where(TicketComment.ticket_id == ticket.id)
        )
    ).scalars().all()
    assert len(comments) == 1
    assert comments[0].author_role == "system"
    assert comments[0].internal is True
    assert "SLA просрочен" in comments[0].content
    assert senior_agent.username in comments[0].content

    notifications = (
        await db_session.execute(
            select(Notification).where(Notification.target_id == ticket.id)
        )
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].user_id == senior_agent.user_id
    assert notifications[0].event_type == "ticket.sla_overdue"

    assert await escalate_overdue_tickets(db_session, now=now) == 0


@pytest.mark.asyncio
async def test_sla_escalation_atomic_counters_on_repeated_call(
    db_session: AsyncSession,
):
    """Два последовательных вызова escalate_overdue_tickets:
    первый эскалирует, второй — no-op. Счётчики агентов должны
    измениться ровно один раз, системный комментарий — один.
    """
    now = datetime.now(timezone.utc)
    requester = await _create_user(db_session, "atomic-requester")
    regular_agent = await _create_agent(
        db_session, "atomic-regular", routing_score=0.3, active_ticket_count=2
    )
    senior_agent = await _create_agent(
        db_session, "atomic-senior", routing_score=0.9, active_ticket_count=0
    )
    ticket = Ticket(
        user_id=requester.id,
        agent_id=regular_agent.id,
        title="Atomic counter test",
        body="SLA breached",
        requester_name=requester.username,
        requester_email=requester.email,
        office="HQ",
        affected_item="Laptop",
        department="IT",
        status="confirmed",
        ticket_source="ai_generated",
        confirmed_by_user=True,
        user_priority=3,
        ai_priority="high",
        ai_confidence=0.9,
        sla_started_at=now - timedelta(hours=12),
        sla_deadline_at=now - timedelta(hours=2),
    )
    db_session.add(ticket)
    await db_session.flush()

    first = await escalate_overdue_tickets(db_session, now=now)
    second = await escalate_overdue_tickets(db_session, now=now)

    assert first == 1
    assert second == 0  # второй вызов ничего не находит — sla_escalated_at уже выставлен
    assert ticket.sla_escalation_count == 1

    await db_session.refresh(regular_agent)
    await db_session.refresh(senior_agent)
    assert regular_agent.active_ticket_count == 1   # было 2, уменьшился ровно на 1
    assert senior_agent.active_ticket_count == 1    # было 0, вырос ровно на 1

    system_comments = (
        await db_session.execute(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket.id)
            .where(TicketComment.author_role == "system")
        )
    ).scalars().all()
    assert len(system_comments) == 1


@pytest.mark.asyncio
async def test_sla_escalation_skips_unconfirmed_drafts(db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    requester = await _create_user(db_session, "draft-requester")
    agent = await _create_agent(
        db_session,
        "draft-agent",
        routing_score=0.95,
        active_ticket_count=0,
    )
    ticket = Ticket(
        user_id=requester.id,
        agent_id=agent.id,
        title="Draft request",
        body="User has not confirmed this request yet",
        requester_name=requester.username,
        requester_email=requester.email,
        office="HQ",
        affected_item="Laptop",
        department="IT",
        status="pending_user",
        ticket_source="ai_generated",
        confirmed_by_user=False,
        user_priority=3,
        ai_priority="high",
        ai_confidence=0.9,
        sla_started_at=now - timedelta(hours=10),
        sla_deadline_at=now - timedelta(hours=1),
    )
    db_session.add(ticket)
    await db_session.flush()

    assert await escalate_overdue_tickets(db_session, now=now) == 0
    assert ticket.agent_id == agent.id
    assert ticket.sla_escalated_at is None
    assert ticket.sla_escalation_count == 0
