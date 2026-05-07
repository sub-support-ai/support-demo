from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.conversation import Conversation
from app.services.conversation_ai import generate_ai_message

AI_JOB_QUEUED = "queued"
AI_JOB_RUNNING = "running"
AI_JOB_DONE = "done"
AI_JOB_FAILED = "failed"
ACTIVE_AI_JOB_STATUSES = (AI_JOB_QUEUED, AI_JOB_RUNNING)


async def enqueue_ai_response_job(
    db: AsyncSession,
    conversation_id: int,
) -> AIJob:
    existing = await db.execute(
        select(AIJob)
        .where(
            AIJob.conversation_id == conversation_id,
            AIJob.status.in_(ACTIVE_AI_JOB_STATUSES),
        )
        .order_by(AIJob.id.desc())
        .limit(1)
    )
    job = existing.scalar_one_or_none()
    if job is not None:
        return job

    job = AIJob(
        conversation_id=conversation_id,
        status=AI_JOB_QUEUED,
        attempts=0,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def claim_next_ai_job(db: AsyncSession) -> AIJob | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AIJob)
        .where(
            AIJob.status == AI_JOB_QUEUED,
            AIJob.run_after <= now,
        )
        .order_by(AIJob.run_after.asc(), AIJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = AI_JOB_RUNNING
    job.attempts += 1
    job.locked_at = now
    job.started_at = now
    job.error = None
    await db.flush()
    await db.refresh(job)
    return job


async def requeue_stale_ai_jobs(
    db: AsyncSession,
    stale_after_seconds: int,
    limit: int = 50,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        select(AIJob)
        .where(
            AIJob.status == AI_JOB_RUNNING,
            AIJob.locked_at.is_not(None),
            AIJob.locked_at < cutoff,
        )
        .order_by(AIJob.locked_at.asc(), AIJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    jobs = result.scalars().all()
    for job in jobs:
        if job.attempts < job.max_attempts:
            job.status = AI_JOB_QUEUED
            job.run_after = datetime.now(timezone.utc)
            job.locked_at = None
            job.started_at = None
            job.error = "Job was requeued after stale running lock"
        else:
            job.status = AI_JOB_FAILED
            job.finished_at = datetime.now(timezone.utc)
            job.error = "Job failed after stale running lock"
            conversation = await db.get(Conversation, job.conversation_id)
            if conversation is not None and conversation.status == "ai_processing":
                conversation.status = "active"
    await db.flush()
    return len(jobs)


async def process_ai_job(db: AsyncSession, job: AIJob) -> None:
    try:
        await generate_ai_message(db, job.conversation_id)
    except Exception as exc:
        await fail_ai_job(db, job, exc)
        return

    now = datetime.now(timezone.utc)
    job.status = AI_JOB_DONE
    job.finished_at = now
    job.error = None
    await db.flush()


async def fail_ai_job(db: AsyncSession, job: AIJob, exc: Exception) -> None:
    now = datetime.now(timezone.utc)
    job.error = str(exc)[:2000]
    if job.attempts < job.max_attempts:
        job.status = AI_JOB_QUEUED
        job.run_after = now + timedelta(seconds=min(60, 2 ** job.attempts * 5))
    else:
        job.status = AI_JOB_FAILED
        job.finished_at = now
        conversation = await db.get(Conversation, job.conversation_id)
        if conversation is not None and conversation.status == "ai_processing":
            conversation.status = "active"
    await db.flush()
