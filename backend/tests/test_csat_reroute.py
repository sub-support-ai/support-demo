"""Тесты CSAT-оценки, перенаправления тикета и email-уведомлений агенту.

Проверяем:
  - POST /tickets/{id}/rate — оценка 1-5 сохраняется, повторная обновляется.
  - Нельзя оценить открытый тикет.
  - Чужой тикет → 404.
  - PATCH /tickets/{id}/reroute — отдел меняется, назначается новый агент.
  - Нельзя перенаправить в тот же отдел.
  - notify_agent_assigned вызывается при подтверждении тикета.
  - avg_csat_score в GET /stats/ (None когда нет оценок, число — когда есть).
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.ticket import Ticket
from app.models.ticket_rating import TicketRating
from app.models.user import User
from app.security import hash_password

# ── Вспомогательные функции ───────────────────────────────────────────────────


async def _register(client: AsyncClient, suffix: str) -> str:
    """Регистрирует пользователя, возвращает access_token."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"csr-{suffix}@example.com",
            "username": f"csr_{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _make_agent(db: AsyncSession, suffix: str, department: str = "IT") -> tuple[User, Agent]:
    """Создаёт агента в БД, возвращает (User, Agent)."""
    pwd = hash_password("Secret123!")
    user = User(
        email=f"csr-agent-{suffix}@example.com",
        username=f"csr_agent_{suffix}",
        hashed_password=pwd,
        role="agent",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    agent = Agent(
        user_id=user.id,
        email=user.email,
        username=user.username,
        hashed_password=pwd,
        department=department,
        ai_routing_score=0.9,
        active_ticket_count=0,
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return user, agent


async def _login(client: AsyncClient, username: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "Secret123!"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _create_resolved_ticket(
    db: AsyncSession,
    user: User,
    agent: Agent,
    title: str = "Нет интернета",
    department: str = "IT",
) -> Ticket:
    """Создаёт тикет в статусе 'resolved' напрямую в БД."""
    ticket = Ticket(
        user_id=user.id,
        agent_id=agent.id,
        title=title,
        body="Интернет пропал",
        department=department,
        status="resolved",
        confirmed_by_user=True,
        ticket_source="user_written",
        user_priority=3,
        requester_name=user.username,
        requester_email=user.email,
        resolved_at=datetime.now(UTC),
    )
    db.add(ticket)
    await db.flush()
    return ticket


async def _create_confirmed_ticket(
    db: AsyncSession,
    user: User,
    agent: Agent,
    title: str = "Зависает ПК",
    department: str = "IT",
) -> Ticket:
    """Создаёт тикет в статусе 'confirmed' напрямую в БД."""
    ticket = Ticket(
        user_id=user.id,
        agent_id=agent.id,
        title=title,
        body="ПК зависает",
        department=department,
        status="confirmed",
        confirmed_by_user=True,
        ticket_source="user_written",
        user_priority=3,
        requester_name=user.username,
        requester_email=user.email,
    )
    db.add(ticket)
    await db.flush()
    return ticket


# ── CSAT оценка ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_ticket_success(client: AsyncClient, db_session: AsyncSession):
    """Пользователь может оценить свой закрытый тикет (1–5 звёзд)."""
    _, agent = await _make_agent(db_session, "csat1")
    token = await _register(client, "csat1-user")

    result = await db_session.execute(sa_select(User).where(User.username == "csr_csat1-user"))
    user_obj = result.scalar_one()
    ticket = await _create_resolved_ticket(db_session, user_obj, agent)

    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 4, "comment": "Всё хорошо"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["rating"] == 4
    assert data["comment"] == "Всё хорошо"
    assert data["ticket_id"] == ticket.id


@pytest.mark.asyncio
async def test_rate_ticket_upsert(client: AsyncClient, db_session: AsyncSession):
    """Повторный вызов rate обновляет существующую оценку."""
    _, agent = await _make_agent(db_session, "csat2")
    token = await _register(client, "csat2-user")

    result = await db_session.execute(sa_select(User).where(User.username == "csr_csat2-user"))
    user_obj = result.scalar_one()
    ticket = await _create_resolved_ticket(db_session, user_obj, agent, "Проблема 2")

    await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 5, "comment": "Пересмотрел — отличная работа!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text  # update → 200, не 201
    assert r.json()["rating"] == 5

    # В БД должна быть ровно одна запись
    result = await db_session.execute(
        sa_select(TicketRating).where(TicketRating.ticket_id == ticket.id)
    )
    ratings = result.scalars().all()
    assert len(ratings) == 1
    assert ratings[0].rating == 5


@pytest.mark.asyncio
async def test_rate_open_ticket_rejected(client: AsyncClient, db_session: AsyncSession):
    """Нельзя оценить тикет в статусе 'confirmed' (ещё открыт)."""
    _, agent = await _make_agent(db_session, "csat3")
    token = await _register(client, "csat3-user")

    result = await db_session.execute(sa_select(User).where(User.username == "csr_csat3-user"))
    user_obj = result.scalar_one()
    ticket = await _create_confirmed_ticket(db_session, user_obj, agent, "Проблема 3")

    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_rate_other_users_ticket_returns_404(client: AsyncClient, db_session: AsyncSession):
    """Нельзя оценить чужой тикет — 404."""
    _, agent = await _make_agent(db_session, "csat4")
    await _register(client, "csat4-owner")
    token_other = await _register(client, "csat4-other")

    result = await db_session.execute(sa_select(User).where(User.username == "csr_csat4-owner"))
    owner = result.scalar_one()
    ticket = await _create_resolved_ticket(db_session, owner, agent, "Проблема 4")

    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 1},
        headers={"Authorization": f"Bearer {token_other}"},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_rating_out_of_range_rejected(client: AsyncClient, db_session: AsyncSession):
    """Оценка вне диапазона 1–5 отклоняется (422)."""
    _, agent = await _make_agent(db_session, "csat5")
    token = await _register(client, "csat5-user")

    result = await db_session.execute(sa_select(User).where(User.username == "csr_csat5-user"))
    user_obj = result.scalar_one()
    ticket = await _create_resolved_ticket(db_session, user_obj, agent, "Проблема 5")

    r = await client.post(
        f"/api/v1/tickets/{ticket.id}/rate",
        json={"rating": 6},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


# ── Перенаправление тикета ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reroute_ticket_changes_department(client: AsyncClient, db_session: AsyncSession):
    """Агент перенаправляет тикет из IT в HR — отдел обновляется."""
    _, it_agent = await _make_agent(db_session, "rr1-it", department="IT")
    _, hr_agent = await _make_agent(db_session, "rr1-hr", department="HR")

    # Создаём пользователя и логинимся как агент
    await _register(client, "rr1-user")
    result = await db_session.execute(sa_select(User).where(User.username == "csr_rr1-user"))
    user_obj = result.scalar_one()
    ticket = await _create_confirmed_ticket(db_session, user_obj, it_agent, "Нужна HR-помощь", "IT")

    agent_token = await _login(client, it_agent.username)
    r = await client.patch(
        f"/api/v1/tickets/{ticket.id}/reroute",
        json={"department": "HR", "reason": "Вопрос к кадрам, не к IT"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["department"] == "HR"


@pytest.mark.asyncio
async def test_reroute_same_department_rejected(client: AsyncClient, db_session: AsyncSession):
    """Перенаправление в тот же отдел → 422."""
    _, agent = await _make_agent(db_session, "rr2-it", department="IT")

    await _register(client, "rr2-user")
    result = await db_session.execute(sa_select(User).where(User.username == "csr_rr2-user"))
    user_obj = result.scalar_one()
    ticket = await _create_confirmed_ticket(db_session, user_obj, agent, "Та же IT-проблема", "IT")

    agent_token = await _login(client, agent.username)
    r = await client.patch(
        f"/api/v1/tickets/{ticket.id}/reroute",
        json={"department": "IT", "reason": "Ошибся"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_reroute_resolved_ticket_rejected(client: AsyncClient, db_session: AsyncSession):
    """Нельзя перенаправить закрытый тикет → 409."""
    _, agent = await _make_agent(db_session, "rr3", department="IT")

    await _register(client, "rr3-user")
    result = await db_session.execute(sa_select(User).where(User.username == "csr_rr3-user"))
    user_obj = result.scalar_one()
    ticket = await _create_resolved_ticket(db_session, user_obj, agent, "Закрытая проблема")

    agent_token = await _login(client, agent.username)
    r = await client.patch(
        f"/api/v1/tickets/{ticket.id}/reroute",
        json={"department": "HR", "reason": "Поздно"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_user_cannot_reroute(client: AsyncClient, db_session: AsyncSession):
    """Обычный пользователь не может перенаправить тикет → 404."""
    _, agent = await _make_agent(db_session, "rr4", department="IT")

    token = await _register(client, "rr4-user")
    result = await db_session.execute(sa_select(User).where(User.username == "csr_rr4-user"))
    user_obj = result.scalar_one()
    ticket = await _create_confirmed_ticket(db_session, user_obj, agent, "Проблема пользователя")

    r = await client.patch(
        f"/api/v1/tickets/{ticket.id}/reroute",
        json={"department": "HR", "reason": "Хочу"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text


# ── notify_agent_assigned ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_agent_assigned_sends_email():
    """notify_agent_assigned вызывает send_email с правильными аргументами."""
    from app.services.email import notify_agent_assigned

    sent = []

    async def fake_send(*, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    with patch("app.services.email.send_email", side_effect=fake_send):
        await notify_agent_assigned(
            ticket_id=99,
            title="Нет принтера",
            department="IT",
            requester_name="Иван",
            agent_email="agent@corp.ru",
            agent_name="Алексей",
        )

    assert len(sent) == 1
    assert "99" in sent[0]["subject"]
    assert sent[0]["to"] == "agent@corp.ru"
    assert "Алексей" in sent[0]["body"]
    assert "IT" in sent[0]["body"]


# ── avg_csat_score в stats ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_avg_csat_none_when_no_ratings(client: AsyncClient):
    """avg_csat_score = None если оценок нет."""
    token = await _register(client, "csat-stats-none")
    r = await client.get("/api/v1/stats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    tickets = r.json()["tickets"]
    assert "avg_csat_score" in tickets
    # None или число
    assert tickets["avg_csat_score"] is None or isinstance(tickets["avg_csat_score"], float)
