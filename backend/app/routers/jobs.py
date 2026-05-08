import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

JOB_STATUSES = ("queued", "running", "done", "failed")
JOB_KINDS = ("all", "ai", "knowledge_embeddings")


def _is_running_stale(
    locked_at: datetime | None,
    job_status: str,
    stale_after_seconds: int,
) -> bool:
    if job_status != AI_JOB_RUNNING or locked_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    locked = locked_at if locked_at.tzinfo else locked_at.replace(tzinfo=timezone.utc)
    return locked < cutoff


def _ai_job_to_read(job: AIJob, stale_seconds: int) -> AIJobRead:
    read = AIJobRead.model_validate(job)
    read.is_stale = _is_running_stale(job.locked_at, job.status, stale_seconds)
    return read


def _knowledge_job_to_read(
    job: KnowledgeEmbeddingJob,
    stale_seconds: int,
) -> KnowledgeEmbeddingJobRead:
    read = KnowledgeEmbeddingJobRead.model_validate(job)
    read.is_stale = _is_running_stale(job.locked_at, job.status, stale_seconds)
    return read


def _ai_jobs_to_read(jobs: Iterable[AIJob], stale_seconds: int) -> list[AIJobRead]:
    return [_ai_job_to_read(job, stale_seconds) for job in jobs]


def _knowledge_jobs_to_read(
    jobs: Iterable[KnowledgeEmbeddingJob],
    stale_seconds: int,
) -> list[KnowledgeEmbeddingJobRead]:
    return [_knowledge_job_to_read(job, stale_seconds) for job in jobs]


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

    settings = get_settings()
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

    return JobsResponse(
        ai=_ai_jobs_to_read(ai_jobs, settings.AI_WORKER_STALE_RUNNING_SECONDS),
        knowledge_embeddings=_knowledge_jobs_to_read(
            knowledge_jobs,
            settings.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS,
        ),
    )


@router.get("/failed", response_model=FailedJobsResponse)
async def list_failed_jobs(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    del admin
    settings = get_settings()
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
    return FailedJobsResponse(
        ai=_ai_jobs_to_read(ai_jobs, settings.AI_WORKER_STALE_RUNNING_SECONDS),
        knowledge_embeddings=_knowledge_jobs_to_read(
            knowledge_jobs,
            settings.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS,
        ),
    )


async def _lock_ai_job(db: AsyncSession, job_id: int) -> AIJob | None:
    # SELECT ... FOR UPDATE: блокируем строку, чтобы воркер
    # (requeue_stale_ai_jobs) или другой админ не успели изменить
    # статус между нашим чтением и записью. Без этого возможен
    # lost-update: воркер уже перевёл задачу в failed, а ручной
    # requeue её "воскрешает" обратно в queued.
    result = await db.execute(
        select(AIJob).where(AIJob.id == job_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def _lock_knowledge_embedding_job(
    db: AsyncSession, job_id: int
) -> KnowledgeEmbeddingJob | None:
    result = await db.execute(
        select(KnowledgeEmbeddingJob)
        .where(KnowledgeEmbeddingJob.id == job_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


@router.post("/ai/{job_id}/retry", response_model=AIJobRead)
async def retry_ai_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await _lock_ai_job(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI job not found",
        )
    if job.status != AI_JOB_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only failed AI jobs can be retried (current status: {job.status})",
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
    settings = get_settings()
    return _ai_job_to_read(job, settings.AI_WORKER_STALE_RUNNING_SECONDS)


@router.post("/ai/{job_id}/requeue", response_model=AIJobRead)
async def requeue_ai_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await _lock_ai_job(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI job not found",
        )
    if job.status != AI_JOB_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only running AI jobs can be requeued (current status: {job.status})",
        )
    # Ручной requeue не сбрасывает attempts — так задача не "забывает"
    # сколько раз она уже падала. Если attempts уже на потолке, отказываем
    # явно: иначе оператор крутит кнопку, и задача всё равно после первого
    # же claim'а уйдёт в failed (claim_next инкрементит attempts). Лучше
    # сразу вернуть 409 и подсказать, что нужен retry, а не requeue.
    if job.attempts >= job.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI job has exhausted retry budget "
                f"({job.attempts}/{job.max_attempts}); use retry after fail."
            ),
        )

    _requeue_running_ai_job(job)
    conversation = await db.get(Conversation, job.conversation_id)
    if conversation is not None and conversation.status == "active":
        # Conversation мог сброситься в active, пока задача висела running.
        # Возвращаем в ai_processing, чтобы worker не процессил "осиротевшую"
        # задачу при неконсистентном состоянии диалога.
        conversation.status = "ai_processing"

    await log_event(
        db,
        action="job.requeue",
        user_id=admin.id,
        target_type="ai_job",
        target_id=job.id,
        request=request,
        details={
            "conversation_id": job.conversation_id,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
        },
    )
    # Ручной requeue — сигнал, что что-то идёт не так у воркера/внешних
    # сервисов. Лог уровня warning попадает и в Sentry (если включён),
    # чтобы пик ручных вмешательств был виден без чтения audit_log.
    logger.warning(
        "Manual requeue of AI job",
        extra={
            "job_id": job.id,
            "conversation_id": job.conversation_id,
            "attempts": job.attempts,
            "admin_id": admin.id,
        },
    )
    await db.flush()
    await db.refresh(job)
    settings = get_settings()
    return _ai_job_to_read(job, settings.AI_WORKER_STALE_RUNNING_SECONDS)


@router.post("/knowledge-embeddings/{job_id}/retry", response_model=KnowledgeEmbeddingJobRead)
async def retry_knowledge_embedding_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    job = await _lock_knowledge_embedding_job(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge embedding job not found",
        )
    if job.status != KNOWLEDGE_EMBEDDING_JOB_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only failed knowledge embedding jobs can be retried "
                f"(current status: {job.status})"
            ),
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
    settings = get_settings()
    return _knowledge_job_to_read(
        job,
        settings.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS,
    )


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
    job = await _lock_knowledge_embedding_job(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge embedding job not found",
        )
    if job.status != KNOWLEDGE_EMBEDDING_JOB_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only running knowledge embedding jobs can be requeued "
                f"(current status: {job.status})"
            ),
        )
    if job.attempts >= job.max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Knowledge embedding job has exhausted retry budget "
                f"({job.attempts}/{job.max_attempts}); use retry after fail."
            ),
        )

    _requeue_running_knowledge_embedding_job(job)
    await log_event(
        db,
        action="job.requeue",
        user_id=admin.id,
        target_type="knowledge_embedding_job",
        target_id=job.id,
        request=request,
        details={
            "article_id": job.article_id,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
        },
    )
    logger.warning(
        "Manual requeue of knowledge embedding job",
        extra={
            "job_id": job.id,
            "article_id": job.article_id,
            "attempts": job.attempts,
            "admin_id": admin.id,
        },
    )
    await db.flush()
    await db.refresh(job)
    settings = get_settings()
    return _knowledge_job_to_read(
        job,
        settings.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS,
    )


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
    job.status = AI_JOB_QUEUED
    job.run_after = datetime.now(timezone.utc)
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
    job.status = KNOWLEDGE_EMBEDDING_JOB_QUEUED
    job.run_after = datetime.now(timezone.utc)
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.error = "Job was manually returned to queue"
