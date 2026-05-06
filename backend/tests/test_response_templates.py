import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import Agent
from app.models.response_template import ResponseTemplate
from app.models.user import User
from app.security import hash_password


async def register_admin(client: AsyncClient, suffix: str) -> str:
    settings = get_settings()
    admin_email = f"templates-admin-{suffix}@example.com"
    previous_bootstrap_email = settings.BOOTSTRAP_ADMIN_EMAIL
    settings.BOOTSTRAP_ADMIN_EMAIL = admin_email
    try:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email,
                "username": f"templates_admin_{suffix}",
                "password": "Secret123!",
            },
        )
    finally:
        settings.BOOTSTRAP_ADMIN_EMAIL = previous_bootstrap_email

    assert response.status_code == 201
    return response.json()["access_token"]


async def create_agent_user(db: AsyncSession, suffix: str, department: str = "IT") -> User:
    password_hash = hash_password("Secret123!")
    user = User(
        email=f"templates-agent-{suffix}@example.com",
        username=f"templates_agent_{suffix}",
        hashed_password=password_hash,
        role="agent",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        Agent(
            user_id=user.id,
            email=user.email,
            username=user.username,
            hashed_password=password_hash,
            department=department,
            is_active=True,
        )
    )
    await db.flush()
    return user


async def login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "Secret123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_can_create_response_template(client: AsyncClient):
    token = await register_admin(client, "create")

    response = await client.post(
        "/api/v1/response-templates/",
        json={
            "department": "IT",
            "request_type": "VPN не работает",
            "title": "VPN диагностика",
            "body": "Здравствуйте, {requester_name}. Проверяем VPN.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["department"] == "IT"
    assert data["request_type"] == "VPN не работает"
    assert data["title"] == "VPN диагностика"


@pytest.mark.asyncio
async def test_agent_sees_matching_and_global_templates(
    client: AsyncClient,
    db_session: AsyncSession,
):
    agent = await create_agent_user(db_session, "list", department="IT")
    db_session.add_all(
        [
            ResponseTemplate(
                department="IT",
                request_type="VPN не работает",
                title="IT VPN",
                body="IT VPN body",
                is_active=True,
            ),
            ResponseTemplate(
                department=None,
                request_type=None,
                title="Общий",
                body="Common body",
                is_active=True,
            ),
            ResponseTemplate(
                department="HR",
                request_type="HR-запрос",
                title="HR",
                body="HR body",
                is_active=True,
            ),
        ]
    )
    await db_session.flush()
    token = await login(client, agent.username)

    response = await client.get(
        "/api/v1/response-templates/",
        params={"department": "IT", "request_type": "VPN не работает"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert titles == {"IT VPN", "Общий"}


@pytest.mark.asyncio
async def test_regular_user_cannot_list_response_templates(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "templates-user@example.com",
            "username": "templates_user",
            "password": "Secret123!",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    response = await client.get(
        "/api/v1/response-templates/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
