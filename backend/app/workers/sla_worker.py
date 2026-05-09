import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.services.sla_escalation import escalate_overdue_tickets

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("SLA_WORKER_POLL_INTERVAL_SECONDS", "30"))
SLA_ESCALATION_BATCH_SIZE = int(os.getenv("SLA_ESCALATION_BATCH_SIZE", "50"))

# Retention: удаляем старые записи раз в час, не при каждом тике (30 с),
# чтобы не нагружать БД мелкими DELETE-запросами.
_RETENTION_INTERVAL_SECONDS = 3600
_last_retention_run: float = 0.0


async def run_once() -> int:
    async with AsyncSessionLocal() as db:
        escalated = await escalate_overdue_tickets(
            db,
            limit=SLA_ESCALATION_BATCH_SIZE,
        )
        await db.commit()
        return escalated


async def _run_retention_once() -> None:
    """Удаляет устаревшие записи логов согласно LOG_RETENTION_DAYS.

    Затрагивает: audit_logs, ai_fallback_events, завершённые ai_jobs и
    knowledge_embedding_jobs (статус 'done' или 'failed'). Живые записи
    (queued / running) не трогаем — они нужны воркерам.

    Если LOG_RETENTION_DAYS == 0 — retention отключён, выходим сразу.
    """
    from app.config import get_settings
    retention_days = get_settings().LOG_RETENTION_DAYS
    if not retention_days:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    from app.models.audit_log import AuditLog
    from app.models.ai_fallback_event import AIFallbackEvent
    from app.models.ai_job import AIJob
    from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob

    async with AsyncSessionLocal() as db:
        # audit_logs — все старше cutoff
        r1 = await db.execute(
            delete(AuditLog).where(AuditLog.created_at < cutoff)
        )
        # ai_fallback_events — все старше cutoff
        r2 = await db.execute(
            delete(AIFallbackEvent).where(AIFallbackEvent.created_at < cutoff)
        )
        # ai_jobs — только завершённые (done/failed) старше cutoff
        r3 = await db.execute(
            delete(AIJob).where(
                AIJob.status.in_({"done", "failed"}),
                AIJob.created_at < cutoff,
            )
        )
        # knowledge_embedding_jobs — аналогично
        r4 = await db.execute(
            delete(KnowledgeEmbeddingJob).where(
                KnowledgeEmbeddingJob.status.in_({"done", "failed"}),
                KnowledgeEmbeddingJob.created_at < cutoff,
            )
        )
        await db.commit()

    deleted = (
        (r1.rowcount or 0)
        + (r2.rowcount or 0)
        + (r3.rowcount or 0)
        + (r4.rowcount or 0)
    )
    if deleted:
        logger.info(
            "Retention: удалено устаревших записей",
            extra={
                "audit_logs": r1.rowcount,
                "fallback_events": r2.rowcount,
                "ai_jobs": r3.rowcount,
                "embedding_jobs": r4.rowcount,
                "cutoff_days": retention_days,
            },
        )


async def run_forever() -> None:
    global _last_retention_run
    while True:
        try:
            escalated = await run_once()
            if escalated:
                logger.info("SLA worker escalated overdue tickets", extra={"count": escalated})
        except Exception:
            logger.exception("SLA worker iteration failed")

        # Retention — раз в час, независимо от SLA-тика
        now = asyncio.get_event_loop().time()
        if now - _last_retention_run >= _RETENTION_INTERVAL_SECONDS:
            try:
                await _run_retention_once()
            except Exception:
                logger.exception("Retention worker iteration failed")
            _last_retention_run = asyncio.get_event_loop().time()

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
