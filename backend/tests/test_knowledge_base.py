from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback, KnowledgeChunk
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.message import Message
from app.models.user import User
from app.services.knowledge_embeddings import (
    EmbeddingBatch,
    estimate_token_count,
    mark_chunk_embedded,
    needs_embedding,
    vector_literal,
)
from app.services.knowledge_base import find_knowledge_answer, search_knowledge_articles
from app.services.knowledge_base import (
    KnowledgeMatch,
    split_knowledge_text,
    sync_knowledge_article_index,
    _merge_matches,
)
from app.services.knowledge_embedding_jobs import (
    enqueue_knowledge_embedding_job,
    process_knowledge_embedding_job,
)


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


def test_knowledge_embedding_helpers_mark_chunk_ready():
    chunk = KnowledgeChunk(
        article_id=1,
        chunk_index=0,
        content="vpn profile mfa error",
        is_active=True,
    )

    assert needs_embedding(chunk, "nomic-embed-text") is True

    mark_chunk_embedded(chunk, "nomic-embed-text")

    assert chunk.embedding_model == "nomic-embed-text"
    assert chunk.embedding_updated_at is not None
    assert chunk.token_count == estimate_token_count(chunk.content)
    assert needs_embedding(chunk, "nomic-embed-text") is False
    assert vector_literal([0.1, -0.25, 1.0]) == "[0.10000000,-0.25000000,1.00000000]"


def test_merge_knowledge_matches_deduplicates_by_highest_score():
    low = KnowledgeArticle(title="VPN", body="low")
    low.id = 1
    high = KnowledgeArticle(title="VPN", body="high")
    high.id = 1
    other = KnowledgeArticle(title="Printer", body="other")
    other.id = 2

    matches = _merge_matches(
        [KnowledgeMatch(article=low, score=5.0, decision="clarify")],
        [
            KnowledgeMatch(
                article=high,
                score=9.0,
                decision="answer",
                snippet="best chunk",
                chunk_id=10,
                retrieval="semantic",
            ),
            KnowledgeMatch(article=other, score=7.0, decision="clarify"),
        ],
        limit=2,
    )

    assert [match.article.id for match in matches] == [1, 2]
    assert matches[0].score == 9.0
    assert matches[0].decision == "answer"
    assert matches[0].snippet == "best chunk"
    assert matches[0].chunk_id == 10
    assert matches[0].retrieval == "semantic"


def test_split_knowledge_text_uses_overlap_for_long_content():
    text = " ".join(f"token-{index}" for index in range(12))

    chunks = split_knowledge_text(text, target_tokens=5, overlap_tokens=2)

    assert chunks == [
        "token-0 token-1 token-2 token-3 token-4",
        "token-3 token-4 token-5 token-6 token-7",
        "token-6 token-7 token-8 token-9 token-10",
        "token-9 token-10 token-11",
    ]


@pytest.mark.asyncio
async def test_sync_knowledge_article_index_rebuilds_chunks_and_resets_embeddings(
    db_session: AsyncSession,
):
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN",
        title="VPN troubleshooting",
        body=" ".join(f"initial-{index}" for index in range(260)),
        problem="VPN cannot connect",
        symptoms=["connection timeout"],
        required_context=["office", "login", "error code"],
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    await sync_knowledge_article_index(db_session, article)
    await db_session.flush()

    chunks = (
        await db_session.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.article_id == article.id)
            .order_by(KnowledgeChunk.chunk_index.asc())
        )
    ).scalars().all()
    assert len(chunks) >= 2
    assert all(chunk.is_active for chunk in chunks)
    assert all(chunk.token_count for chunk in chunks)

    first_chunk = chunks[0]
    first_chunk.embedding_model = "nomic-embed-text"
    first_chunk.embedding_updated_at = datetime.now(timezone.utc)
    first_chunk.content = "stale content"
    await db_session.flush()

    await sync_knowledge_article_index(db_session, article)
    await db_session.flush()
    await db_session.refresh(first_chunk)

    assert first_chunk.content != "stale content"
    assert first_chunk.embedding_model is None
    assert first_chunk.embedding_updated_at is None


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
    assert answer["sources"][0]["retrieval"] == "keyword"
    assert answer["sources"][0]["snippet"]
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
    assert data[0]["retrieval"] == "keyword"
    assert data[0]["snippet"]


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
    chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id)
        )
    ).scalars().all()
    assert chunks
    assert chunks[0].is_active is True


@pytest.mark.asyncio
async def test_admin_can_enqueue_knowledge_article_reindex_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "adminreindex")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN",
        title="VPN reindex",
        body="VPN troubleshooting content",
        keywords="vpn",
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/knowledge/{article.id}/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["article_id"] == article.id
    assert data["requested_by_user_id"] == admin_id
    assert data["status"] == "queued"

    jobs = (
        await db_session.execute(
            select(KnowledgeEmbeddingJob).where(KnowledgeEmbeddingJob.article_id == article.id)
        )
    ).scalars().all()
    assert len(jobs) == 1

    chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id)
        )
    ).scalars().all()
    assert chunks


@pytest.mark.asyncio
async def test_admin_can_enqueue_full_knowledge_reindex_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "adminreindexall")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    response = await client.post(
        "/api/v1/knowledge/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["article_id"] is None
    assert data["requested_by_user_id"] == admin_id
    assert data["status"] == "queued"

    jobs = (
        await db_session.execute(
            select(KnowledgeEmbeddingJob).where(KnowledgeEmbeddingJob.article_id.is_(None))
        )
    ).scalars().all()
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_process_knowledge_embedding_job_marks_chunks_embedded(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN",
        title="VPN embedding job",
        body="VPN troubleshooting content",
        keywords="vpn",
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()
    await sync_knowledge_article_index(db_session, article)
    job = await enqueue_knowledge_embedding_job(
        db_session,
        article_id=article.id,
        requested_by_user_id=None,
    )
    await db_session.flush()

    async def fake_embed_texts(texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            model="test-embedding",
            embeddings=[[0.1, 0.2, 0.3] for _ in texts],
        )

    monkeypatch.setattr(
        "app.services.knowledge_embedding_jobs.embed_texts",
        fake_embed_texts,
    )

    await process_knowledge_embedding_job(db_session, job, batch_size=4)
    await db_session.flush()

    assert job.status == "done"
    assert job.updated_chunks >= 1
    assert job.embedding_model == "test-embedding"

    chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id)
        )
    ).scalars().all()
    assert chunks
    assert all(chunk.embedding_model == "test-embedding" for chunk in chunks)
    assert all(chunk.embedding_updated_at is not None for chunk in chunks)


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


# ── Блок 4: пороги RAG настраиваются через Settings ──────────────────────────


@pytest.mark.asyncio
async def test_knowledge_list_exposes_aggregated_feedback_counts(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /api/v1/knowledge/ должен отдавать helped/not_helped/not_relevant
    счётчики, чтобы админка показывала «полезность» статьи без N+1 запросов.

    Проверяем end-to-end: три разных feedback'а через POST /knowledge/feedback,
    счётчики на статье обновлены, GET /knowledge/ возвращает их в JSON.
    """
    user_id, token = await _register_user_with_id(client, "kbagg")
    article = KnowledgeArticle(
        department="IT",
        request_type="VPN не работает",
        title="VPN agg-test",
        body="agg body",
        keywords="vpn agg",
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()

    # Три отдельных диалога, по одному feedback'у каждого типа — реалистичный
    # сценарий, в котором три разных пользователя оценили одну и ту же статью.
    feedbacks_to_send = ("helped", "not_helped", "not_relevant")
    for kind in feedbacks_to_send:
        conversation = Conversation(user_id=user_id, status="active")
        db_session.add(conversation)
        await db_session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="ai",
            content=f"Ответ для feedback={kind}",
        )
        db_session.add(message)
        await db_session.flush()
        # Базовая запись feedback без оценки — её апдейтит POST /knowledge/feedback.
        db_session.add(
            KnowledgeArticleFeedback(
                article_id=article.id,
                conversation_id=conversation.id,
                message_id=message.id,
                user_id=user_id,
                query="vpn",
                score=10.0,
                decision="answer",
            )
        )
        await db_session.flush()
        response = await client.post(
            "/api/v1/knowledge/feedback",
            json={
                "message_id": message.id,
                "article_id": article.id,
                "feedback": kind,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

    # Проверяем агрегаты в API списка — именно их потребляет админка
    listing = await client.get(
        "/api/v1/knowledge/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    [item] = [a for a in listing.json() if a["id"] == article.id]
    assert item["helped_count"] == 1
    assert item["not_helped_count"] == 1
    assert item["not_relevant_count"] == 1


@pytest.mark.asyncio
async def test_unreachable_high_threshold_forces_escalate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """С пороговым значением 1000 ни одна KB-статья не даст «answer».

    Это подтверждает, что хардкод порогов снят — теперь дашборд админа на
    клиенте может тюнить чувствительность KB без релиза. Если бы пороги
    остались константами, тест прошёл бы и до Блока 4.
    """
    from app.config import get_settings
    from app.services.knowledge_base import _decision_for_score

    monkeypatch.setattr(get_settings(), "RAG_SCORE_HIGH_THRESHOLD", 1000.0)
    monkeypatch.setattr(get_settings(), "RAG_SCORE_MEDIUM_THRESHOLD", 999.0)

    # Скоры реальных match'ей в KB обычно 5–30; 50 — точно «выше среднего»
    # для KB ответа. С порогом 999 даже это даёт «escalate».
    assert _decision_for_score(50.0) == "escalate"
    assert _decision_for_score(998.0) == "escalate"
    assert _decision_for_score(999.5) == "clarify"
    assert _decision_for_score(1000.5) == "answer"


@pytest.mark.asyncio
async def test_zero_red_zone_disables_forced_escalation(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """RAG_CONFIDENCE_RED_ZONE=0 → ни один confidence не уйдёт в escalation
    автоматически (только если AI сам попросил escalate).

    Симметричный сценарий проверяет дефолтный порог 0.6 в test_conversations.py
    (test_post_message_ai_unavailable_marks_red_zone).
    """
    from app.config import get_settings
    from app.services import conversation_ai

    monkeypatch.setattr(get_settings(), "RAG_CONFIDENCE_RED_ZONE", 0.0)

    # AI отвечает с низкой confidence, но НЕ просит escalate
    async def low_confidence_no_escalate(conversation_id, messages):
        return {
            "answer": "ok",
            "confidence": 0.1,  # ниже дефолтного red zone
            "escalate": False,
            "sources": [],
            "model_version": "test",
        }

    monkeypatch.setattr(conversation_ai, "get_ai_answer", low_confidence_no_escalate)

    from tests.test_conversations import register_user, process_next_ai_job

    _, token = await register_user(client, "rzdisabled")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = (await client.post("/api/v1/conversations/", headers=headers)).json()["id"]
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "anything"},
        headers=headers,
    )
    await process_next_ai_job(db_session)

    history = await client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    ai_msg = history.json()[-1]
    # Красная зона выключена (порог 0), AI не просил escalate → флаг False
    assert ai_msg["requires_escalation"] is False
