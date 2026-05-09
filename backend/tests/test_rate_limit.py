"""Тесты sliding-window rate limiter (memory + redis).

Memory-тесты проверяют общий контракт: max_calls / window / Retry-After /
изоляция scope'ов. Redis-тесты используют fakeredis (тоже исполняет Lua),
чтобы убедиться что атомарный sliding-window работает без поднятого
настоящего сервера.
"""

import asyncio

import pytest

from app.rate_limit import (
    _MemoryBackend,
    _RedisBackend,
    set_backend_for_testing,
)


# ── Memory backend ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_backend_allows_under_limit():
    """N запросов при лимите N — все проходят, отказа нет."""
    backend = _MemoryBackend()
    for _ in range(5):
        retry = await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
        assert retry is None


@pytest.mark.asyncio
async def test_memory_backend_blocks_over_limit_with_retry_after():
    """N+1-й запрос → отказ + Retry-After в окне."""
    backend = _MemoryBackend()
    for _ in range(5):
        await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    retry = await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    assert retry is not None
    # +1 в формуле retry_after страхует от int-truncation при «осталось <1с»;
    # граничное значение для одинаковых timestamp'ов = window + 1.
    assert 0 < retry <= 61


@pytest.mark.asyncio
async def test_memory_backend_isolates_scopes():
    """5 запросов на /login + 5 на /register с одного IP не должны
    сваливаться в общий счётчик."""
    backend = _MemoryBackend()
    for _ in range(5):
        await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    # /register ещё не использовался — должен пропустить
    retry = await backend.consume("register", "1.2.3.4", max_calls=5, window_seconds=60)
    assert retry is None


@pytest.mark.asyncio
async def test_memory_backend_isolates_keys():
    """5 попыток с одного IP не должны лимитировать другой IP."""
    backend = _MemoryBackend()
    for _ in range(5):
        await backend.consume("login", "1.1.1.1", max_calls=5, window_seconds=60)
    retry = await backend.consume("login", "2.2.2.2", max_calls=5, window_seconds=60)
    assert retry is None


@pytest.mark.asyncio
async def test_memory_backend_releases_after_window(monkeypatch):
    """Выход за окно → старые попытки выкидываются, новый запрос проходит.

    Проверяем без sleep: подменяем monotonic, чтобы тест шёл мгновенно.
    """
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    import app.rate_limit as rate_limit_mod
    monkeypatch.setattr(rate_limit_mod, "monotonic", fake_monotonic)

    backend = _MemoryBackend()
    for _ in range(5):
        await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    # 6-й заблокирован
    assert await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60) is not None

    # Прыгаем за окно → счётчик пуст
    fake_now[0] += 61
    assert await backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60) is None


# ── Redis backend через fakeredis ───────────────────────────────────────────


@pytest.fixture
async def redis_backend():
    """fakeredis с поддержкой Lua. Изолирован per-тест: новый instance каждый раз."""
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = _RedisBackend(client)
    yield backend
    await client.flushdb()
    await client.aclose()


@pytest.mark.asyncio
async def test_redis_backend_allows_under_limit(redis_backend):
    """Lua-скрипт корректно прокидывает разрешения для запросов в окне."""
    for _ in range(5):
        retry = await redis_backend.consume(
            "login", "1.2.3.4", max_calls=5, window_seconds=60
        )
        assert retry is None


@pytest.mark.asyncio
async def test_redis_backend_blocks_over_limit_with_retry_after(redis_backend):
    """N+1 → -1 из Lua → translate в retry_after >= 1 sec."""
    for _ in range(5):
        await redis_backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    retry = await redis_backend.consume(
        "login", "1.2.3.4", max_calls=5, window_seconds=60
    )
    assert retry is not None
    assert retry >= 1


@pytest.mark.asyncio
async def test_redis_backend_isolates_scopes(redis_backend):
    """ZSET-ключ включает scope — разные endpoint'ы не пересекаются."""
    for _ in range(5):
        await redis_backend.consume("login", "1.2.3.4", max_calls=5, window_seconds=60)
    retry = await redis_backend.consume(
        "register", "1.2.3.4", max_calls=5, window_seconds=60
    )
    assert retry is None


@pytest.mark.asyncio
async def test_redis_backend_atomic_under_concurrency(redis_backend):
    """N конкурентных запросов при лимите N — ровно один лишний должен
    получить отказ (а не «все 2N разлетелись между ZCARD и ZADD»).

    Регрессия защиты: без Lua атомарности под конкурентной нагрузкой
    rate limit давал false negatives — это и есть основная причина,
    зачем вообще нужен redis-бэкенд.
    """
    max_calls = 5

    async def attempt():
        return await redis_backend.consume(
            "login", "1.2.3.4", max_calls=max_calls, window_seconds=60
        )

    # 10 одновременных запросов при лимите 5 → ровно 5 должны пройти
    results = await asyncio.gather(*(attempt() for _ in range(10)))
    allowed = [r for r in results if r is None]
    blocked = [r for r in results if r is not None]
    assert len(allowed) == max_calls
    assert len(blocked) == 10 - max_calls


# ── End-to-end через FastAPI dependency ─────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_dependency_uses_configured_backend(client):
    """rate_limit() через FastAPI: после max_calls возвращает 429 с Retry-After."""
    from app.rate_limit import _reset

    # Сюит уже использует memory backend (default); зануляем счётчики.
    _reset()

    # Существующий test_login_rate_limit_blocks_brute_force в test_users.py
    # покрывает интеграцию через /auth/login. Здесь проверяем сам контракт
    # ответа FastAPI на сработавший лимит — отдельно от login-логики.
    await client.post("/api/v1/auth/register", json={
        "email": "ratelimit@example.com",
        "username": "ratelimituser",
        "password": "Secret123!",
    })

    # 5 неверных логинов — 401
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "ratelimituser", "password": "wrong"},
        )
        assert response.status_code == 401

    # 6-й → 429 с Retry-After
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "ratelimituser", "password": "wrong"},
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) > 0


# ── Settings: валидация значения RATE_LIMIT_BACKEND ──────────────────────────


def test_settings_rejects_unknown_rate_limit_backend():
    """Опечатка вместо memory/redis должна падать на старте, не молча
    переходить в no-op (= открытый /auth/login для брутфорса)."""
    from app.config import Settings

    s = Settings()
    s.RATE_LIMIT_BACKEND = "memcached"  # не из whitelist

    with pytest.raises(RuntimeError, match="RATE_LIMIT_BACKEND"):
        s.__post_init_check__()


# ── _client_ip: X-Forwarded-For за доверенным прокси ────────────────────────


def _make_request(xff: str | None, client_host: str = "127.0.0.1"):
    """Создаёт минимальный mock Request с нужными атрибутами."""
    from unittest.mock import MagicMock

    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_host
    req.headers = {}
    if xff is not None:
        req.headers = {"X-Forwarded-For": xff}
    # MagicMock.get() нужен для dict-like доступа headers.get(...)
    req.headers = MagicMock()
    req.headers.get = lambda key, default="": xff if xff is not None and key == "X-Forwarded-For" else default
    return req


def test_client_ip_without_proxy_uses_socket_host(monkeypatch):
    """TRUSTED_PROXY_COUNT=0: IP берётся из request.client.host, XFF игнорируется."""
    from app.config import Settings
    from app.rate_limit import _client_ip

    settings = Settings()
    settings.TRUSTED_PROXY_COUNT = 0
    monkeypatch.setattr("app.rate_limit.get_settings", lambda: settings)

    req = _make_request(xff="1.2.3.4", client_host="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"


def test_client_ip_with_one_proxy_reads_xff(monkeypatch):
    """TRUSTED_PROXY_COUNT=1, один прокси (nginx):
    X-Forwarded-For содержит реальный IP клиента."""
    from app.config import Settings
    from app.rate_limit import _client_ip

    settings = Settings()
    settings.TRUSTED_PROXY_COUNT = 1
    monkeypatch.setattr("app.rate_limit.get_settings", lambda: settings)

    req = _make_request(xff="1.2.3.4", client_host="127.0.0.1")
    assert _client_ip(req) == "1.2.3.4"


def test_client_ip_with_proxy_resists_xff_spoofing(monkeypatch):
    """Злоумышленник добавляет поддельный IP перед реальным.
    TRUSTED_PROXY_COUNT=1: берём IP на позиции len-1 от начала, spoof отброшен.
    X-Forwarded-For: spoofed_ip, real_client_ip  (nginx добавил real_client_ip)
    """
    from app.config import Settings
    from app.rate_limit import _client_ip

    settings = Settings()
    settings.TRUSTED_PROXY_COUNT = 1
    monkeypatch.setattr("app.rate_limit.get_settings", lambda: settings)

    req = _make_request(xff="9.9.9.9, 1.2.3.4", client_host="127.0.0.1")
    assert _client_ip(req) == "1.2.3.4"


def test_client_ip_with_two_proxies(monkeypatch):
    """TRUSTED_PROXY_COUNT=2: клиент → proxy1 → nginx → app.
    X-Forwarded-For: client_ip, proxy1_ip  → реальный IP = client_ip.
    """
    from app.config import Settings
    from app.rate_limit import _client_ip

    settings = Settings()
    settings.TRUSTED_PROXY_COUNT = 2
    monkeypatch.setattr("app.rate_limit.get_settings", lambda: settings)

    req = _make_request(xff="1.2.3.4, 2.2.2.2", client_host="127.0.0.1")
    assert _client_ip(req) == "1.2.3.4"


def test_client_ip_falls_back_to_socket_when_xff_empty(monkeypatch):
    """TRUSTED_PROXY_COUNT=1 но XFF отсутствует → fallback на socket host."""
    from app.config import Settings
    from app.rate_limit import _client_ip

    settings = Settings()
    settings.TRUSTED_PROXY_COUNT = 1
    monkeypatch.setattr("app.rate_limit.get_settings", lambda: settings)

    req = _make_request(xff=None, client_host="10.0.0.2")
    assert _client_ip(req) == "10.0.0.2"
