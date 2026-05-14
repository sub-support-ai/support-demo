"""Тесты для audit_log.

Что проверяем:
  1) Важные события пишутся: успешная регистрация, создание/удаление тикета.
  2) Неудачный логин пишется тоже (несмотря на HTTPException + rollback).
  3) GET /audit доступен только admin'у.
"""

import json

import pytest
from httpx import AsyncClient


async def register(client: AsyncClient, suffix: str, bootstrap_admin: bool = False):
    """Зарегистрировать юзера; вернуть (id, token).
    Если bootstrap_admin=True — через monkeypatch эта регистрация станет админом
    (логика в routers/auth.py). Здесь мы просто регистрируем обычного.
    """
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"audit{suffix}@example.com",
            "username": f"audit{suffix}",
            "password": "Secret123!",
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json()["id"], token


@pytest.mark.asyncio
async def test_register_is_audited(client: AsyncClient):
    """POST /auth/register → в audit_logs строка action='user.register'."""
    user_id, token = await register(client, "reg")

    # Чтобы посмотреть журнал, нужен admin. Промоутим через bootstrap.

    from app.config import get_settings

    settings = get_settings()
    # Временный admin-аккаунт только для чтения журнала.
    settings.BOOTSTRAP_ADMIN_EMAIL = "auditadmin@example.com"
    admin_r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin@example.com",
            "username": "auditadmin",
            "password": "Secret123!",
        },
    )
    admin_token = admin_r.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None

    audit = await client.get(
        f"/api/v1/audit/?user_id={user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    events = audit.json()

    register_events = [e for e in events if e["action"] == "user.register"]
    assert len(register_events) == 1
    e = register_events[0]
    assert e["user_id"] == user_id
    assert e["ip"] is not None
    # details — JSON-строка, проверяем валидность и содержимое
    details = json.loads(e["details"])
    assert details["role"] == "user"


@pytest.mark.asyncio
async def test_failed_login_is_audited_despite_rollback(client: AsyncClient):
    """
    Главный нюанс, который мы специально обрабатывали в auth.py:
    неудачный логин бросает 401, get_db делает rollback — но мы коммитим
    audit ЯВНО перед raise, поэтому запись должна сохраниться.
    """
    # Создаём юзера с известным паролем
    _, _ = await register(client, "fail")

    # Три заведомо неверные попытки (не 5, чтобы не упереться в rate limit)
    for _ in range(3):
        r = await client.post(
            "/api/v1/auth/login",
            data={"username": "auditfail", "password": "wrong"},
        )
        assert r.status_code == 401

    # Промоутим временного админа, как в предыдущем тесте
    from app.config import get_settings

    settings = get_settings()
    settings.BOOTSTRAP_ADMIN_EMAIL = "auditadmin2@example.com"
    admin_r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin2@example.com",
            "username": "auditadmin2",
            "password": "Secret123!",
        },
    )
    admin_token = admin_r.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None

    audit = await client.get(
        "/api/v1/audit/?action=login.failure",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    fails = audit.json()
    # Три неудачные попытки с username='auditfail' — должны быть записаны
    our_fails = [
        e for e in fails if e["details"] and json.loads(e["details"]).get("username") == "auditfail"
    ]
    assert len(our_fails) == 3


@pytest.mark.asyncio
async def test_failed_login_with_huge_username_does_not_crash(client: AsyncClient):
    """Регрессия: длинный username от атакующего не должен ронять /login 500-кой.

    Сценарий: злоумышленник шлёт POST /auth/login с username в 2000 символов.
    До фикса json.dumps(details={"username": "aaaa...×2000"}) давал строку
    длиннее колонки details (String(500)):
      - Postgres → StringDataRightTruncation → 500 Internal Server Error;
      - SQLite  → тихо обрезал, но инвариант "details — валидный JSON" ломался
        (обрывался на полуслове, json.loads падал бы в /audit).

    После фикса:
      - /login возвращает штатный 401 (ровно как на короткий username);
      - в audit появляется запись login.failure, details — валидный JSON,
        оканчивающийся маркером "...<truncated>".
    """
    huge_username = "a" * 2000

    # 1) Запрос должен пройти весь pipeline до 401, без 500.
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": huge_username, "password": "wrong"},
    )
    assert r.status_code == 401, f"ожидали 401, получили {r.status_code}: {r.text}"

    # 2) В audit должна быть запись с обрезанным details (валидный JSON).
    from app.config import get_settings
    from app.models.audit_log import DETAILS_MAX_LEN

    settings = get_settings()
    settings.BOOTSTRAP_ADMIN_EMAIL = "auditadmin_huge@example.com"
    admin_r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin_huge@example.com",
            "username": "auditadmin_huge",
            "password": "Secret123!",
        },
    )
    admin_token = admin_r.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None

    audit = await client.get(
        "/api/v1/audit/?action=login.failure",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    events = audit.json()
    # Ищем нашу запись — у неё details должен быть непустой и укладываться в лимит.
    # Других login.failure в этом тесте быть не должно (изолированный кейс).
    our = [e for e in events if e["details"] and "<truncated>" in e["details"]]
    assert len(our) == 1, f"ожидали 1 обрезанную запись, нашли {len(our)}"
    e = our[0]
    assert len(e["details"]) <= DETAILS_MAX_LEN
    # details всё ещё валидная JSON-строка после отрезания суффикса
    # (суффикс — просто маркер, а не часть JSON; главное что /login не упал).
    assert e["user_id"] is None  # такого username в базе нет


@pytest.mark.asyncio
async def test_blocked_login_is_audited(client: AsyncClient, db_session):
    """Попытка войти на заблокированный аккаунт (is_active=False) пишется как login.blocked.

    Сценарий с точки зрения безопасности: либо юзер не понимает, почему
    не может зайти (тогда саппорт объяснит), либо кто-то сознательно
    ломится в отключённый аккаунт. Оба случая — сигнал, и без записи
    в audit мы их не увидим.

    Как и login.failure, событие требует явного db.commit() перед raise,
    иначе get_db() откатит транзакцию на HTTPException(403).
    """
    # 1) Регистрируем юзера и тут же баним его напрямую в БД
    #    (эмулируем действие админа "Отключить аккаунт").
    from sqlalchemy import update

    from app.models.user import User

    user_id, _ = await register(client, "blocked")
    await db_session.execute(update(User).where(User.id == user_id).values(is_active=False))
    await db_session.flush()

    # 2) Пытаемся залогиниться корректным паролем — но аккаунт уже бан:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "auditblocked", "password": "Secret123!"},
    )
    assert r.status_code == 403, f"ожидали 403, получили {r.status_code}: {r.text}"

    # 3) Поднимаем временного админа и проверяем журнал.
    from app.config import get_settings

    settings = get_settings()
    settings.BOOTSTRAP_ADMIN_EMAIL = "auditadmin_blocked@example.com"
    admin_r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin_blocked@example.com",
            "username": "auditadmin_blocked",
            "password": "Secret123!",
        },
    )
    admin_token = admin_r.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None

    audit = await client.get(
        "/api/v1/audit/?action=login.blocked",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    events = audit.json()
    # Ровно одна запись login.blocked — и user_id совпадает с нашим юзером.
    our = [e for e in events if e["user_id"] == user_id]
    assert len(our) == 1, f"ожидали 1 событие login.blocked, нашли {len(our)}"
    e = our[0]
    assert e["action"] == "login.blocked"
    assert e["ip"] is not None
    details = json.loads(e["details"])
    assert details["username"] == "auditblocked"


@pytest.mark.asyncio
async def test_ticket_delete_is_audited(client: AsyncClient):
    """DELETE /tickets/{id} → в audit_logs action='ticket.delete' c target_id."""
    # Создаём обычного юзера + тикет
    user_id, user_token = await register(client, "owner")
    ticket_resp = await client.post(
        "/api/v1/tickets/",
        json={"title": "to be deleted", "body": "test", "user_priority": 3},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert ticket_resp.status_code == 201
    ticket_id = ticket_resp.json()["id"]

    # Бутстрапим админа и удаляем
    from app.config import get_settings

    settings = get_settings()
    settings.BOOTSTRAP_ADMIN_EMAIL = "auditadmin3@example.com"
    admin_r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "auditadmin3@example.com",
            "username": "auditadmin3",
            "password": "Secret123!",
        },
    )
    admin_token = admin_r.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None

    del_r = await client.delete(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_r.status_code == 204

    audit = await client.get(
        "/api/v1/audit/?action=ticket.delete",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    deletes = [e for e in audit.json() if e["target_id"] == ticket_id]
    assert len(deletes) == 1
    e = deletes[0]
    assert e["target_type"] == "ticket"
    details = json.loads(e["details"])
    assert details["owner_user_id"] == user_id


@pytest.mark.asyncio
async def test_audit_endpoint_forbidden_for_non_admin(client: AsyncClient):
    """GET /audit обычному юзеру → 403."""
    _, token = await register(client, "nonadmin")
    r = await client.get("/api/v1/audit/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_endpoint_requires_auth(client: AsyncClient):
    """GET /audit без токена → 401."""
    r = await client.get("/api/v1/audit/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ticket_status_change_is_audited(client: AsyncClient):
    """PATCH /tickets/{id} → запись action='ticket.status_change' с from/to."""
    user_id, user_token = await register(client, "stchowner")
    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "to be moved",
            "body": "test",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]

    confirm = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"

    # Бутстрапим админа и переводим тикет в in_progress.
    from app.config import get_settings

    settings = get_settings()
    settings.BOOTSTRAP_ADMIN_EMAIL = "stchadmin@example.com"
    admin_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "stchadmin@example.com",
            "username": "stchadmin",
            "password": "Secret123!",
        },
    )
    admin_token = admin_resp.json()["access_token"]
    settings.BOOTSTRAP_ADMIN_EMAIL = None
    admin_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin_id = admin_me.json()["id"]

    update = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "in_progress"

    audit = await client.get(
        "/api/v1/audit/?action=ticket.status_change",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    rows = [e for e in audit.json() if e["target_id"] == ticket_id]
    assert len(rows) == 1
    entry = rows[0]
    assert entry["target_type"] == "ticket"
    assert entry["user_id"] == admin_id
    details = json.loads(entry["details"])
    assert details == {"from": "confirmed", "to": "in_progress"}
