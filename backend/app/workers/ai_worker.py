import asyncio
import logging
import os

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.ai_job import AIJob
from app.services.ai_jobs import claim_next_ai_job, process_ai_job

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("AI_WORKER_POLL_INTERVAL_SECONDS", "1"))


async def run_once() -> bool:
    async with AsyncSessionLocal() as db:
        job = await claim_next_ai_job(db)
        await db.commit()

    if job is None:
        return False

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AIJob).where(AIJob.id == job.id))
        locked_job = result.scalar_one()
        await process_ai_job(db, locked_job)
        await db.commit()

    return True


async def run_forever() -> None:
    while True:
        try:
            processed = await run_once()
        except Exception:
            logger.exception("AI worker iteration failed")
            processed = False

        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
