from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.message import Message
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
async def test_process_ai_job_skips_duplicate_response_for_same_user_turn(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user_id, _ = await _register_user_with_id(client, "skipduplicate")
    conversation = Conversation(
        user_id=user_id,
        status="ai_processing",
        ai_stage="generating",
    )
    db_session.add(conversation)
    await db_session.flush()
    db_session.add_all(
        [
            Message(
                conversation_id=conversation.id,
                role="user",
                content="Не открывается 1С",
            ),
            Message(
                conversation_id=conversation.id,
                role="ai",
                content="Уже созданный ответ по этому сообщению.",
            ),
        ]
    )
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

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("duplicate AI response generation")

    monkeypatch.setattr("app.services.ai_jobs.generate_ai_message", fail_if_called)

    from app.services.ai_jobs import process_ai_job

    await process_ai_job(db_session, job)

    await db_session.refresh(conversation)
    assert job.status == "done"
    assert conversation.status == "active"
    assert conversation.ai_stage is None

    ai_messages = (
        await db_session.execute(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role == "ai",
            )
        )
    ).scalars().all()
    assert len(ai_messages) == 1


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


@pytest.mark.asyncio
async def test_regular_user_cannot_requeue_ai_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, _ = await _register_user_with_id(client, "requeueaiowner")
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

    _, user_token = await _register_user_with_id(client, "requeueairegular")

    response = await client.post(
        f"/api/v1/jobs/ai/{job.id}/requeue",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_requeue_unknown_ai_job_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueai404")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    response = await client.post(
        "/api/v1/jobs/ai/999999/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("job_status", ["queued", "done", "failed"])
async def test_requeue_ai_job_rejects_non_running_status(
    client: AsyncClient,
    db_session: AsyncSession,
    job_status: str,
):
    admin_id, token = await _register_user_with_id(client, f"requeueai409{job_status}")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    conversation = Conversation(user_id=admin_id, status="active")
    db_session.add(conversation)
    await db_session.flush()
    job = AIJob(
        conversation_id=conversation.id,
        status=job_status,
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/ai/{job.id}/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert job_status in response.json()["detail"]


@pytest.mark.asyncio
async def test_requeue_ai_job_rejects_when_attempts_exhausted(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueaiexhausted")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    conversation = Conversation(user_id=admin_id, status="ai_processing")
    db_session.add(conversation)
    await db_session.flush()
    job = AIJob(
        conversation_id=conversation.id,
        status="running",
        attempts=3,
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

    assert response.status_code == 409
    assert "exhausted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_regular_user_cannot_requeue_knowledge_embedding_job(
    client: AsyncClient,
):
    _, user_token = await _register_user_with_id(client, "requeuekeregular")

    response = await client.post(
        "/api/v1/jobs/knowledge-embeddings/1/requeue",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_requeue_unknown_knowledge_embedding_job_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueke404")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    response = await client.post(
        "/api/v1/jobs/knowledge-embeddings/999999/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("job_status", ["queued", "done", "failed"])
async def test_requeue_knowledge_embedding_job_rejects_non_running_status(
    client: AsyncClient,
    db_session: AsyncSession,
    job_status: str,
):
    admin_id, token = await _register_user_with_id(
        client, f"requeueke409{job_status}"
    )
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status=job_status,
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/jobs/knowledge-embeddings/{job.id}/requeue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert job_status in response.json()["detail"]


@pytest.mark.asyncio
async def test_requeue_knowledge_embedding_job_rejects_when_attempts_exhausted(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeuekeexhausted")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status="running",
        attempts=3,
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

    assert response.status_code == 409
    assert "exhausted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_requeue_ai_job_marks_is_stale_for_old_lock(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "requeueaistale")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"
    conversation = Conversation(user_id=admin_id, status="ai_processing")
    db_session.add(conversation)
    await db_session.flush()
    # Свежий lock — is_stale должен быть False для running-задачи.
    fresh_job = AIJob(
        conversation_id=conversation.id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    # Старый lock (20 минут назад) — is_stale должен быть True.
    other = Conversation(user_id=admin_id, status="ai_processing")
    db_session.add(other)
    await db_session.flush()
    stale_job = AIJob(
        conversation_id=other.id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        started_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    db_session.add_all([fresh_job, stale_job])
    await db_session.flush()

    response = await client.get(
        "/api/v1/jobs/?kind=ai&status=running",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    by_id = {item["id"]: item for item in data["ai"]}
    assert by_id[fresh_job.id]["is_stale"] is False
    assert by_id[stale_job.id]["is_stale"] is True


@pytest.mark.asyncio
async def test_list_jobs_marks_stale_knowledge_embedding_job(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_id, token = await _register_user_with_id(client, "knowledgejobstale")
    admin = await db_session.get(User, admin_id)
    assert admin is not None
    admin.role = "admin"

    fresh_job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    stale_job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status="running",
        attempts=1,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        started_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    queued_old_lock_job = KnowledgeEmbeddingJob(
        article_id=None,
        requested_by_user_id=admin_id,
        status="queued",
        attempts=0,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    db_session.add_all([fresh_job, stale_job, queued_old_lock_job])
    await db_session.flush()

    response = await client.get(
        "/api/v1/jobs/?kind=knowledge_embeddings&status=all",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    by_id = {item["id"]: item for item in data["knowledge_embeddings"]}
    assert by_id[fresh_job.id]["is_stale"] is False
    assert by_id[stale_job.id]["is_stale"] is True
    assert by_id[queued_old_lock_job.id]["is_stale"] is False
