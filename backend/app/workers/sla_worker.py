import asyncio
import logging
import os

from app.database import AsyncSessionLocal
from app.services.sla_escalation import escalate_overdue_tickets

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("SLA_WORKER_POLL_INTERVAL_SECONDS", "30"))
SLA_ESCALATION_BATCH_SIZE = int(os.getenv("SLA_ESCALATION_BATCH_SIZE", "50"))


async def run_once() -> int:
    async with AsyncSessionLocal() as db:
        escalated = await escalate_overdue_tickets(
            db,
            limit=SLA_ESCALATION_BATCH_SIZE,
        )
        await db.commit()
        return escalated


async def run_forever() -> None:
    while True:
        try:
            escalated = await run_once()
            if escalated:
                logger.info("SLA worker escalated overdue tickets", extra={"count": escalated})
        except Exception:
            logger.exception("SLA worker iteration failed")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
