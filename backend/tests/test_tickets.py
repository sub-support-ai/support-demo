from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.ai_log import AILog
from app.models.ticket import Ticket
from app.models.user import User
from app.security import hash_password
from app.services.ai_classifier import _choose_priority, _infer_priority_from_text


def test_how_to_priority_heuristic_can_downgrade_ai_priority():
    inferred = _infer_priority_from_text(
        "я хочу обновить программу VS Code, как это сделать?",
        "нужна инструкция по обновлению приложения",
    )

    assert inferred == "низкий"
    assert _choose_priority("высокий", inferred) == "низкий"


# Регистрируем пользователя через /auth/register и возвращаем
# (user_id, access_token) — нужны для тикета и для заголовка Authorization.
async def register_user(client: AsyncClient, suffix: str = "") -> tuple[int, str]:
    response = await client.post("/api/v1/auth/register", json={
        "email": f"ticketuser{suffix}@example.com",
        "username": f"ticketuser{suffix}",
        "password": "Secret123!",
    })
    assert response.status_code == 201
    token = response.json()["access_token"]

    # /auth/me — узнаём id созданного пользователя
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    return me.json()["id"], token


async def register_admin(client: AsyncClient, suffix: str = "") -> tuple[int, str]:
    from app.config import get_settings

    settings = get_settings()
    admin_email = f"ticketadmin{suffix}@example.com"
    previous_bootstrap_email = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = admin_email
    try:
        response = await client.post("/api/v1/auth/register", json={
            "email": admin_email,
            "username": f"ticketadmin{suffix}",
            "password": "Secret123!",
        })
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = previous_bootstrap_email
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    return me.json()["id"], token


async def create_operator(
    client: AsyncClient,
    db_session: AsyncSession,
    suffix: str,
    role: str = "admin",
) -> tuple[int, str]:
    password = "Secret123!"
    user = User(
        email=f"operator{suffix}@example.com",
        username=f"operator{suffix}",
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": user.username, "password": password},
    )
    assert response.status_code == 200
    return user.id, response.json()["access_token"]


@pytest.mark.asyncio
async def test_create_ticket(client: AsyncClient):
    """Создание тикета: проверяем поля ответа и поведение AI-fallback.

    AI-сервис принудительно недостижим (autouse-фикстура _isolate_ai_service
    в conftest.py), поэтому classify_ticket всегда возвращает fallback:
    confidence=0.0, category="other", department="IT".
    """
    user_id, token = await register_user(client, suffix="create")

    response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "не могу войти в систему",
            "body": "при входе пишет ошибку 403",
            # user_id НЕ передаём — он берётся из JWT (current_user.id)
            "user_priority": 4,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    data = response.json()

    assert data["title"] == "не могу войти в систему"
    assert data["user_id"] == user_id
    assert data["user_priority"] == 4
    assert data["requester_name"] == "ticketusercreate"
    assert data["requester_email"] == "ticketusercreate@example.com"

    assert "id" in data
    assert data["id"] is not None

    # После AI обработки дефолтный статус — pending_user
    assert data["status"] == "pending_user"

    # classify_ticket замокан → всегда возвращает заглушку (confidence=0.0)
    assert data["ai_confidence"] == 0.0
    assert data["ai_category"] == "other"
    assert data["department"] == "IT"


@pytest.mark.asyncio
async def test_urgent_broken_hardware_gets_high_priority(client: AsyncClient):
    """Срочная поломка оборудования не должна оставаться средним приоритетом.

    AI-сервис недостижим (autouse-фикстура _isolate_ai_service) → classify_ticket
    возвращает fallback «средний» → текстовые маркеры (сроч/порван/надо заменить)
    через _choose_priority поднимают итоговый приоритет до «высокий».
    """
    _, token = await register_user(client, suffix="urgentmouse")

    response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "не работает мышка, порван провод, срочно надо заменить!",
            "body": "пользователь не может нормально работать",
            "user_priority": 3,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["ai_priority"] == "высокий"


@pytest.mark.asyncio
async def test_mass_outage_gets_critical_priority(client: AsyncClient):
    """Критический приоритет выдаётся системно для массовых сбоев."""
    _, token = await register_user(client, suffix="criticaloutage")

    response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "У всех не работает 1С",
            "body": "Весь отдел не может оформить заказы, простой продаж.",
            "user_priority": 3,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["ai_priority"] == "критический"


@pytest.mark.asyncio
async def test_manual_ticket_cannot_use_critical_user_priority(client: AsyncClient):
    _, token = await register_user(client, suffix="manualusercritical")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Не работает ноутбук",
            "body": "Пользователь просит проверить устройство",
            "user_priority": 1,
        },
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_how_to_update_software_gets_low_priority(client: AsyncClient):
    """How-to software requests should not be routed as urgent incidents."""
    _, token = await register_user(client, suffix="updatesoftware")

    response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "я хочу обновить программу VS Code, как это сделать?",
            "body": "нужна инструкция по обновлению приложения",
            "user_priority": 3,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["ai_priority"] == "низкий"


@pytest.mark.asyncio
async def test_pending_ticket_draft_can_be_edited_before_confirm(client: AsyncClient):
    _, token = await register_user(client, suffix="editdraft")
    headers = {"Authorization": f"Bearer {token}"}
    low_priority = "\u043d\u0438\u0437\u043a\u0438\u0439"

    create_resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "РЅРµ СЂР°Р±РѕС‚Р°РµС‚ РїСЂРёРЅС‚РµСЂ",
            "body": "РїРµС‡Р°С‚СЊ РЅРµ РёРґРµС‚",
            "user_priority": 3,
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    ticket_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}/draft",
        json={
            "title": "РќРµ РїРµС‡Р°С‚Р°РµС‚ РїСЂРёРЅС‚РµСЂ РІ Р±СѓС…РіР°Р»С‚РµСЂРёРё",
            "body": "РќСѓР¶РЅР° РїСЂРѕРІРµСЂРєР° РїСЂРёРЅС‚РµСЂР° Рё РґСЂР°Р№РІРµСЂР°.",
            "department": "IT",
            "ai_priority": low_priority,
            "requester_name": "Анна Иванова",
            "requester_email": "anna.ivanova@example.com",
            "office": "Главный офис",
            "affected_item": "Принтер/МФУ",
            "steps_tried": "РџРµСЂРµР·Р°РїСѓСЃРєР°Р»Рё РїСЂРёРЅС‚РµСЂ Рё РЅРѕСѓС‚Р±СѓРє.",
        },
        headers=headers,
    )

    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["title"] == "РќРµ РїРµС‡Р°С‚Р°РµС‚ РїСЂРёРЅС‚РµСЂ РІ Р±СѓС…РіР°Р»С‚РµСЂРёРё"
    assert updated["body"] == "РќСѓР¶РЅР° РїСЂРѕРІРµСЂРєР° РїСЂРёРЅС‚РµСЂР° Рё РґСЂР°Р№РІРµСЂР°."
    assert updated["department"] == "IT"
    assert updated["ai_priority"] == low_priority
    assert updated["requester_name"] == "Анна Иванова"
    assert updated["requester_email"] == "anna.ivanova@example.com"
    assert updated["office"] == "Главный офис"
    assert updated["affected_item"] == "Принтер/МФУ"
    assert updated["steps_tried"] == "РџРµСЂРµР·Р°РїСѓСЃРєР°Р»Рё РїСЂРёРЅС‚РµСЂ Рё РЅРѕСѓС‚Р±СѓРє."


@pytest.mark.asyncio
async def test_draft_context_fields_refresh_context_block(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await register_user(client, suffix="contextblock")
    headers = {"Authorization": f"Bearer {token}"}

    ticket = Ticket(
        user_id=user_id,
        title="Не работает VPN",
        body=(
            "Контекст обращения:\n"
            "Автор: Старый Автор <old@example.com>\n"
            "Создал: ticketusercontextblock <ticketusercontextblock@example.com>\n"
            "Офис: Старый офис\n"
            "Объект: Старый объект\n\n"
            "Пользователь: Не работает VPN"
        ),
        user_priority=3,
        department="IT",
        status="pending_user",
        confirmed_by_user=False,
        ai_priority="средний",
        ai_confidence=0.95,
        requester_name="Старый Автор",
        requester_email="old@example.com",
        office="Старый офис",
        affected_item="Старый объект",
    )
    db_session.add(ticket)
    await db_session.flush()

    update_resp = await client.patch(
        f"/api/v1/tickets/{ticket.id}/draft",
        json={
            "requester_name": "Новый Автор",
            "requester_email": "new@example.com",
            "office": "Главный офис",
            "affected_item": "VPN",
        },
        headers=headers,
    )

    assert update_resp.status_code == 200
    body = update_resp.json()["body"]
    assert "Автор: Новый Автор <new@example.com>" in body
    assert "Создал: ticketusercontextblock <ticketusercontextblock@example.com>" in body
    assert "Офис: Главный офис" in body
    assert "Объект: VPN" in body
    assert "Старый Автор" not in body
    assert "Старый офис" not in body
    assert "Пользователь: Не работает VPN" in body


@pytest.mark.asyncio
async def test_draft_priority_change_reroutes_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await register_user(client, suffix="reroutepriority")
    headers = {"Authorization": f"Bearer {token}"}

    free_agent = Agent(
        email="free-reroute@example.com",
        username="free-reroute",
        hashed_password=hash_password("Secret123!"),
        department="IT",
        active_ticket_count=2,
        ai_routing_score=0.1,
        is_active=True,
    )
    senior_agent = Agent(
        email="senior-reroute@example.com",
        username="senior-reroute",
        hashed_password=hash_password("Secret123!"),
        department="IT",
        active_ticket_count=0,
        ai_routing_score=0.9,
        is_active=True,
    )
    db_session.add_all([free_agent, senior_agent])
    await db_session.flush()

    ticket = Ticket(
        user_id=user_id,
        title="Нужно обновить приложение",
        body="Плановый запрос",
        user_priority=3,
        department="IT",
        status="pending_user",
        confirmed_by_user=False,
        ai_priority="низкий",
        ai_confidence=0.95,
        agent_id=free_agent.id,
    )
    db_session.add(ticket)
    await db_session.flush()

    update_resp = await client.patch(
        f"/api/v1/tickets/{ticket.id}/draft",
        json={"ai_priority": "высокий"},
        headers=headers,
    )

    assert update_resp.status_code == 200
    assert update_resp.json()["agent_id"] == senior_agent.id

    await db_session.refresh(free_agent)
    await db_session.refresh(senior_agent)
    assert free_agent.active_ticket_count == 1
    assert senior_agent.active_ticket_count == 1

    refreshed = await db_session.execute(select(Ticket).where(Ticket.id == ticket.id))
    assert refreshed.scalar_one().agent_id == senior_agent.id


@pytest.mark.asyncio
async def test_draft_priority_cannot_be_set_to_critical(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await register_user(client, suffix="manualcritical")
    headers = {"Authorization": f"Bearer {token}"}

    ticket = Ticket(
        user_id=user_id,
        title="Не работает ноутбук",
        body="Пользователь просит проверить устройство",
        user_priority=3,
        department="IT",
        status="pending_user",
        confirmed_by_user=False,
        ai_priority="средний",
        ai_confidence=0.95,
    )
    db_session.add(ticket)
    await db_session.flush()

    update_resp = await client.patch(
        f"/api/v1/tickets/{ticket.id}/draft",
        json={"ai_priority": "критический"},
        headers=headers,
    )

    assert update_resp.status_code == 422

    await db_session.refresh(ticket)
    assert ticket.ai_priority == "средний"


@pytest.mark.asyncio
async def test_confirmed_ticket_draft_cannot_be_edited(client: AsyncClient):
    _, token = await register_user(client, suffix="lockedraft")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "РЅРµ РѕС‚РєСЂС‹РІР°РµС‚СЃСЏ VPN",
            "body": "РѕС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=headers,
    )
    ticket_id = create_resp.json()["id"]

    confirm_resp = await client.patch(f"/api/v1/tickets/{ticket_id}/confirm", headers=headers)
    assert confirm_resp.status_code == 200

    update_resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}/draft",
        json={"title": "РЅРѕРІР°СЏ С‚РµРјР°"},
        headers=headers,
    )
    assert update_resp.status_code == 409


@pytest.mark.asyncio
async def test_list_tickets(client: AsyncClient):
    user_id, token = await register_user(client, suffix="list")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/api/v1/tickets/",
        json={
            "title": "первый тикет",
            "body": "описание первого",
            "user_priority": 3,
        },
        headers=headers,
    )

    await client.post(
        "/api/v1/tickets/",
        json={
            "title": "второй тикет",
            "body": "описание второго",
            "user_priority": 2,
        },
        headers=headers,
    )

    response = await client.get("/api/v1/tickets/", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2


# ── Ownership: пользователь не должен видеть чужие тикеты ─────────────────────

@pytest.mark.asyncio
async def test_list_tickets_returns_only_own(client: AsyncClient):
    """
    Два пользователя, каждый создаёт свой тикет.
    GET /tickets/ должен вернуть КАЖДОМУ только его тикет, не оба.
    """
    _, token_alice = await register_user(client, suffix="alice")
    _, token_bob = await register_user(client, suffix="bob")

    # Alice создаёт свой
    await client.post(
        "/api/v1/tickets/",
        json={"title": "тикет алисы", "body": "секрет алисы", "user_priority": 3},
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    # Bob создаёт свой
    await client.post(
        "/api/v1/tickets/",
        json={"title": "тикет боба", "body": "секрет боба", "user_priority": 3},
        headers={"Authorization": f"Bearer {token_bob}"},
    )

    # Alice видит только свои тикеты
    resp = await client.get(
        "/api/v1/tickets/",
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert resp.status_code == 200
    titles = {t["title"] for t in resp.json()}
    assert "тикет алисы" in titles
    assert "тикет боба" not in titles


@pytest.mark.asyncio
async def test_get_other_user_ticket_returns_404(client: AsyncClient):
    """
    Alice создаёт тикет, Bob пытается запросить его по ID → 404
    (именно 404, а не 403 — не палим существование тикета).
    """
    _, token_alice = await register_user(client, suffix="owngetA")
    _, token_bob = await register_user(client, suffix="owngetB")

    # Alice создаёт тикет и запоминает его id
    create = await client.post(
        "/api/v1/tickets/",
        json={"title": "чужой", "body": "чужой", "user_priority": 3},
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    alice_ticket_id = create.json()["id"]

    # Bob пытается его прочитать
    resp = await client.get(
        f"/api/v1/tickets/{alice_ticket_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_resolve_other_user_ticket(client: AsyncClient):
    """Bob не может закрыть тикет Alice → 404."""
    _, token_alice = await register_user(client, suffix="resA")
    _, token_bob = await register_user(client, suffix="resB")

    create = await client.post(
        "/api/v1/tickets/",
        json={"title": "чужой resolve", "body": "чужой", "user_priority": 3},
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    alice_ticket_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/tickets/{alice_ticket_id}/resolve",
        json={"agent_accepted_ai_response": True},
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_id_in_body_is_ignored(client: AsyncClient):
    """
    Даже если клиент подпихнёт user_id в JSON — он должен быть проигнорирован.
    Схема Pydantic его не принимает (extra fields разрешены, но не парсятся).
    Проверяем: ticket.user_id == current_user.id из токена.
    """
    alice_id, token_alice = await register_user(client, suffix="spoofA")
    bob_id, token_bob = await register_user(client, suffix="spoofB")

    # Alice создаёт тикет, пытается подставить user_id Боба
    resp = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "попытка спуфа",
            "body": "хочу создать от имени боба",
            "user_priority": 3,
            "user_id": bob_id,  # ← попытка атаки
        },
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert resp.status_code == 201
    # В базе тикет принадлежит Alice, а не Bob
    assert resp.json()["user_id"] == alice_id
    assert resp.json()["user_id"] != bob_id


@pytest.mark.asyncio
async def test_confirm_ticket_marks_user_confirmation(client: AsyncClient):
    """Пользователь подтверждает AI-черновик одним endpoint'ом."""
    _, token = await register_user(client, suffix="confirm")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "черновик из AI",
            "body": "нужно отправить в поддержку",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]
    assert create.json()["status"] == "pending_user"
    assert create.json()["confirmed_by_user"] is False

    confirm = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=headers,
    )
    assert confirm.status_code == 200
    data = confirm.json()
    assert data["id"] == ticket_id
    assert data["status"] == "confirmed"
    assert data["confirmed_by_user"] is True
    assert data["sla_started_at"] is not None
    assert data["sla_deadline_at"] is not None
    assert data["is_sla_breached"] is False


@pytest.mark.asyncio
async def test_confirm_ticket_sets_sla_deadline_by_priority(client: AsyncClient):
    """SLA = 8 ч для «высокий»; эвристика должна поднять фолбэк «средний» до «высокий».

    AI-сервис недостижим (autouse-фикстура _isolate_ai_service) → classify_ticket
    даёт «средний» → маркеры «слом»/«сроч» поднимают до «высокий» →
    SLA_HOURS_BY_PRIORITY[«высокий»] == 8.
    """
    _, token = await register_user(client, suffix="sla")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "сломано оборудование",
            "body": "срочно нужна замена",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "Ноутбук",
        },
        headers=headers,
    )
    assert create.status_code == 201

    confirm = await client.patch(
        f"/api/v1/tickets/{create.json()['id']}/confirm",
        headers=headers,
    )
    assert confirm.status_code == 200
    data = confirm.json()
    started_at = datetime.fromisoformat(data["sla_started_at"])
    deadline_at = datetime.fromisoformat(data["sla_deadline_at"])

    assert deadline_at - started_at == timedelta(hours=8)


@pytest.mark.asyncio
async def test_ticket_response_marks_overdue_sla(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await register_user(client, suffix="slaoverdue")
    headers = {"Authorization": f"Bearer {token}"}
    ticket = Ticket(
        user_id=user_id,
        title="Просроченный запрос",
        body="Проверяем SLA",
        user_priority=3,
        department="IT",
        status="confirmed",
        confirmed_by_user=True,
        ai_priority="средний",
        requester_name="User",
        requester_email="user@example.com",
        office="HQ",
        affected_item="VPN",
        sla_started_at=datetime.now(timezone.utc) - timedelta(hours=30),
        sla_deadline_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )
    db_session.add(ticket)
    await db_session.flush()

    response = await client.get(f"/api/v1/tickets/{ticket.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["is_sla_breached"] is True


@pytest.mark.asyncio
async def test_admin_can_add_ticket_comment_after_confirmation(
    client: AsyncClient,
    db_session: AsyncSession,
):
    _, user_token = await register_user(client, suffix="commentowner")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    _, admin_token = await create_operator(client, db_session, suffix="commentadmin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Не работает VPN",
            "body": "Нужно проверить доступ",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=user_headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]
    confirm = await client.patch(f"/api/v1/tickets/{ticket_id}/confirm", headers=user_headers)
    assert confirm.status_code == 200

    comment = await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"content": "Проверить учетную запись и VPN-группу."},
        headers=admin_headers,
    )

    assert comment.status_code == 201
    assert comment.json()["content"] == "Проверить учетную запись и VPN-группу."
    assert comment.json()["author_role"] == "admin"

    comments = await client.get(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=admin_headers,
    )
    assert comments.status_code == 200
    assert len(comments.json()) == 1


@pytest.mark.asyncio
async def test_regular_user_cannot_add_operator_comment(client: AsyncClient):
    _, token = await register_user(client, suffix="commentregular")
    headers = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Не работает принтер",
            "body": "Нужна помощь",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "Принтер/МФУ",
        },
        headers=headers,
    )
    ticket_id = create.json()["id"]
    confirm = await client.patch(f"/api/v1/tickets/{ticket_id}/confirm", headers=headers)
    assert confirm.status_code == 200

    comment = await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"content": "Попытка оставить внутренний комментарий"},
        headers=headers,
    )

    assert comment.status_code == 404


@pytest.mark.asyncio
async def test_confirm_ticket_requires_request_context(client: AsyncClient):
    _, token = await register_user(client, suffix="confirmcontext")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "draft without context",
            "body": "office and affected item must be required",
            "user_priority": 3,
        },
        headers=headers,
    )
    assert create.status_code == 201

    confirm = await client.patch(
        f"/api/v1/tickets/{create.json()['id']}/confirm",
        headers=headers,
    )

    assert confirm.status_code == 422
    assert set(confirm.json()["detail"]["fields"]) == {"office", "affected_item"}


@pytest.mark.asyncio
async def test_confirm_ticket_rejects_non_pending_draft(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Confirm не должен откатывать уже активный тикет в status=confirmed."""
    _, token = await register_user(client, suffix="confirmreject")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "уже в работе",
            "body": "агент уже взял тикет",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]

    result = await db_session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one()
    ticket.status = "in_progress"
    await db_session.flush()

    confirm = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=headers,
    )
    assert confirm.status_code == 409

    current = await client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=headers,
    )
    assert current.status_code == 200
    assert current.json()["status"] == "in_progress"
    assert current.json()["confirmed_by_user"] is False


@pytest.mark.asyncio
async def test_user_cannot_update_ticket_status_after_confirm(client: AsyncClient):
    _, token = await register_user(client, suffix="userstatus")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "confirmed ticket",
            "body": "regular user must not act as operator",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]

    confirm = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=headers,
    )
    assert confirm.status_code == 200

    update = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "closed"},
        headers=headers,
    )

    assert update.status_code == 404


@pytest.mark.asyncio
async def test_confirm_ticket_sets_sla_deadline(client: AsyncClient):
    _, token = await register_user(client, suffix="sla")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "не работает VPN",
            "body": "ошибка подключения",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "VPN",
        },
        headers=headers,
    )
    assert create.status_code == 201

    confirm = await client.patch(
        f"/api/v1/tickets/{create.json()['id']}/confirm",
        headers=headers,
    )

    assert confirm.status_code == 200
    data = confirm.json()
    assert data["sla_started_at"] is not None
    assert data["sla_deadline_at"] is not None
    assert data["is_sla_breached"] is False


@pytest.mark.asyncio
async def test_admin_can_add_comment_to_confirmed_ticket(client: AsyncClient):
    _, user_token = await register_user(client, suffix="comment")
    _, admin_token = await register_admin(client, suffix="comment")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "сломано оборудование",
            "body": "не включается монитор",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "Монитор",
        },
        headers=user_headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]

    confirm = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=user_headers,
    )
    assert confirm.status_code == 200

    comment = await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"content": "Взяли в диагностику", "internal": True},
        headers=admin_headers,
    )
    assert comment.status_code == 201
    assert comment.json()["content"] == "Взяли в диагностику"

    comments = await client.get(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=admin_headers,
    )
    assert comments.status_code == 200
    assert len(comments.json()) == 1


@pytest.mark.asyncio
async def test_user_cannot_see_internal_comments(client: AsyncClient):
    _, user_token = await register_user(client, suffix="internal-vis")
    _, admin_token = await register_admin(client, suffix="internal-vis")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "не работает принтер",
            "body": "бумага застряла",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "Принтер",
        },
        headers=user_headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]

    assert (await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=user_headers,
    )).status_code == 200

    assert (await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"content": "Внутренняя заметка агента", "internal": True},
        headers=admin_headers,
    )).status_code == 201

    assert (await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        json={"content": "Взяли в работу", "internal": False},
        headers=admin_headers,
    )).status_code == 201

    user_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=user_headers,
    )
    assert user_resp.status_code == 200
    user_comments = user_resp.json()
    assert len(user_comments) == 1
    assert user_comments[0]["content"] == "Взяли в работу"
    assert user_comments[0]["internal"] is False

    admin_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=admin_headers,
    )
    assert admin_resp.status_code == 200
    assert len(admin_resp.json()) == 2


@pytest.mark.asyncio
async def test_negative_feedback_can_reopen_closed_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
):
    _, user_token = await register_user(client, suffix="reopen")
    _, admin_token = await register_admin(client, suffix="reopen")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "не работает почта",
            "body": "письма не отправляются",
            "user_priority": 3,
            "office": "HQ",
            "affected_item": "Почта",
        },
        headers=user_headers,
    )
    assert create.status_code == 201
    ticket_id = create.json()["id"]
    assert (await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=user_headers,
    )).status_code == 200

    resolve = await client.patch(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"agent_accepted_ai_response": False},
        headers=admin_headers,
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "closed"

    feedback = await client.patch(
        f"/api/v1/tickets/{ticket_id}/feedback",
        json={"feedback": "not_helped", "reopen": True},
        headers=user_headers,
    )
    assert feedback.status_code == 200
    data = feedback.json()
    assert data["status"] == "confirmed"
    assert data["reopen_count"] == 1
    assert data["resolved_at"] is None

    result = await db_session.execute(
        select(AILog)
        .where(AILog.ticket_id == ticket_id)
        .order_by(AILog.id.desc())
        .limit(1)
    )
    assert result.scalar_one().user_feedback == "not_helped"
