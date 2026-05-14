import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.metrics import refresh_queue_depth_metrics
from app.services.sla_escalation import escalate_overdue_tickets
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = float(os.getenv("SLA_WORKER_POLL_INTERVAL_SECONDS", "30"))
SLA_ESCALATION_BATCH_SIZE = int(os.getenv("SLA_ESCALATION_BATCH_SIZE", "50"))

# Retention: удаляем старые записи раз в час, не при каждом тике (30 с),
# чтобы не нагружать БД мелкими DELETE-запросами.
_RETENTION_INTERVAL_SECONDS = 3600


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

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    from app.models.ai_fallback_event import AIFallbackEvent
    from app.models.ai_job import AIJob
    from app.models.audit_log import AuditLog
    from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob

    async with AsyncSessionLocal() as db:
        # audit_logs — все старше cutoff
        r1 = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        # ai_fallback_events — все старше cutoff
        r2 = await db.execute(delete(AIFallbackEvent).where(AIFallbackEvent.created_at < cutoff))
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

    deleted = (r1.rowcount or 0) + (r2.rowcount or 0) + (r3.rowcount or 0) + (r4.rowcount or 0)
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


class SLAWorker(BaseWorker):
    # SLA — timer-based, не event-driven: нет очереди, которую нужно ждать.
    # NOTIFY_CHANNEL="" — BaseWorker не поднимает LISTEN-соединение.
    # NOTIFY_TIMEOUT_SECONDS = POLL_INTERVAL_SECONDS — это таймаут между тиками.
    NOTIFY_CHANNEL = ""
    NOTIFY_TIMEOUT_SECONDS = POLL_INTERVAL_SECONDS
    WORKER_NAME = "SLA worker"

    def __init__(self) -> None:
        super().__init__()
        self._last_retention_run: float = 0.0

    async def run_once(self) -> bool:
        try:
            escalated = await run_once()
            if escalated:
                logger.info("SLA worker escalated overdue tickets", extra={"count": escalated})
        except Exception:
            logger.exception("SLA worker iteration failed")

        # Retention — раз в час, независимо от SLA-тика
        now = asyncio.get_running_loop().time()
        if now - self._last_retention_run >= _RETENTION_INTERVAL_SECONDS:
            try:
                await _run_retention_once()
            except Exception:
                logger.exception("Retention worker iteration failed")
            self._last_retention_run = asyncio.get_running_loop().time()

        # Обновляем Prometheus-gauges глубины очередей: SLA-воркер уже тикает
        # каждые 30 с, используем его тик чтобы не поднимать отдельный поллер.
        from app.config import get_settings

        try:
            await refresh_queue_depth_metrics(get_settings().DATABASE_URL)
        except Exception:
            logger.exception("Metrics refresh failed")

        # Всегда возвращаем True: это говорит BaseWorker, что надо сразу же
        # подождать NOTIFY_TIMEOUT_SECONDS (= POLL_INTERVAL_SECONDS), а не
        # немедленно вызывать следующую итерацию.
        return True


_sla_worker = SLAWorker()


async def run_forever() -> None:
    await _sla_worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
