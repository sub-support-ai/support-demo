import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback
from app.models.message import Message
from app.models.user import User
from app.services.knowledge_base import find_knowledge_answer, search_knowledge_articles


@pytest.mark.asyncio
async def test_search_knowledge_articles_ranks_matching_article(db_session: AsyncSession):
    vpn = KnowledgeArticle(
        department="IT",
        request_type="VPN не работает",
        title="VPN не подключается",
        body="Проверьте интернет, профиль подключения и MFA-код.",
        keywords="vpn впн удаленный доступ подключение",
        is_active=True,
    )
    printer = KnowledgeArticle(
        department="IT",
        request_type="Сломано оборудование",
        title="Принтер не печатает",
        body="Проверьте бумагу и очередь печати.",
        keywords="принтер печать мфу",
        is_active=True,
    )
    db_session.add_all([vpn, printer])
    await db_session.flush()

    matches = await search_knowledge_articles(
        db_session,
        "VPN не подключается, ошибка удаленного доступа",
    )

    assert matches
    assert matches[0].article.id == vpn.id
    assert matches[0].score > 0


@pytest.mark.asyncio
async def test_find_knowledge_answer_builds_sources(db_session: AsyncSession):
    article = KnowledgeArticle(
        department="IT",
        request_type="Сброс пароля",
        title="Сброс пароля учётной записи",
        body="Проверьте раскладку и портал самообслуживания.",
        keywords="пароль сброс логин учетная запись",
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    answer = await find_knowledge_answer(
        db_session,
        [{"role": "user", "content": "Не могу войти, нужен сброс пароля"}],
    )

    assert answer is not None
    assert answer["escalate"] is False
    assert answer["confidence"] >= 0.6
    assert answer["sources"][0]["title"] == article.title
    assert answer["sources"][0]["article_id"] == article.id
    assert answer["sources"][0]["decision"] == "answer"
    assert "Проверьте раскладку" in answer["answer"]


@pytest.mark.asyncio
async def test_find_knowledge_answer_asks_for_context_on_medium_match(db_session: AsyncSession):
    article = KnowledgeArticle(
        department="IT",
        request_type="Доступ к порталу",
        title="Портал",
        body="Инструкция зависит от конкретной системы и офиса.",
        required_context=["система", "офис", "код ошибки"],
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    answer = await find_knowledge_answer(
        db_session,
        [{"role": "user", "content": "Портал"}],
    )

    assert answer is not None
    assert answer["escalate"] is False
    assert answer["sources"][0]["decision"] == "clarify"
    assert "уточните: система, офис, код ошибки" in answer["answer"]


@pytest.mark.asyncio
async def test_search_knowledge_articles_drops_irrelevant_low_score(db_session: AsyncSession):
    db_session.add(
        KnowledgeArticle(
            department="IT",
            request_type="VPN не работает",
            title="VPN не подключается",
            body="Проверьте интернет, профиль подключения и MFA-код.",
            keywords="vpn впн удаленный доступ подключение",
            is_active=True,
        )
    )
    await db_session.flush()

    matches = await search_knowledge_articles(db_session, "порвался провод срочно")

    assert matches == []


async def _register_user(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "kb-user@example.com",
            "username": "kb_user",
            "password": "Secret123!",
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


async def _register_user_with_id(client: AsyncClient, suffix: str) -> tuple[int, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"kb-{suffix}@example.com",
            "username": f"kb_{suffix}",
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


@pytest.mark.asyncio
async def test_knowledge_search_endpoint_requires_auth_and_returns_matches(
    client: AsyncClient,
    db_session: AsyncSession,
):
    db_session.add(
        KnowledgeArticle(
            department="IT",
            request_type="VPN не работает",
            title="VPN не подключается",
            body="Проверьте интернет и профиль подключения.",
            keywords="vpn подключение удаленный доступ",
            is_active=True,
        )
    )
    await db_session.flush()

    unauthorized = await client.get("/api/v1/knowledge/search?q=vpn")
    assert unauthorized.status_code == 401

    token = await _register_user(client)
    response = await client.get(
        "/api/v1/knowledge/search?q=vpn",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "VPN не подключается"
    assert data[0]["score"] > 0
    assert data[0]["decision"] == "answer"


@pytest.mark.asyncio
async def test_admin_can_update_knowledge_article_and_rebuild_search_text(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "adminupdate")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN не работает",
        title="VPN не подключается",
        body="Старая инструкция",
        keywords="vpn",
        version=1,
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/knowledge/{article.id}",
        json={
            "title": "VPN: ошибка 809",
            "body": "Новая инструкция",
            "symptoms": ["ошибка 809"],
            "required_context": ["офис", "логин", "код ошибки"],
            "owner": "IT support",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "VPN: ошибка 809"
    assert data["version"] == 2
    await db_session.refresh(article)
    assert article.search_text is not None
    assert "ошибка 809" in article.search_text
    assert "код ошибки" in article.search_text


@pytest.mark.asyncio
async def test_stats_counts_knowledge_answer_as_resolved_without_specialist(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await _register_user_with_id(client, "stats")
    conversation = Conversation(user_id=user_id, status="active")
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(
        AILog(
            ticket_id=None,
            conversation_id=conversation.id,
            model_version="knowledge-base-v1",
            predicted_category="knowledge_base",
            predicted_priority="низкий",
            confidence_score=0.9,
            ai_response_draft="Проверочное решение из базы знаний",
            ai_response_time_ms=0,
            outcome="resolved_by_ai",
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/stats/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["ai"]["resolved_by_ai_count"] == 1


@pytest.mark.asyncio
async def test_knowledge_feedback_updates_article_counters(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user_id, token = await _register_user_with_id(client, "feedback")
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN не работает",
        title="VPN не подключается",
        body="Проверка VPN",
        keywords="vpn",
        is_active=True,
    )
    conversation = Conversation(user_id=user_id, status="active")
    db_session.add_all([article, conversation])
    await db_session.flush()
    message = Message(
        conversation_id=conversation.id,
        role="ai",
        content="Ответ из базы знаний",
    )
    db_session.add(message)
    await db_session.flush()
    feedback = KnowledgeArticleFeedback(
        article_id=article.id,
        conversation_id=conversation.id,
        message_id=message.id,
        user_id=user_id,
        query="vpn",
        score=10.0,
        decision="answer",
    )
    db_session.add(feedback)
    await db_session.flush()

    response = await client.post(
        "/api/v1/knowledge/feedback",
        json={
            "message_id": message.id,
            "article_id": article.id,
            "feedback": "helped",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["feedback"] == "helped"
    await db_session.refresh(article)
    assert article.helped_count == 1

    response = await client.post(
        "/api/v1/knowledge/feedback",
        json={
            "message_id": message.id,
            "article_id": article.id,
            "feedback": "not_relevant",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    await db_session.refresh(article)
    assert article.helped_count == 0
    assert article.not_relevant_count == 1
