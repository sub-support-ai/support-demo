from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.ai_job import AIJob
from app.models.conversation import Conversation
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.user import User
from app.schemas.job import (
    AIJobRead,
    FailedJobsResponse,
    JobsResponse,
    KnowledgeEmbeddingJobRead,
)
from app.services.ai_jobs import (
    ACTIVE_AI_JOB_STATUSES,
    AI_JOB_FAILED,
    AI_JOB_QUEUED,
    AI_JOB_RUNNING,
)
from app.services.audit import log_event
from app.services.knowledge_embedding_jobs import (
    ACTIVE_KNOWLEDGE_EMBEDDING_JOB_STATUSES,
    KNOWLEDGE_EMBEDDING_JOB_FAILED,
    KNOWLEDGE_EMBEDDING_JOB_QUEUED,
    KNOWLEDGE_EMBEDDING_JOB_RUNNING,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

JOB_STATUSES = ("queued", "running", "done", "failed")
JOB_KINDS = ("all", "ai", "knowledge_embeddings")


@router.get("/", response_model=JobsResponse)
async def list_jobs(
    kind: str = Query(default="all"),
    status_filter: str = Query(default="all", alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    del admin
    if kind not in JOB_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid job kind",
        )
    if status_filter != "all" and status_filter not in JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid job status",
        )

    ai_jobs: list[AIJob] = []
    knowledge_jobs: list[KnowledgeEmbeddingJob] = []
    if kind in {"all", "ai"}:
        ai_query = select(AIJob).order_by(AIJob.id.desc()).limit(limit)
        if status_filter != "all":
            ai_query = (
                select(AIJob)
                .where(AIJob.status == status_filter)
                .order_by(AIJob.id.desc())
                .limit(limit)
            )
        ai_jobs = (await db.execute(ai_query)).scalars().all()

    if kind in {"all", "knowledge_embeddings"}:
        knowledge_query = (
            select(KnowledgeEmbeddingJob)
            .order_by(KnowledgeEmbeddingJob.id.desc())
            .limit(limit)
        )
        if status_filter != "all":
            knowledge_query = (
                select(KnowledgeEmbeddingJob)
                .where(KnowledgeEmbeddingJob.status == status_filter)
                .order_by(KnowledgeEmbeddingJob.id.desc())
                .limit(limit)
            )
        knowledge_jobs = (await db.execute(knowledge_query)).scalars().all()

    return JobsResponse(ai=ai_jobs, knowledge_embeddings=knowledge_jobs)


@router.get("/failed", response_model=FailedJobsResponse)
async def list_failed_jobs(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    del admin
    ai_jobs = (
        await db.execute(
            select(AIJob)
            .where(AIJob.status == AI_JOB_FAILED)
            .order_by(AIJob.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    knowledge_jobs = (
        await db.execute(
            select(KnowledgeEmbeddingJob)
            .where(KnowledgeEmbeddingJob.status == KNOWLEDGE_EMBEDDING_JOB_FAILED)
            .order_by(KnowledgeEmbeddingJob.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return FailedJobsResponse(ai=ai_jobs, knowledge_embeddings=knowledge_jobs)


@router.post("/ai/{job_id}/retry", response_model=AIJobRead)
async def retry_ai_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await db.get(AIJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI job not found",
        )
    if job.status != AI_JOB_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed AI jobs can be retried",
        )

    active_job = (
        await db.execute(
            select(AIJob)
            .where(
                AIJob.id != job.id,
                AIJob.conversation_id == job.conversation_id,
                AIJob.status.in_(ACTIVE_AI_JOB_STATUSES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation already has an active AI job",
        )

    _reset_ai_job(job)
    conversation = await db.get(Conversation, job.conversation_id)
    if conversation is not None and conversation.status == "active":
        conversation.status = "ai_processing"

    await log_event(
        db,
        action="job.retry",
        user_id=admin.id,
        target_type="ai_job",
        target_id=job.id,
        request=request,
        details={"conversation_id": job.conversation_id},
    )
    await db.flush()
    await db.refresh(job)
    return job


@router.post("/ai/{job_id}/requeue", response_model=AIJobRead)
async def requeue_ai_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await db.get(AIJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI job not found",
        )
    if job.status != AI_JOB_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only running AI jobs can be requeued",
        )

    _requeue_running_ai_job(job)
    await log_event(
        db,
        action="job.requeue",
        user_id=admin.id,
        target_type="ai_job",
        target_id=job.id,
        request=request,
        details={"conversation_id": job.conversation_id},
    )
    await db.flush()
    await db.refresh(job)
    return job


@router.post("/knowledge-embeddings/{job_id}/retry", response_model=KnowledgeEmbeddingJobRead)
async def retry_knowledge_embedding_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await db.get(KnowledgeEmbeddingJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge embedding job not found",
        )
    if job.status != KNOWLEDGE_EMBEDDING_JOB_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed knowledge embedding jobs can be retried",
        )

    statement = select(KnowledgeEmbeddingJob).where(
        KnowledgeEmbeddingJob.id != job.id,
        KnowledgeEmbeddingJob.status.in_(ACTIVE_KNOWLEDGE_EMBEDDING_JOB_STATUSES),
    )
    if job.article_id is None:
        statement = statement.where(KnowledgeEmbeddingJob.article_id.is_(None))
    else:
        statement = statement.where(KnowledgeEmbeddingJob.article_id == job.article_id)
    active_job = (await db.execute(statement.limit(1))).scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge article already has an active embedding job",
        )

    _reset_knowledge_embedding_job(job)
    await log_event(
        db,
        action="job.retry",
        user_id=admin.id,
        target_type="knowledge_embedding_job",
        target_id=job.id,
        request=request,
        details={"article_id": job.article_id},
    )
    await db.flush()
    await db.refresh(job)
    return job


@router.post(
    "/knowledge-embeddings/{job_id}/requeue",
    response_model=KnowledgeEmbeddingJobRead,
)
async def requeue_knowledge_embedding_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await db.get(KnowledgeEmbeddingJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge embedding job not found",
        )
    if job.status != KNOWLEDGE_EMBEDDING_JOB_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only running knowledge embedding jobs can be requeued",
        )

    _requeue_running_knowledge_embedding_job(job)
    await log_event(
        db,
        action="job.requeue",
        user_id=admin.id,
        target_type="knowledge_embedding_job",
        target_id=job.id,
        request=request,
        details={"article_id": job.article_id},
    )
    await db.flush()
    await db.refresh(job)
    return job


def _reset_ai_job(job: AIJob) -> None:
    now = datetime.now(timezone.utc)
    job.status = AI_JOB_QUEUED
    job.attempts = 0
    job.run_after = now
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.error = None


def _requeue_running_ai_job(job: AIJob) -> None:
    now = datetime.now(timezone.utc)
    job.status = AI_JOB_QUEUED
    job.run_after = now
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.error = "Job was manually returned to queue"


def _reset_knowledge_embedding_job(job: KnowledgeEmbeddingJob) -> None:
    now = datetime.now(timezone.utc)
    job.status = KNOWLEDGE_EMBEDDING_JOB_QUEUED
    job.attempts = 0
    job.run_after = now
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.error = None


def _requeue_running_knowledge_embedding_job(job: KnowledgeEmbeddingJob) -> None:
    now = datetime.now(timezone.utc)
    job.status = KNOWLEDGE_EMBEDDING_JOB_QUEUED
    job.run_after = now
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.error = "Job was manually returned to queue"
