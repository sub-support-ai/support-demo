import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthcheck(client: AsyncClient):
    """Healthcheck должен отвечать 200 и подтверждать живость БД."""
    response = await client.get("/healthcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """POST /auth/register — самостоятельная регистрация. Возвращает access_token."""
    payload = {
        "email": "test@example.com",
        "username": "testuser",
        "password": "Secret123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Проверяем, что пароль не утекает в /auth/me
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["email"] == payload["email"]
    assert me_data["username"] == payload["username"]
    assert me_data["role"] == "user"
    assert me_data["is_active"] is True
    assert "password" not in me_data
    assert "hashed_password" not in me_data


@pytest.mark.asyncio
async def test_register_accepts_simple_username(client: AsyncClient):
    """Логин не ограничен набором символов; уникальность проверяется отдельно."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "simplelogin@example.com",
        "username": "юзер",
        "password": "Secret123!",
    })
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client: AsyncClient):
    """Пароль должен проходить базовую complexity policy."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "weakpw@example.com",
        "username": "weakpwuser",
        "password": "secret123",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(client: AsyncClient):
    """Email проверяется через EmailStr/Pydantic."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "not-an-email",
        "username": "emailuser",
        "password": "Secret123!",
    })
    assert response.status_code == 422


# ── bcrypt 72-byte: длинные пароли не ломают хэширование ─────────────────────
#
# security.py пре-хэширует пароль через SHA-256 → hex (64 ASCII байта), и только
# потом кормит bcrypt. За счёт этого:
#   1) любой длины пароль укладывается в 72-байтный лимит bcrypt;
#   2) разные пароли, совпадающие по первым 72 байтам, дают РАЗНЫЕ хэши
#      (в bcrypt-напрямую они коллизировали бы).
# Эти тесты — регрессия: если кто-то уберёт SHA-256-нормализацию, они упадут.

@pytest.mark.asyncio
async def test_long_password_round_trips(client: AsyncClient):
    """Пароль близко к верхней границе регистрируется и логинится — то есть хэш
    корректно покрывает всю длину, а не только первые 72 байта."""
    long_pw = "A" + ("a" * 124) + "1!"
    reg = await client.post("/api/v1/auth/register", json={
        "email": "longpw@example.com",
        "username": "longpwuser",
        "password": long_pw,
    })
    assert reg.status_code == 201

    # /auth/login — OAuth2PasswordRequestForm, принимает form-data (username+password)
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "longpwuser", "password": long_pw},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_cyrillic_password_round_trips(client: AsyncClient):
    """80 байт UTF-8 (40 × 'ё') работает end-to-end.
    До SHA-256-нормализации такой пароль упирался в 72-байтный потолок."""
    cyrillic_pw = "Ё" + ("ё" * 37) + "1!"   # 80+ байт UTF-8
    reg = await client.post("/api/v1/auth/register", json={
        "email": "cyrpw@example.com",
        "username": "cyrpwuser",
        "password": cyrillic_pw,
    })
    assert reg.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "cyrpwuser", "password": cyrillic_pw},
    )
    assert login.status_code == 200


def test_different_long_passwords_produce_different_hashes():
    """
    Главный sanity: два пароля, отличающиеся ТОЛЬКО после 72-го байта,
    должны давать несовпадающие результаты verify.

    Без SHA-256-пре-хэша bcrypt видел бы оба как "a"*72 и считал
    эквивалентными — классическая CVE-class коллизия.
    """
    from app.security import hash_password, verify_password

    pw_a = "a" * 72 + "X"
    pw_b = "a" * 72 + "Y"

    stored_a = hash_password(pw_a)
    assert verify_password(pw_a, stored_a) is True
    assert verify_password(pw_b, stored_a) is False   # ← без SHA-256 было бы True


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {
        "email": "duplicate@example.com",
        "username": "user1",
        "password": "Secret123!",
    }
    await client.post("/api/v1/auth/register", json=payload)

    # Второй раз с тем же email — 409
    payload["username"] = "user2"
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "Email" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient):
    payload = {
        "email": "user3@example.com",
        "username": "sameusername",
        "password": "Secret123!",
    }
    await client.post("/api/v1/auth/register", json=payload)

    # Второй раз с тем же username — 409
    payload["email"] = "user4@example.com"
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "Username" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_username_after_trim(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "email": "trimuser1@example.com",
        "username": "trimmed",
        "password": "Secret123!",
    })

    response = await client.post("/api/v1/auth/register", json={
        "email": "trimuser2@example.com",
        "username": "  trimmed  ",
        "password": "Secret123!",
    })

    assert response.status_code == 409
    assert "Username" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_self(client: AsyncClient):
    """GET /users/{id} доступен владельцу — /users/<свой_id> возвращает 200."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "getme@example.com",
        "username": "getmeuser",
        "password": "Secret123!",
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["id"]
    request_context = me.json()["request_context"]
    assert request_context["requester_name"] == "getmeuser"
    assert request_context["requester_email"] == "getme@example.com"
    assert "Главный офис" in request_context["office_options"]
    assert "VPN" in request_context["affected_item_options"]

    response = await client.get(f"/api/v1/users/{user_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == user_id


@pytest.mark.asyncio
async def test_get_other_user_forbidden(client: AsyncClient):
    """Обычный пользователь не может смотреть чужой профиль → 403."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "spy@example.com",
        "username": "spy",
        "password": "Secret123!",
    })
    token = reg.json()["access_token"]
    response = await client.get(
        "/api/v1/users/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_users_list_requires_admin(client: AsyncClient):
    """GET /users/ без админ-токена → 403."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "nonadmin@example.com",
        "username": "nonadmin",
        "password": "Secret123!",
    })
    token = reg.json()["access_token"]
    response = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_stats_requires_auth(client: AsyncClient):
    """GET /stats/ без токена → 401."""
    response = await client.get("/api/v1/stats/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stats_includes_job_queue_counters(client: AsyncClient):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "statsjobs@example.com",
        "username": "statsjobs",
        "password": "Secret123!",
    })
    token = reg.json()["access_token"]

    response = await client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["jobs"]["ai"] == {
        "total": 0,
        "queued": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
    }
    assert data["jobs"]["knowledge_embeddings"] == {
        "total": 0,
        "queued": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
    }


# ── Bootstrap-admin ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_admin_registration(client: AsyncClient, monkeypatch):
    """
    Если BOOTSTRAP_ADMIN_EMAIL совпадает с email при регистрации —
    пользователь автоматически получает role=admin.
    """
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "ceo@acme.com")

    reg = await client.post("/api/v1/auth/register", json={
        "email": "ceo@acme.com",
        "username": "ceo",
        "password": "Secret123!",
    })
    assert reg.status_code == 201

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {reg.json()['access_token']}"},
    )
    assert me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_bootstrap_admin_case_insensitive(client: AsyncClient, monkeypatch):
    """Email сравнивается без учёта регистра."""
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "Admin@Corp.com")

    reg = await client.post("/api/v1/auth/register", json={
        "email": "admin@corp.com",   # lower-case, а в env — Mixed-case
        "username": "mixcaseadmin",
        "password": "Secret123!",
    })
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {reg.json()['access_token']}"},
    )
    assert me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_cors_allows_configured_origin(client: AsyncClient, monkeypatch):
    """
    Preflight-запрос с Origin из белого списка → ответ с Access-Control-Allow-Origin.
    NOTE: мы патчим settings.CORS_ORIGINS_RAW, но CORSMiddleware уже зарегистрирован
    при старте app, поэтому тест проверяет только факт "middleware установлен".
    Чтобы проверить реальный фильтр — нужен отдельный app-инстанс на тест.
    """
    # Если CORS не подключён (CORS_ORIGINS был пуст при старте) — тест skip.
    # Реальную валидацию покрывает test_cors_no_middleware_when_empty ниже.
    from starlette.middleware.cors import CORSMiddleware as _CORSMiddleware
    from app.main import app
    cors_middleware = next((m for m in app.user_middleware if m.cls is _CORSMiddleware), None)
    if cors_middleware is None:
        pytest.skip("CORS middleware не подключён в этом процессе — CORS_ORIGINS пуст")
    origin = cors_middleware.kwargs["allow_origins"][0]

    response = await client.options(
        "/healthcheck",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_cors_no_middleware_when_empty():
    """
    Санити: если CORS_ORIGINS пустой, middleware не добавляется (см. main.py).
    Проверяем property напрямую — он возвращает пустой список для пустой строки.
    """
    from app.config import Settings
    s = Settings()
    s.CORS_ORIGINS_RAW = ""
    assert s.CORS_ORIGINS == []

    s.CORS_ORIGINS_RAW = "  "
    assert s.CORS_ORIGINS == []

    s.CORS_ORIGINS_RAW = "http://localhost:3000, https://app.acme.com"
    assert s.CORS_ORIGINS == ["http://localhost:3000", "https://app.acme.com"]


@pytest.mark.asyncio
async def test_non_bootstrap_users_stay_regular(client: AsyncClient, monkeypatch):
    """
    Если email НЕ совпадает с BOOTSTRAP_ADMIN_EMAIL — обычный user.
    Регрессия: случайный пользователь не должен стать админом.
    """
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "ceo@acme.com")

    reg = await client.post("/api/v1/auth/register", json={
        "email": "random@acme.com",
        "username": "randomuser",
        "password": "Secret123!",
    })
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {reg.json()['access_token']}"},
    )
    assert me.json()["role"] == "user"


# ── Rate limit на /auth ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_rate_limit_blocks_brute_force(client: AsyncClient):
    """
    6-й подряд /auth/login с одного IP в минутном окне возвращает 429.
    Первые 5 попыток пропускаются (пусть и с 401) — это нормальный UX:
    пользователь мог опечататься.
    """
    # Сначала создаём юзера, чтобы /login не валился на "нет такого".
    # Регистрация не лимитируется в рамках 3/мин — одна регистрация OK.
    await client.post("/api/v1/auth/register", json={
        "email": "brute@example.com",
        "username": "brute",
        "password": "Correct123!",
    })

    # Сбрасываем счётчики ПЕРЕД тестом, чтобы регистрация выше не съела
    # квоту login'а (они считаются раздельно, но на всякий случай).
    from app.rate_limit import _reset
    _reset()

    # Пять заведомо неверных попыток — все возвращают 401, но лимитер
    # уже записал их и на 6-ю сработает.
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "brute", "password": "wrong"},
        )
        assert resp.status_code == 401

    # Шестая попытка — даже с ПРАВИЛЬНЫМ паролем получает 429.
    # Это важно: лимит срабатывает РАНЬШЕ проверки пароля, иначе
    # атакующий узнал бы по задержке, когда угадал.
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "brute", "password": "Correct123!"},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_register_rate_limit_blocks_spam(client: AsyncClient):
    """4-я подряд регистрация с одного IP в минуту → 429."""
    from app.rate_limit import _reset
    _reset()

    # Три легитимные регистрации проходят.
    for i in range(3):
        resp = await client.post("/api/v1/auth/register", json={
            "email": f"spam{i}@example.com",
            "username": f"spammer{i}",
            "password": "Secret123!",
        })
        assert resp.status_code == 201

    # Четвёртая — блок.
    resp = await client.post("/api/v1/auth/register", json={
        "email": "spam3@example.com",
        "username": "spammer3",
        "password": "Secret123!",
    })
    assert resp.status_code == 429
