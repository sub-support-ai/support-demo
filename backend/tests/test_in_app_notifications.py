import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.notification import Notification
from app.models.user import User
from app.security import hash_password


async def register_user(client: AsyncClient, suffix: str = "") -> tuple[int, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"notifyuser{suffix}@example.com",
            "username": f"notifyuser{suffix}",
            "password": "Secret123!",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    return me.json()["id"], token


async def create_agent_user(
    client: AsyncClient,
    db_session: AsyncSession,
    suffix: str,
    department: str = "IT",
) -> tuple[int, str]:
    password = "Secret123!"
    user = User(
        email=f"notifyagent{suffix}@example.com",
        username=f"notifyagent{suffix}",
        hashed_password=hash_password(password),
        role="agent",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Agent(
            user_id=user.id,
            email=user.email,
            username=user.username,
            hashed_password=user.hashed_password,
            department=department,
            is_active=True,
        )
    )
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": user.username, "password": password},
    )
    assert response.status_code == 200
    return user.id, response.json()["access_token"]


@pytest.mark.asyncio
async def test_user_can_list_and_mark_own_notifications(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await register_user(client, "owner")
    _, other_token = await register_user(client, "other")

    db_session.add(
        Notification(
            user_id=user_id,
            event_type="ticket.comment_added",
            title="Новый ответ по запросу",
            body="Специалист добавил комментарий.",
            target_type="ticket",
            target_id=42,
        )
    )
    await db_session.flush()

    owner_headers = {"Authorization": f"Bearer {token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    count_response = await client.get(
        "/api/v1/notifications/unread-count",
        headers=owner_headers,
    )
    assert count_response.status_code == 200
    assert count_response.json()["unread_count"] == 1

    other_count_response = await client.get(
        "/api/v1/notifications/unread-count",
        headers=other_headers,
    )
    assert other_count_response.status_code == 200
    assert other_count_response.json()["unread_count"] == 0

    list_response = await client.get("/api/v1/notifications/", headers=owner_headers)
    assert list_response.status_code == 200
    notification = list_response.json()[0]
    assert notification["title"] == "Новый ответ по запросу"
    assert notification["target_type"] == "ticket"
    assert notification["target_id"] == 42
    assert notification["is_read"] is False

    missing_response = await client.patch(
        f"/api/v1/notifications/{notification['id']}/read",
        headers=other_headers,
    )
    assert missing_response.status_code == 404

    read_response = await client.patch(
        f"/api/v1/notifications/{notification['id']}/read",
        headers=owner_headers,
    )
    assert read_response.status_code == 200
    assert read_response.json()["is_read"] is True
    assert read_response.json()["read_at"] is not None

    count_after_read = await client.get(
        "/api/v1/notifications/unread-count",
        headers=owner_headers,
    )
    assert count_after_read.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_confirm_ticket_notifies_assigned_agent(
    client: AsyncClient,
    db_session: AsyncSession,
):
    _, agent_token = await create_agent_user(client, db_session, "assigned")
    _, user_token = await register_user(client, "requester")

    user_headers = {"Authorization": f"Bearer {user_token}"}
    ticket_response = await client.post(
        "/api/v1/tickets/",
        json={
            "title": "Не открывается корпоративный портал",
            "body": "После входа вижу ошибку 403.",
            "user_priority": 3,
            "department": "IT",
            "office": "Москва",
            "affected_item": "корпоративный портал",
        },
        headers=user_headers,
    )
    assert ticket_response.status_code == 201

    ticket_id = ticket_response.json()["id"]
    confirm_response = await client.patch(
        f"/api/v1/tickets/{ticket_id}/confirm",
        headers=user_headers,
    )
    assert confirm_response.status_code == 200

    agent_headers = {"Authorization": f"Bearer {agent_token}"}
    count_response = await client.get(
        "/api/v1/notifications/unread-count",
        headers=agent_headers,
    )
    assert count_response.status_code == 200
    assert count_response.json()["unread_count"] == 1

    list_response = await client.get("/api/v1/notifications/", headers=agent_headers)
    assert list_response.status_code == 200
    notification = list_response.json()[0]
    assert notification["event_type"] == "ticket.assigned"
    assert notification["target_type"] == "ticket"
    assert notification["target_id"] == ticket_id
