"""Тесты POST /auth/register, POST /auth/login, GET /auth/me.

Что проверяем:
  - Успешная регистрация: 201 + access_token.
  - Дублирующийся email/username: 409.
  - Bootstrap-admin через BOOTSTRAP_ADMIN_EMAIL.
  - Успешный логин: 200 + access_token.
  - Неверный пароль / несуществующий пользователь: 401.
  - Заблокированный пользователь: 403.
  - GET /auth/me: данные текущего пользователя / 401 без токена.
  - Rate-limit: 429 после N попыток с одного IP.
  - Невалидные данные: 422.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.security import hash_password


# ── POST /auth/register ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Новый пользователь регистрируется, в ответе — access_token."""
    r = await client.post("/api/v1/auth/register", json={
        "email": "newuser@example.com",
        "username": "newuser",
        "password": "Secret123!",
    })
    assert r.status_code == 201
    data = r.json()
    assert "access_token" in data
    assert len(data["access_token"]) > 10


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Повторная регистрация с тем же email → 409."""
    payload = {"email": "dup@example.com", "username": "dup1", "password": "Abcdef1!"}
    await client.post("/api/v1/auth/register", json=payload)

    r = await client.post("/api/v1/auth/register", json={
        **payload,
        "username": "dup2",  # другой username, тот же email
    })
    assert r.status_code == 409
    assert "email" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient):
    """Повторная регистрация с тем же username → 409."""
    await client.post("/api/v1/auth/register", json={
        "email": "uname1@example.com",
        "username": "taken_user",
        "password": "Abcdef1!",
    })
    r = await client.post("/api/v1/auth/register", json={
        "email": "uname2@example.com",
        "username": "taken_user",  # тот же username
        "password": "Abcdef1!",
    })
    assert r.status_code == 409
    assert "username" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_bootstrap_admin(client: AsyncClient):
    """Если email совпадает с BOOTSTRAP_ADMIN_EMAIL — роль admin."""
    settings = get_settings()
    admin_email = "bootstrap@example.com"
    prev = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = admin_email
    try:
        r = await client.post("/api/v1/auth/register", json={
            "email": admin_email,
            "username": "bootstrapadmin",
            "password": "Admin123!",
        })
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = prev

    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_register_regular_user_role(client: AsyncClient):
    """Обычный пользователь (не bootstrap) получает роль user."""
    r = await client.post("/api/v1/auth/register", json={
        "email": "regular@example.com",
        "username": "regularuser",
        "password": "Regular123!",
    })
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "user"


@pytest.mark.asyncio
async def test_register_invalid_missing_fields(client: AsyncClient):
    """422 если обязательные поля отсутствуют."""
    r = await client.post("/api/v1/auth/register", json={"email": "only@example.com"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email_format(client: AsyncClient):
    """422 при невалидном формате email."""
    r = await client.post("/api/v1/auth/register", json={
        "email": "not-an-email",
        "username": "bademail",
        "password": "Secret123!",
    })
    assert r.status_code == 422


# ── POST /auth/login ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Успешный логин → 200 + access_token."""
    await client.post("/api/v1/auth/register", json={
        "email": "loginuser@example.com",
        "username": "loginuser",
        "password": "Login123!",
    })
    r = await client.post("/api/v1/auth/login", data={
        "username": "loginuser",
        "password": "Login123!",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Неверный пароль → 401."""
    await client.post("/api/v1/auth/register", json={
        "email": "wp@example.com",
        "username": "wpuser",
        "password": "Correct123!",
    })
    r = await client.post("/api/v1/auth/login", data={
        "username": "wpuser",
        "password": "Wrong123!",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_username(client: AsyncClient):
    """Несуществующий пользователь → 401 (не 404, чтобы не раскрывать существование)."""
    r = await client.post("/api/v1/auth/login", data={
        "username": "ghost_user_xyz",
        "password": "Whatever123!",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_blocked_user(client: AsyncClient, db_session: AsyncSession):
    """Заблокированный пользователь → 403."""
    await client.post("/api/v1/auth/register", json={
        "email": "blocked@example.com",
        "username": "blockeduser",
        "password": "Block123!",
    })
    # Блокируем пользователя напрямую в БД
    from sqlalchemy import select
    result = await db_session.execute(
        select(User).where(User.username == "blockeduser")
    )
    user = result.scalar_one()
    user.is_active = False
    await db_session.flush()

    r = await client.post("/api/v1/auth/login", data={
        "username": "blockeduser",
        "password": "Block123!",
    })
    assert r.status_code == 403


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient):
    """GET /auth/me с валидным токеном → 200 с данными пользователя."""
    r = await client.post("/api/v1/auth/register", json={
        "email": "meuser@example.com",
        "username": "meuser",
        "password": "MePass1!",
    })
    token = r.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    data = me.json()
    assert data["email"] == "meuser@example.com"
    assert data["username"] == "meuser"
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "id" in data and data["id"] > 0


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    """GET /auth/me без токена → 401."""
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    """GET /auth/me с некорректным токеном → 401."""
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.not.valid"},
    )
    assert r.status_code == 401


# ── Rate limiting ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_rate_limit(client: AsyncClient):
    """После 3 регистраций с одного IP → 429 на четвёртой."""
    from app.rate_limit import _reset
    _reset()

    for i in range(3):
        r = await client.post("/api/v1/auth/register", json={
            "email": f"ratelimit_reg{i}@example.com",
            "username": f"ratelimit_reg{i}",
            "password": "Secret123!",
        })
        assert r.status_code == 201, f"Попытка {i+1} неожиданно провалилась: {r.status_code}"

    r = await client.post("/api/v1/auth/register", json={
        "email": "ratelimit_reg4@example.com",
        "username": "ratelimit_reg4",
        "password": "Secret123!",
    })
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_login_rate_limit(client: AsyncClient):
    """После 5 попыток логина с одного IP → 429 на шестой."""
    from app.rate_limit import _reset
    _reset()

    # Создаём пользователя
    await client.post("/api/v1/auth/register", json={
        "email": "ratelimit_login@example.com",
        "username": "ratelimit_login",
        "password": "Secret123!",
    })
    _reset()  # сбрасываем после регистрации

    for i in range(5):
        await client.post("/api/v1/auth/login", data={
            "username": "ratelimit_login",
            "password": "wrong_pass",
        })

    r = await client.post("/api/v1/auth/login", data={
        "username": "ratelimit_login",
        "password": "wrong_pass",
    })
    assert r.status_code == 429
