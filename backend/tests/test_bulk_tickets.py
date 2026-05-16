"""
Тесты POST /api/v1/tickets/bulk — массовое изменение статуса с защитой.

Что покрываем:
  - Auth required, operator only
  - force=True доступен только admin
  - applied / rejected — partial-success
  - Защита от риска: has_reopens, has_unread_user_msg, wrong_status, not_found
  - force=True обходит защиту
  - Max 100 ticket_ids (валидация)
  - Audit логируется
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.security import hash_password


# ── Хелперы ──────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, suffix: str) -> tuple[int, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"bulk{suffix}@example.com",
            "username": f"bulk{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


async def _register_admin(client: AsyncClient, suffix: str) -> tuple[int, str]:
    settings = get_settings()
    email = f"bulkadmin{suffix}@example.com"
    prev = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = email
    try:
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": f"bulkadmin{suffix}",
                "password": "Secret123!",
            },
        )
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = prev
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "admin"
    return me.json()["id"], token


async def _make_agent_user(
    client: AsyncClient, db: AsyncSession, suffix: str
) -> tuple[int, str]:
    """Регистрирует пользователя и повышает его до agent."""
    user_id, token = await _register(client, f"a{suffix}")
    user = await db.get(User, user_id)
    assert user is not None
    user.role = "agent"
    agent = Agent(
        user_id=user_id,
        email=f"bulkagent{suffix}@example.com",
        username=f"bulkagent{suffix}",
        hashed_password=hash_password("Secret123!"),
        department="IT",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return user_id, token


def _make_ticket(
    user_id: int,
    *,
    status: str = "in_progress",
    reopen_count: int = 0,
    confirmed_by_user: bool = True,
    conversation_id: int | None = None,
) -> Ticket:
    return Ticket(
        user_id=user_id,
        title="test",
        body="...",
        user_priority=3,
        department="IT",
        status=status,
        confirmed_by_user=confirmed_by_user,
        reopen_count=reopen_count,
        conversation_id=conversation_id,
        sla_started_at=datetime.now(UTC),
    )


# ── Auth и роли ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_requires_auth(client: AsyncClient):
    r = await client.post("/api/v1/tickets/bulk", json={"ticket_ids": [1], "action": "closed"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bulk_forbidden_for_regular_user(client: AsyncClient):
    _, token = await _register(client, "u1")
    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {token}"},
        json={"ticket_ids": [1], "action": "closed"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_bulk_force_forbidden_for_agent(
    client: AsyncClient, db_session: AsyncSession
):
    """Agent не может использовать force=True — иначе защита обходится в один клик."""
    _, token = await _make_agent_user(client, db_session, "fa1")
    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {token}"},
        json={"ticket_ids": [1], "action": "closed", "force": True},
    )
    assert r.status_code == 403


# ── Базовое применение ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_close_clean_tickets_all_applied(
    client: AsyncClient, db_session: AsyncSession
):
    """Чистые тикеты (без переоткрытий, без unread) — все закрываются."""
    user_id, _ = await _register(client, "owner1")
    _, agent_token = await _make_agent_user(client, db_session, "ok1")

    tickets = [
        _make_ticket(user_id, status="in_progress"),
        _make_ticket(user_id, status="in_progress"),
        _make_ticket(user_id, status="confirmed"),
    ]
    db_session.add_all(tickets)
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [t.id for t in tickets], "action": "closed"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["requested_count"] == 3
    assert data["applied_count"] == 3
    assert len(data["rejected"]) == 0
    assert set(data["applied_ticket_ids"]) == {t.id for t in tickets}


# ── Защита от риска ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_rejects_reopened_tickets(
    client: AsyncClient, db_session: AsyncSession
):
    """Тикет с reopen_count > 0 — rejected с кодом has_reopens."""
    user_id, _ = await _register(client, "owner2")
    _, agent_token = await _make_agent_user(client, db_session, "ok2")

    clean = _make_ticket(user_id, status="in_progress")
    reopened = _make_ticket(user_id, status="in_progress", reopen_count=2)
    db_session.add_all([clean, reopened])
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [clean.id, reopened.id], "action": "closed"},
    )
    data = r.json()
    assert data["applied_count"] == 1
    assert clean.id in data["applied_ticket_ids"]
    assert len(data["rejected"]) == 1
    assert data["rejected"][0]["ticket_id"] == reopened.id
    assert data["rejected"][0]["code"] == "has_reopens"


@pytest.mark.asyncio
async def test_bulk_rejects_tickets_with_unread_user_message(
    client: AsyncClient, db_session: AsyncSession
):
    """Тикет с последним сообщением от user — rejected с has_unread_user_msg."""
    user_id, _ = await _register(client, "owner3")
    _, agent_token = await _make_agent_user(client, db_session, "ok3")

    conv = Conversation(user_id=user_id, status="active")
    db_session.add(conv)
    await db_session.flush()

    # Последнее сообщение — от user
    db_session.add(Message(conversation_id=conv.id, role="ai", content="hi"))
    db_session.add(Message(conversation_id=conv.id, role="user", content="не помогло"))

    ticket_with_unread = _make_ticket(
        user_id, status="in_progress", conversation_id=conv.id
    )
    clean = _make_ticket(user_id, status="in_progress")
    db_session.add_all([ticket_with_unread, clean])
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [ticket_with_unread.id, clean.id], "action": "closed"},
    )
    data = r.json()
    assert data["applied_count"] == 1
    assert clean.id in data["applied_ticket_ids"]
    rejected_codes = [r["code"] for r in data["rejected"]]
    assert "has_unread_user_msg" in rejected_codes


@pytest.mark.asyncio
async def test_bulk_rejects_pending_user_drafts(
    client: AsyncClient, db_session: AsyncSession
):
    """pending_user (черновики) — rejected с wrong_status."""
    user_id, _ = await _register(client, "owner4")
    _, agent_token = await _make_agent_user(client, db_session, "ok4")

    draft = _make_ticket(user_id, status="pending_user", confirmed_by_user=False)
    db_session.add(draft)
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [draft.id], "action": "closed"},
    )
    data = r.json()
    assert data["applied_count"] == 0
    assert data["rejected"][0]["code"] == "wrong_status"


@pytest.mark.asyncio
async def test_bulk_handles_missing_ids(
    client: AsyncClient, db_session: AsyncSession
):
    """Несуществующие ID — rejected с not_found, остальные применяются."""
    user_id, _ = await _register(client, "owner5")
    _, agent_token = await _make_agent_user(client, db_session, "ok5")

    ticket = _make_ticket(user_id, status="in_progress")
    db_session.add(ticket)
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [ticket.id, 99999, 99998], "action": "closed"},
    )
    data = r.json()
    assert data["applied_count"] == 1
    not_found = [r for r in data["rejected"] if r["code"] == "not_found"]
    assert len(not_found) == 2


# ── force=True обход защиты ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_force_admin_bypasses_reopen_check(
    client: AsyncClient, db_session: AsyncSession
):
    """Admin с force=True может закрывать переоткрытые."""
    user_id, _ = await _register(client, "owner6")
    _, admin_token = await _register_admin(client, "f1")

    reopened = _make_ticket(user_id, status="in_progress", reopen_count=3)
    db_session.add(reopened)
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"ticket_ids": [reopened.id], "action": "closed", "force": True},
    )
    data = r.json()
    assert data["applied_count"] == 1
    assert reopened.id in data["applied_ticket_ids"]


# ── Валидация ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_max_100_tickets(
    client: AsyncClient, db_session: AsyncSession
):
    """Запрос с 101+ ticket_ids → 422."""
    _, agent_token = await _make_agent_user(client, db_session, "v1")
    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": list(range(1, 102)), "action": "closed"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_empty_ticket_ids_rejected(
    client: AsyncClient, db_session: AsyncSession
):
    _, agent_token = await _make_agent_user(client, db_session, "v2")
    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [], "action": "closed"},
    )
    assert r.status_code == 422


# ── Audit log ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_logs_audit_event(
    client: AsyncClient, db_session: AsyncSession
):
    user_id, _ = await _register(client, "owner7")
    _, agent_token = await _make_agent_user(client, db_session, "au1")

    t1 = _make_ticket(user_id, status="in_progress")
    db_session.add(t1)
    await db_session.flush()

    r = await client.post(
        "/api/v1/tickets/bulk",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"ticket_ids": [t1.id], "action": "closed"},
    )
    assert r.status_code == 200

    import json

    audit_rows = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "ticket.bulk")
    )
    audits = list(audit_rows.scalars().all())
    assert len(audits) >= 1
    latest = audits[-1]
    # AuditLog.details — VARCHAR(500), сериализованный JSON.
    details = json.loads(latest.details) if isinstance(latest.details, str) else latest.details
    assert details["action"] == "closed"
    assert details["applied"] == 1
