"""Тесты эндпоинтов GET /api/v1/stats/*.

Что проверяем:
  - GET /stats/ возвращает корректную структуру для user, agent и admin.
  - GET /stats/ai/fallbacks доступен только admin (403 для остальных).
  - GET /stats/knowledge доступен только admin (403 для остальных).
  - GET /stats/knowledge/score-distribution доступен только admin (403 для остальных).
  - На пустой БД все поля имеют валидные zero-значения, нет 500.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import Agent
from app.models.user import User
from app.security import hash_password


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client: AsyncClient, suffix: str) -> tuple[int, str]:
    r = await client.post("/api/v1/auth/register", json={
        "email": f"statsuser{suffix}@example.com",
        "username": f"statsuser{suffix}",
        "password": "Secret123!",
    })
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


async def _register_admin(client: AsyncClient, suffix: str) -> tuple[int, str]:
    settings = get_settings()
    email = f"statsadmin{suffix}@example.com"
    prev = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = email
    try:
        r = await client.post("/api/v1/auth/register", json={
            "email": email,
            "username": f"statsadmin{suffix}",
            "password": "Secret123!",
        })
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = prev
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "admin"
    return me.json()["id"], token


async def _make_agent(
    db_session: AsyncSession,
    client: AsyncClient,
    suffix: str,
) -> tuple[int, str]:
    """Регистрирует пользователя с ролью agent и создаёт Agent-запись."""
    user_id, token = await _register(client, f"agent{suffix}")
    user = await db_session.get(User, user_id)
    assert user is not None
    user.role = "agent"
    agent = Agent(
        user_id=user_id,
        email=f"statsagent{suffix}@example.com",
        username=f"statsagent{suffix}",
        hashed_password=hash_password("Secret123!"),
        department="IT",
        is_active=True,
    )
    db_session.add(agent)
    await db_session.flush()
    return user_id, token


# ── GET /stats/ ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_empty_db_user(client: AsyncClient):
    """На пустой БД user получает StatsResponse с нулями, без 500."""
    _, token = await _register(client, "s1")
    r = await client.get("/api/v1/stats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "tickets" in data
    assert "ai" in data
    assert "jobs" in data
    assert data["tickets"]["total"] == 0
    assert data["ai"]["total_processed"] == 0


@pytest.mark.asyncio
async def test_stats_empty_db_admin(client: AsyncClient):
    """Admin также получает корректный StatsResponse на пустой БД."""
    _, token = await _register_admin(client, "s2")
    r = await client.get("/api/v1/stats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["tickets"]["total"] == 0
    assert isinstance(data["tickets"]["by_status"], dict)
    assert isinstance(data["tickets"]["by_department"], dict)


@pytest.mark.asyncio
async def test_stats_agent_sees_only_own_tickets(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Agent видит только тикеты, назначенные на него (zero без назначения)."""
    _, token = await _make_agent(db_session, client, "st3")
    r = await client.get("/api/v1/stats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["tickets"]["total"] == 0


@pytest.mark.asyncio
async def test_stats_requires_auth(client: AsyncClient):
    """GET /stats/ без токена → 401."""
    r = await client.get("/api/v1/stats/")
    assert r.status_code == 401


# ── GET /stats/ai/fallbacks ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_ai_fallbacks_admin_only_forbidden_for_user(client: AsyncClient):
    """Обычный пользователь получает 403 на /stats/ai/fallbacks."""
    _, token = await _register(client, "fb1")
    r = await client.get(
        "/api/v1/stats/ai/fallbacks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stats_ai_fallbacks_admin_empty(client: AsyncClient):
    """Admin получает корректный AIFallbacksStats на пустой БД."""
    _, token = await _register_admin(client, "fb2")
    r = await client.get(
        "/api/v1/stats/ai/fallbacks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "by_reason" in data
    assert "by_service" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_stats_ai_fallbacks_custom_since(client: AsyncClient):
    """Параметр since принимается без ошибки; since в ответе — ISO8601-строка."""
    _, token = await _register_admin(client, "fb3")
    # Используем дату в пределах MAX_FALLBACKS_WINDOW_DAYS=30 — за последние 7 дней
    r = await client.get(
        "/api/v1/stats/ai/fallbacks?since=2026-05-03T00:00:00Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "since" in data
    assert "T" in data["since"]  # ISO8601 содержит T между датой и временем


# ── GET /stats/knowledge ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_knowledge_forbidden_for_user(client: AsyncClient):
    """Обычный пользователь получает 403 на /stats/knowledge."""
    _, token = await _register(client, "kb1")
    r = await client.get(
        "/api/v1/stats/knowledge",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stats_knowledge_admin_empty(client: AsyncClient):
    """Admin получает KnowledgeStats с нулями на пустой KB."""
    _, token = await _register_admin(client, "kb2")
    r = await client.get(
        "/api/v1/stats/knowledge",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total_articles"] == 0
    assert data["active_articles"] == 0
    assert isinstance(data["by_department"], dict)
    assert isinstance(data["top_helped"], list)
    assert isinstance(data["never_shown"], list)


# ── GET /stats/knowledge/score-distribution ───────────────────────────────────

@pytest.mark.asyncio
async def test_stats_score_distribution_forbidden_for_user(client: AsyncClient):
    """Обычный пользователь получает 403 на /stats/knowledge/score-distribution."""
    _, token = await _register(client, "sd1")
    r = await client.get(
        "/api/v1/stats/knowledge/score-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stats_score_distribution_admin_empty(client: AsyncClient):
    """Admin получает KnowledgeScoreDistribution с нулями."""
    _, token = await _register_admin(client, "sd2")
    r = await client.get(
        "/api/v1/stats/knowledge/score-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "period_days" in data
    assert "buckets" in data
    assert "decision_distribution" in data
    assert "current_thresholds" in data
    assert data["total_feedback_records"] == 0
    assert isinstance(data["buckets"], list)


@pytest.mark.asyncio
async def test_stats_score_distribution_custom_days(client: AsyncClient):
    """Параметр days принимается без ошибки."""
    _, token = await _register_admin(client, "sd3")
    r = await client.get(
        "/api/v1/stats/knowledge/score-distribution?days=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["period_days"] == 7
