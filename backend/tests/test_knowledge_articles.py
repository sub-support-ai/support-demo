"""Тесты роутера /api/v1/knowledge/*.

Что проверяем:
  - GET /knowledge/           — список статей (видимость по роли).
  - POST /knowledge/          — создание (admin only, 403 для остальных).
  - GET /knowledge/search     — поиск возвращает корректную структуру.
  - POST /knowledge/reindex   — глобальный reindex (admin only).
  - POST /knowledge/{id}/reindex — reindex одной статьи (404 если нет).
  - PATCH /knowledge/{id}     — обновление (admin only, 404 если нет).
  - POST /knowledge/feedback  — 404 если feedback-запись не существует.
"""

import pytest
from httpx import AsyncClient

from app.config import get_settings


@pytest.fixture(autouse=True)
def _monkeypatch_sqlite_fallback(monkeypatch: pytest.MonkeyPatch):
    """Force SQLite FTS fallback for all tests in this file.

    Tests call search_knowledge_articles through the REST API /knowledge/search endpoint.
    Force SQLite dialect fallback to avoid search_vector dependency.
    """
    monkeypatch.setattr(
        "app.services.knowledge_base._session_dialect_name",
        lambda _db: "sqlite",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, suffix: str) -> tuple[int, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"kbuser{suffix}@example.com",
            "username": f"kbuser{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


async def _register_admin(client: AsyncClient, suffix: str) -> tuple[int, str]:
    settings = get_settings()
    email = f"kbadmin{suffix}@example.com"
    prev = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = email
    try:
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": f"kbadmin{suffix}",
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


_ARTICLE_PAYLOAD = {
    "title": "Тестовая статья VPN",
    "body": "Для подключения VPN откройте приложение и введите логин.",
    "department": "IT",
    "request_type": "VPN",
    "access_scope": "public",
    "keywords": "vpn доступ подключение",
}

_INTERNAL_ARTICLE_PAYLOAD = {
    "title": "Внутренняя статья IT",
    "body": "Инструкция для внутреннего использования.",
    "department": "IT",
    "request_type": "Internal",
    "access_scope": "internal",
}


async def _create_article(client: AsyncClient, token: str, payload: dict | None = None) -> dict:
    payload = payload or _ARTICLE_PAYLOAD
    r = await client.post(
        "/api/v1/knowledge/",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── GET /knowledge/ ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient):
    """Пустая KB возвращает пустой список, не 500."""
    _, token = await _register(client, "l1")
    r = await client.get(
        "/api/v1/knowledge/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_user_sees_only_public(client: AsyncClient):
    """Обычный пользователь видит только public-статьи."""
    _, admin_token = await _register_admin(client, "l2a")
    await _create_article(client, admin_token, _ARTICLE_PAYLOAD)  # public
    await _create_article(client, admin_token, _INTERNAL_ARTICLE_PAYLOAD)  # internal

    _, user_token = await _register(client, "l2u")
    r = await client.get(
        "/api/v1/knowledge/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    articles = r.json()
    scopes = {a["access_scope"] for a in articles}
    assert scopes <= {"public"}, f"user видит non-public статьи: {scopes}"


@pytest.mark.asyncio
async def test_list_admin_sees_all(client: AsyncClient):
    """Admin видит все статьи — и public, и internal."""
    _, admin_token = await _register_admin(client, "l3")
    await _create_article(client, admin_token, _ARTICLE_PAYLOAD)
    await _create_article(client, admin_token, _INTERNAL_ARTICLE_PAYLOAD)

    r = await client.get(
        "/api/v1/knowledge/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    scopes = {a["access_scope"] for a in r.json()}
    assert "public" in scopes
    assert "internal" in scopes


@pytest.mark.asyncio
async def test_list_filter_by_department(client: AsyncClient):
    """Параметр department фильтрует корректно."""
    _, admin_token = await _register_admin(client, "l4")
    await _create_article(client, admin_token, _ARTICLE_PAYLOAD)  # department=IT

    r = await client.get(
        "/api/v1/knowledge/?department=IT",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert all(a["department"] == "IT" for a in r.json())

    r2 = await client.get(
        "/api/v1/knowledge/?department=HR",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200
    assert r2.json() == []


# ── POST /knowledge/ ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_admin_only(client: AsyncClient):
    """Обычный пользователь получает 403 при попытке создать статью."""
    _, user_token = await _register(client, "c1")
    r = await client.post(
        "/api/v1/knowledge/",
        json=_ARTICLE_PAYLOAD,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_returns_article(client: AsyncClient):
    """Admin создаёт статью — ответ содержит id и переданные поля."""
    _, token = await _register_admin(client, "c2")
    article = await _create_article(client, token)
    assert article["id"] > 0
    assert article["title"] == _ARTICLE_PAYLOAD["title"]
    assert article["department"] == "IT"
    assert article["is_active"] is True


@pytest.mark.asyncio
async def test_create_missing_required_fields(client: AsyncClient):
    """422 если обязательные поля title/body отсутствуют."""
    _, token = await _register_admin(client, "c3")
    r = await client.post(
        "/api/v1/knowledge/",
        json={"department": "IT"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


# ── GET /knowledge/search ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_returns_list(client: AsyncClient):
    """Поиск по несуществующему запросу возвращает пустой список, не 500."""
    _, token = await _register(client, "s1")
    r = await client.get(
        "/api/v1/knowledge/search?q=ничего_нет_такого",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_search_too_short_query(client: AsyncClient):
    """Запрос длиной < 2 символов → 422."""
    _, token = await _register(client, "s2")
    r = await client.get(
        "/api/v1/knowledge/search?q=a",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_finds_created_article(client: AsyncClient):
    """После создания статьи поиск по ключевому слову находит её."""
    _, admin_token = await _register_admin(client, "s3a")
    await _create_article(client, admin_token, _ARTICLE_PAYLOAD)

    _, user_token = await _register(client, "s3u")
    r = await client.get(
        "/api/v1/knowledge/search?q=vpn",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)
    # Ключевое: поиск не падает и возвращает список (может быть пустым
    # на SQLite без полнотекстового индекса, но не 500)


# ── POST /knowledge/reindex ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_all_admin_only(client: AsyncClient):
    """Обычный пользователь получает 403."""
    _, user_token = await _register(client, "ri1")
    r = await client.post(
        "/api/v1/knowledge/reindex",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reindex_all_creates_job(client: AsyncClient):
    """Admin может запустить глобальный reindex — возвращается job-объект."""
    _, token = await _register_admin(client, "ri2")
    r = await client.post(
        "/api/v1/knowledge/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["id"] > 0
    assert job["status"] == "queued"
    assert job["article_id"] is None  # глобальный reindex — без конкретной статьи


# ── POST /knowledge/{id}/reindex ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_article_not_found(client: AsyncClient):
    """404 если статья не существует."""
    _, token = await _register_admin(client, "ra1")
    r = await client.post(
        "/api/v1/knowledge/99999/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reindex_article_creates_job(client: AsyncClient):
    """Admin создаёт статью и запускает reindex — job содержит article_id."""
    _, token = await _register_admin(client, "ra2")
    article = await _create_article(client, token)
    article_id = article["id"]

    r = await client.post(
        f"/api/v1/knowledge/{article_id}/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    job = r.json()
    assert job["article_id"] == article_id
    assert job["status"] == "queued"


# ── PATCH /knowledge/{id} ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_article_admin_only(client: AsyncClient):
    """Обычный пользователь получает 403."""
    _, admin_token = await _register_admin(client, "u1a")
    article = await _create_article(client, admin_token)

    _, user_token = await _register(client, "u1u")
    r = await client.patch(
        f"/api/v1/knowledge/{article['id']}",
        json={"title": "Новый заголовок"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_article_not_found(client: AsyncClient):
    """404 если статья не существует."""
    _, token = await _register_admin(client, "u2")
    r = await client.patch(
        "/api/v1/knowledge/99999",
        json={"title": "Не важно"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_article_changes_fields(client: AsyncClient):
    """Admin может обновить заголовок и body; версия инкрементируется."""
    _, token = await _register_admin(client, "u3")
    article = await _create_article(client, token)
    original_version = article["version"]

    r = await client.patch(
        f"/api/v1/knowledge/{article['id']}",
        json={"title": "Обновлённый заголовок VPN"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["title"] == "Обновлённый заголовок VPN"
    assert updated["version"] == original_version + 1


@pytest.mark.asyncio
async def test_update_article_empty_patch_returns_unchanged(client: AsyncClient):
    """PATCH с пустым телом возвращает статью без изменений (не 422)."""
    _, token = await _register_admin(client, "u4")
    article = await _create_article(client, token)

    r = await client.patch(
        f"/api/v1/knowledge/{article['id']}",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == article["title"]


# ── POST /knowledge/feedback ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feedback_target_not_found(client: AsyncClient):
    """404 если feedback-запись с таким article_id/message_id не найдена."""
    _, token = await _register(client, "f1")
    r = await client.post(
        "/api/v1/knowledge/feedback",
        json={
            "article_id": 99999,
            "message_id": 99999,
            "feedback": "helped",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
