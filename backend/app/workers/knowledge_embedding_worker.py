import asyncio
import logging
import os

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.metrics import record_job_duration
from app.services.knowledge_embedding_jobs import (
    claim_next_knowledge_embedding_job,
    enqueue_knowledge_embedding_job,
    fail_knowledge_embedding_job,
    process_knowledge_embedding_job,
    requeue_stale_knowledge_embedding_jobs,
)
from app.services.knowledge_embeddings import DEFAULT_EMBEDDING_BATCH_SIZE
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)

JOB_TIMEOUT_SECONDS = float(os.getenv("KNOWLEDGE_EMBEDDING_WORKER_JOB_TIMEOUT_SECONDS", "300"))
REINDEX_INTERVAL_SECONDS = int(os.getenv("KNOWLEDGE_REINDEX_INTERVAL_SECONDS", "0"))
EMBEDDING_BATCH_SIZE = int(
    os.getenv("KNOWLEDGE_EMBEDDING_BATCH_SIZE", str(DEFAULT_EMBEDDING_BATCH_SIZE))
)


class JobTimeoutError(TimeoutError):
    pass


class KnowledgeEmbeddingWorker(BaseWorker):
    NOTIFY_CHANNEL = "knowledge_embedding_jobs"
    NOTIFY_TIMEOUT_SECONDS = float(
        os.getenv("KNOWLEDGE_EMBEDDING_WORKER_NOTIFY_TIMEOUT_SECONDS", "2.0")
    )
    WORKER_NAME = "Knowledge embedding worker"

    def __init__(self) -> None:
        super().__init__()
        self._last_reindex_at: float = 0.0

    async def run_once(self) -> bool:
        settings = get_settings()

        # Периодический полный переиндекс (если включён через env).
        if REINDEX_INTERVAL_SECONDS > 0:
            now = asyncio.get_running_loop().time()
            if now - self._last_reindex_at >= REINDEX_INTERVAL_SECONDS:
                await enqueue_periodic_reindex()
                self._last_reindex_at = now

        async with AsyncSessionLocal() as db:
            await requeue_stale_knowledge_embedding_jobs(
                db,
                settings.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS,
            )
            job = await claim_next_knowledge_embedding_job(db)
            if job is None:
                await db.commit()
                return False
            try:
                with record_job_duration("knowledge_embedding"):
                    await asyncio.wait_for(
                        process_knowledge_embedding_job(
                            db,
                            job,
                            batch_size=EMBEDDING_BATCH_SIZE,
                        ),
                        timeout=JOB_TIMEOUT_SECONDS,
                    )
            except asyncio.TimeoutError:
                await fail_knowledge_embedding_job(
                    db,
                    job,
                    JobTimeoutError(
                        f"Knowledge embedding job exceeded {JOB_TIMEOUT_SECONDS:.0f}s timeout"
                    ),
                )
            await db.commit()
        return True


async def enqueue_periodic_reindex() -> None:
    async with AsyncSessionLocal() as db:
        await enqueue_knowledge_embedding_job(
            db,
            article_id=None,
            requested_by_user_id=None,
        )
        await db.commit()


# ── Обратная совместимость ────────────────────────────────────────────────────

_worker = KnowledgeEmbeddingWorker()


async def run_once() -> bool:
    return await _worker.run_once()


async def run_forever() -> None:
    await _worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
