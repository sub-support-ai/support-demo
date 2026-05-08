import asyncio
import logging
import os
import signal

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.knowledge_embedding_jobs import (
    claim_next_knowledge_embedding_job,
    enqueue_knowledge_embedding_job,
    fail_knowledge_embedding_job,
    process_knowledge_embedding_job,
    requeue_stale_knowledge_embedding_jobs,
)
from app.services.knowledge_embeddings import DEFAULT_EMBEDDING_BATCH_SIZE

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("KNOWLEDGE_EMBEDDING_WORKER_POLL_INTERVAL_SECONDS", "5"))
JOB_TIMEOUT_SECONDS = float(os.getenv("KNOWLEDGE_EMBEDDING_WORKER_JOB_TIMEOUT_SECONDS", "300"))
REINDEX_INTERVAL_SECONDS = int(os.getenv("KNOWLEDGE_REINDEX_INTERVAL_SECONDS", "0"))
EMBEDDING_BATCH_SIZE = int(
    os.getenv("KNOWLEDGE_EMBEDDING_BATCH_SIZE", str(DEFAULT_EMBEDDING_BATCH_SIZE))
)
_stop_event = asyncio.Event()


class JobTimeoutError(TimeoutError):
    pass


def _request_shutdown() -> None:
    logger.info("Knowledge embedding worker shutdown requested")
    _stop_event.set()


def _install_signal_handlers() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: _request_shutdown())


async def run_once() -> bool:
    settings = get_settings()
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


async def run_forever() -> None:
    _install_signal_handlers()
    last_reindex_at = 0.0
    while not _stop_event.is_set():
        try:
            if REINDEX_INTERVAL_SECONDS > 0:
                now = asyncio.get_running_loop().time()
                if now - last_reindex_at >= REINDEX_INTERVAL_SECONDS:
                    await enqueue_periodic_reindex()
                    last_reindex_at = now
            processed = await run_once()
        except Exception:
            logger.exception("Knowledge embedding worker iteration failed")
            processed = False

        if not processed:
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
