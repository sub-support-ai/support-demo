from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_article import KnowledgeArticle, KnowledgeChunk
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.services.knowledge_base import sync_knowledge_article_index
from app.services.knowledge_embeddings import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    embed_texts,
    mark_chunk_embedded,
    needs_embedding,
    vector_literal,
)

KNOWLEDGE_EMBEDDING_JOB_QUEUED = "queued"
KNOWLEDGE_EMBEDDING_JOB_RUNNING = "running"
KNOWLEDGE_EMBEDDING_JOB_DONE = "done"
KNOWLEDGE_EMBEDDING_JOB_FAILED = "failed"
ACTIVE_KNOWLEDGE_EMBEDDING_JOB_STATUSES = (
    KNOWLEDGE_EMBEDDING_JOB_QUEUED,
    KNOWLEDGE_EMBEDDING_JOB_RUNNING,
)


async def enqueue_knowledge_embedding_job(
    db: AsyncSession,
    article_id: int | None,
    requested_by_user_id: int | None,
) -> KnowledgeEmbeddingJob:
    statement = select(KnowledgeEmbeddingJob).where(
        KnowledgeEmbeddingJob.status.in_(ACTIVE_KNOWLEDGE_EMBEDDING_JOB_STATUSES)
    )
    if article_id is None:
        statement = statement.where(KnowledgeEmbeddingJob.article_id.is_(None))
    else:
        statement = statement.where(KnowledgeEmbeddingJob.article_id == article_id)

    result = await db.execute(statement.order_by(KnowledgeEmbeddingJob.id.desc()).limit(1))
    job = result.scalar_one_or_none()
    if job is not None:
        return job

    job = KnowledgeEmbeddingJob(
        article_id=article_id,
        requested_by_user_id=requested_by_user_id,
        status=KNOWLEDGE_EMBEDDING_JOB_QUEUED,
        attempts=0,
        max_attempts=3,
        run_after=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def claim_next_knowledge_embedding_job(db: AsyncSession) -> KnowledgeEmbeddingJob | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(KnowledgeEmbeddingJob)
        .where(
            KnowledgeEmbeddingJob.status == KNOWLEDGE_EMBEDDING_JOB_QUEUED,
            KnowledgeEmbeddingJob.run_after <= now,
        )
        .order_by(KnowledgeEmbeddingJob.run_after.asc(), KnowledgeEmbeddingJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = KNOWLEDGE_EMBEDDING_JOB_RUNNING
    job.attempts += 1
    job.locked_at = now
    job.started_at = now
    job.error = None
    await db.flush()
    await db.refresh(job)
    return job


async def requeue_stale_knowledge_embedding_jobs(
    db: AsyncSession,
    stale_after_seconds: int,
    limit: int = 50,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        select(KnowledgeEmbeddingJob)
        .where(
            KnowledgeEmbeddingJob.status == KNOWLEDGE_EMBEDDING_JOB_RUNNING,
            KnowledgeEmbeddingJob.locked_at.is_not(None),
            KnowledgeEmbeddingJob.locked_at < cutoff,
        )
        .order_by(KnowledgeEmbeddingJob.locked_at.asc(), KnowledgeEmbeddingJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    jobs = result.scalars().all()
    for job in jobs:
        if job.attempts < job.max_attempts:
            job.status = KNOWLEDGE_EMBEDDING_JOB_QUEUED
            job.run_after = datetime.now(timezone.utc)
            job.locked_at = None
            job.started_at = None
            job.error = "Job was requeued after stale running lock"
        else:
            job.status = KNOWLEDGE_EMBEDDING_JOB_FAILED
            job.finished_at = datetime.now(timezone.utc)
            job.error = "Job failed after stale running lock"
    await db.flush()
    return len(jobs)


async def _pgvector_available(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return False
    result = await db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'knowledge_chunks'
                  AND column_name = 'embedding'
            )
            """
        )
    )
    return bool(result.scalar_one())


async def _chunk_ids_missing_embeddings(
    db: AsyncSession,
    article_id: int | None,
    embedding_model: str | None,
    limit: int,
    has_pgvector: bool,
) -> list[int]:
    article_filter = ""
    params: dict[str, object] = {"limit": limit}
    if article_id is not None:
        article_filter = "AND article_id = :article_id"
        params["article_id"] = article_id

    if has_pgvector:
        model_filter = (
            "OR embedding_model != :embedding_model"
            if embedding_model
            else ""
        )
        if embedding_model:
            params["embedding_model"] = embedding_model
        result = await db.execute(
            text(
                f"""
                SELECT id
                FROM knowledge_chunks
                WHERE is_active IS TRUE
                  {article_filter}
                  AND (
                    embedding IS NULL
                    OR embedding_model IS NULL
                    {model_filter}
                    OR embedding_updated_at IS NULL
                  )
                ORDER BY id ASC
                LIMIT :limit
                """
            ),
            params,
        )
        return [int(row[0]) for row in result.all()]

    statement = select(KnowledgeChunk.id).where(KnowledgeChunk.is_active.is_(True))
    if article_id is not None:
        statement = statement.where(KnowledgeChunk.article_id == article_id)
    if embedding_model:
        statement = statement.where(
            (KnowledgeChunk.embedding_model.is_(None))
            | (KnowledgeChunk.embedding_model != embedding_model)
            | (KnowledgeChunk.embedding_updated_at.is_(None))
        )
    else:
        statement = statement.where(
            (KnowledgeChunk.embedding_model.is_(None))
            | (KnowledgeChunk.embedding_updated_at.is_(None))
        )
    result = await db.execute(statement.order_by(KnowledgeChunk.id.asc()).limit(limit))
    return [int(chunk_id) for chunk_id in result.scalars().all()]


async def _load_chunks_by_id(db: AsyncSession, chunk_ids: list[int]) -> list[KnowledgeChunk]:
    if not chunk_ids:
        return []
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.id.in_(chunk_ids))
        .order_by(KnowledgeChunk.id.asc())
    )
    return result.scalars().all()


async def embed_pending_knowledge_chunks(
    db: AsyncSession,
    article_id: int | None = None,
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    max_batches: int | None = 1,
) -> tuple[int, str | None]:
    updated = 0
    embedding_model: str | None = None
    has_pgvector = await _pgvector_available(db)

    batch_number = 0
    while max_batches is None or batch_number < max_batches:
        chunk_ids = await _chunk_ids_missing_embeddings(
            db,
            article_id=article_id,
            embedding_model=embedding_model,
            limit=batch_size,
            has_pgvector=has_pgvector,
        )
        chunks = await _load_chunks_by_id(db, chunk_ids)
        if not chunks:
            break

        batch = await embed_texts([chunk.content for chunk in chunks])
        embedding_model = batch.model
        for chunk, embedding in zip(chunks, batch.embeddings, strict=True):
            if not has_pgvector and not needs_embedding(chunk, embedding_model):
                continue
            mark_chunk_embedded(chunk, embedding_model)
            if has_pgvector:
                await db.execute(
                    text(
                        """
                        UPDATE knowledge_chunks
                        SET embedding = CAST(:embedding AS vector)
                        WHERE id = :chunk_id
                        """
                    ),
                    {
                        "chunk_id": chunk.id,
                        "embedding": vector_literal(embedding),
                    },
                )
            updated += 1

        await db.flush()
        batch_number += 1

    return updated, embedding_model


async def process_knowledge_embedding_job(
    db: AsyncSession,
    job: KnowledgeEmbeddingJob,
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
) -> None:
    try:
        if job.article_id is not None:
            article = await db.get(KnowledgeArticle, job.article_id)
            if article is None:
                raise ValueError("Knowledge article not found")
            await sync_knowledge_article_index(db, article)
            await db.flush()

        updated, model = await embed_pending_knowledge_chunks(
            db,
            article_id=job.article_id,
            batch_size=batch_size,
            max_batches=None,
        )
    except Exception as exc:
        await fail_knowledge_embedding_job(db, job, exc)
        return

    now = datetime.now(timezone.utc)
    job.status = KNOWLEDGE_EMBEDDING_JOB_DONE
    job.finished_at = now
    job.updated_chunks = updated
    job.embedding_model = model
    job.error = None
    await db.flush()


async def fail_knowledge_embedding_job(
    db: AsyncSession,
    job: KnowledgeEmbeddingJob,
    exc: Exception,
) -> None:
    now = datetime.now(timezone.utc)
    job.error = str(exc)[:2000]
    if job.attempts < job.max_attempts:
        job.status = KNOWLEDGE_EMBEDDING_JOB_QUEUED
        job.run_after = now + timedelta(seconds=min(60, 2**job.attempts * 5))
    else:
        job.status = KNOWLEDGE_EMBEDDING_JOB_FAILED
        job.finished_at = now
    await db.flush()
