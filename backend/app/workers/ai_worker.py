import asyncio
import logging
import os
import signal

from app.database import AsyncSessionLocal
from app.services.ai_jobs import claim_next_ai_job, fail_ai_job, process_ai_job, requeue_stale_ai_jobs

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("AI_WORKER_POLL_INTERVAL_SECONDS", "1"))
JOB_TIMEOUT_SECONDS = float(os.getenv("AI_WORKER_JOB_TIMEOUT_SECONDS", "240"))
STALE_RUNNING_SECONDS = int(os.getenv("AI_WORKER_STALE_RUNNING_SECONDS", "600"))
_stop_event = asyncio.Event()


class JobTimeoutError(TimeoutError):
    pass


def _request_shutdown() -> None:
    logger.info("AI worker shutdown requested")
    _stop_event.set()


def _install_signal_handlers() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: _request_shutdown())


async def run_once() -> bool:
    async with AsyncSessionLocal() as db:
        await requeue_stale_ai_jobs(db, STALE_RUNNING_SECONDS)
        job = await claim_next_ai_job(db)
        if job is None:
            await db.commit()
            return False
        try:
            await asyncio.wait_for(
                process_ai_job(db, job),
                timeout=JOB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await fail_ai_job(
                db,
                job,
                JobTimeoutError(f"AI job exceeded {JOB_TIMEOUT_SECONDS:.0f}s timeout"),
            )
        await db.commit()
    return True


async def run_forever() -> None:
    _install_signal_handlers()
    while not _stop_event.is_set():
        try:
            processed = await run_once()
        except Exception:
            logger.exception("AI worker iteration failed")
            processed = False

        if not processed:
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
