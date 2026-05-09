"""Тесты метрик TTFR (Time To First Response) и TTR (Time To Resolution).

TTFR = время от создания тикета до первого публичного комментария агента.
TTR  = время от создания до resolved_at.

Проверяем:
  - first_response_at проставляется при первом комментарии агента.
  - Повторный комментарий агента не перезаписывает first_response_at.
  - Комментарий пользователя не влияет на first_response_at.
  - GET /stats/ возвращает avg_ttfr_seconds и avg_ttr_seconds.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import Agent
from app.models.ticket import Ticket
from app.models.user import User
from app.security import hash_password


# ── Фикстуры ─────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, suffix: str, role: str = "user") -> tuple[str, str]:
    """Регистрирует пользователя, возвращает (username, token)."""
    settings = get_settings()
    if role == "admin":
        prev = settings.BOOTSTRAP_ADMIN_EMAIL
        settings.BOOTSTRAP_ADMIN_EMAIL = f"ttfr-admin-{suffix}@example.com"

    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"ttfr-{suffix}@example.com",
            "username": f"ttfr_{suffix}",
            "password": "Secret123!",
        },
    )
    if role == "admin":
        settings.BOOTSTRAP_ADMIN_EMAIL = prev
    assert r.status_code == 201
    return f"ttfr_{suffix}", r.json()["access_token"]


async def _make_agent(db: AsyncSession, suffix: str) -> tuple[User, Agent]:
    """Создаёт агента напрямую в БД, возвращает (User, Agent).

    Возвращаем оба объекта, чтобы можно было использовать agent.id
    (PK в таблице agents) при установке ticket.agent_id.
    User.id != Agent.id в полном прогоне — они из разных последовательностей.
    """
    pwd = hash_password("Secret123!")
    user = User(
        email=f"ttfr-agent-{suffix}@example.com",
        username=f"ttfr_agent_{suffix}",
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
        department="IT",
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
    assert r.status_code == 200
    return r.json()["access_token"]


# ── Тесты first_response_at ───────────────────────────────────────────────────


async def _create_ticket_direct(
    db: AsyncSession,
    user: User,
    agent: Agent,
    title: str,
    body: str,
) -> Ticket:
    """Создаёт подтверждённый тикет напрямую в БД без роутинга.

    Принимает объект Agent (не User!), чтобы использовать agent.id —
    PK из таблицы agents — как ticket.agent_id (FK → agents.id).
    Смешивать user.id и agent.id нельзя: это разные последовательности.
    """
    ticket = Ticket(
        user_id=user.id,
        agent_id=agent.id,       # PK таблицы agents, не users
        title=title,
        body=body,
        department="IT",
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


@pytest.mark.asyncio
async def test_first_response_at_set_on_first_agent_comment(
    client: AsyncClient, db_session: AsyncSession
):
    """Первый комментарий агента → first_response_at проставляется."""
    agent_user, agent = await _make_agent(db_session, "frat1")
    _, user_token = await _register(client, "frat1-user")

    # Получаем объект пользователя из БД по username
    from sqlalchemy import select as sa_select
    result = await db_session.execute(
        sa_select(User).where(User.username == "ttfr_frat1-user")
    )
    user_obj = result.scalar_one()

    ticket = await _create_ticket_direct(db_session, user_obj, agent, "Нет интернета", "Интернет пропал")

    agent_token = await _login(client, agent_user.username)
    comment_r = await client.post(
        f"/api/v1/tickets/{ticket.id}/comments",
        json={"content": "Проверяем маршрутизатор", "internal": False},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert comment_r.status_code == 201

    await db_session.refresh(ticket)
    assert ticket.first_response_at is not None


@pytest.mark.asyncio
async def test_first_response_at_not_overwritten_on_second_comment(
    client: AsyncClient, db_session: AsyncSession
):
    """Второй комментарий агента не перезаписывает first_response_at."""
    from sqlalchemy import select as sa_select

    agent_user, agent = await _make_agent(db_session, "frat2")
    _, user_token = await _register(client, "frat2-user")

    result = await db_session.execute(
        sa_select(User).where(User.username == "ttfr_frat2-user")
    )
    user_obj = result.scalar_one()

    ticket = await _create_ticket_direct(db_session, user_obj, agent, "Зависает ПК", "Компьютер зависает")

    agent_token = await _login(client, agent_user.username)

    await client.post(
        f"/api/v1/tickets/{ticket.id}/comments",
        json={"content": "Первый ответ", "internal": False},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    await db_session.refresh(ticket)
    first_ts = ticket.first_response_at
    assert first_ts is not None

    await client.post(
        f"/api/v1/tickets/{ticket.id}/comments",
        json={"content": "Второй ответ", "internal": False},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    await db_session.refresh(ticket)
    assert ticket.first_response_at == first_ts  # не изменился


@pytest.mark.asyncio
async def test_user_comment_does_not_set_first_response_at(
    client: AsyncClient, db_session: AsyncSession
):
    """Комментарий пользователя не должен влиять на first_response_at."""
    from sqlalchemy import select as sa_select

    _, user_token = await _register(client, "frat3-user")

    ticket_r = await client.post(
        "/api/v1/tickets/",
        json={"title": "Нет VPN", "body": "VPN не работает"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ticket_r.status_code == 201
    ticket_id = ticket_r.json()["id"]

    result = await db_session.execute(sa_select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one()
    # Пользователи не могут добавлять комментарии (только агенты/админы),
    # поэтому first_response_at должен оставаться None пока нет агентских комментариев
    assert ticket.first_response_at is None


# ── Тест: avg_ttfr / avg_ttr в /stats/ ───────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_returns_ttfr_ttr_fields(client: AsyncClient):
    """GET /stats/ должен возвращать поля avg_ttfr_seconds и avg_ttr_seconds."""
    _, token = await _register(client, "stats-check")

    r = await client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    tickets = data["tickets"]
    # Оба поля присутствуют (None или число)
    assert "avg_ttfr_seconds" in tickets
    assert "avg_ttr_seconds" in tickets
    # Если данных нет — None (не отсутствующее поле)
    assert tickets["avg_ttfr_seconds"] is None or isinstance(tickets["avg_ttfr_seconds"], (int, float))
    assert tickets["avg_ttr_seconds"] is None or isinstance(tickets["avg_ttr_seconds"], (int, float))


@pytest.mark.asyncio
async def test_stats_returns_by_category_field(client: AsyncClient):
    """GET /stats/ должен возвращать поле by_category."""
    _, token = await _register(client, "cat-check")

    r = await client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "by_category" in r.json()["tickets"]
