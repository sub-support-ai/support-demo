from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.user import User


async def _register_user_with_id(client: AsyncClient, suffix: str) -> tuple[int, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"jobs-{suffix}@example.com",
            "username": f"jobs_{suffix}",
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
async def test_admin_can_list_failed_jobs(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "list")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    conversation = Conversation(user_id=admin_id, status="active")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        AIJob(
            conversation_id=conversation.id,
            status="failed",
            attempts=3,
            max_attempts=3,
            run_after=datetime.now(timezone.utc),
            error="Ollama timeout",
        )
    )
    db_session.add(
        KnowledgeEmbeddingJob(
            article_id=None,
            requested_by_user_id=admin_id,
            status="failed",
            attempts=3,
            max_attempts=3,
            run_after=datetime.now(timezone.utc),
            error="Embedding service unavailable",
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/jobs/failed",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ai"][0]["error"] == "Ollama timeout"
    assert data["knowledge_embeddings"][0]["error"] == "Embedding service unavailable"


@pytest.mark.asyncio
async def test_regular_user_cannot_list_failed_jobs(client: AsyncClient):
    _, token = await _register_user_with_id(client, "regular")

    response = await client.get(
        "/api/v1/jobs/failed",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_filter_jobs_by_kind_and_status(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "filter")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    conversation = Conversation(user_id=admin_id, status="active")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        AIJob(
            conversation_id=conversation.id,
            status="queued",
            attempts=0,
            max_attempts=3,
            run_after=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        KnowledgeEmbeddingJob(
            article_id=None,
            requested_by_user_id=admin_id,
            status="failed",
            attempts=3,
            max_attempts=3,
            run_after=datetime.now(timezone.utc),
            error="Embedding service unavailable",
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/jobs/?kind=knowledge_embeddings&status=failed",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ai"] == []
    assert len(data["knowledge_embeddings"]) == 1
    assert data["knowledge_embeddings"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_admin_can_retry_failed_ai_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "retryai")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    conversation = Conversation(user_id=admin_id, status="active")
    db_session.add(conversation)
    await db_session.flush()
    job = AIJob(
        conversation_id=conversation.id,
        status="failed",
        attempts=3,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        error="temporary failure",
        finished_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/ai/{job.id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["attempts"] == 0
    assert data["error"] is None
    await db_session.refresh(conversation)
    assert conversation.status == "ai_processing"


@pytest.mark.asyncio
async def test_admin_can_retry_failed_knowledge_embedding_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "retryknowledge")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    article = KnowledgeArticle(
        department="IT",
        title="VPN",
        body="VPN troubleshooting",
        is_active=True,
    )
    db_session.add(article)
    await db_session.flush()
    job = KnowledgeEmbeddingJob(
        article_id=article.id,
        requested_by_user_id=admin_id,
        status="failed",
        attempts=3,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        error="embedding failed",
        finished_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/knowledge-embeddings/{job.id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["attempts"] == 0
    assert data["error"] is None


@pytest.mark.asyncio
async def test_admin_can_requeue_running_ai_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueai")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    conversation = Conversation(user_id=admin_id, status="ai_processing")
    db_session.add(conversation)
    await db_session.flush()
    job = AIJob(
        conversation_id=conversation.id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/ai/{job.id}/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["locked_at"] is None
    assert data["started_at"] is None
    assert data["error"] == "Job was manually returned to queue"


@pytest.mark.asyncio
async def test_admin_can_requeue_running_knowledge_embedding_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueknowledge")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/knowledge-embeddings/{job.id}/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["locked_at"] is None
    assert data["started_at"] is None
    assert data["error"] == "Job was manually returned to queue"
