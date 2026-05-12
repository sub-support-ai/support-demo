"""
Prometheus-метрики: HTTP-инструментация + бизнесовые gauges/histograms.

Что тут есть:
  • HTTP-метрики (request_total, latency) — автоматически через
    prometheus-fastapi-instrumentator. Подключается в lifespan.
  • Бизнес-метрики:
      support_ai_jobs_queued_total      — глубина очереди ai_jobs
      support_embedding_jobs_queued_total — глубина очереди embedding
      support_worker_job_duration_seconds — гистограмма времени обработки джобы

Защита /metrics в production:
  Эндпоинт не аутентифицирован — он должен быть закрыт на уровне
  nginx/ingress (разрешить только IP Prometheus-scraper).
  В docker-compose.yml добавьте к сервису app: expose: ["8000"],
  а не ports, и проксируйте /metrics только внутри docker-сети.

Использование:

    # В lifespan (main.py):
    from app.metrics import setup_metrics
    setup_metrics(app)

    # В воркере вокруг обработки джобы:
    from app.metrics import record_job_duration
    with record_job_duration("ai"):
        await process_ai_job(db, job)

    # Обновление gauges (вызывать периодически, например из sla_worker):
    from app.metrics import refresh_queue_depth_metrics
    await refresh_queue_depth_metrics(settings.DATABASE_URL)
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

from prometheus_client import Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# ── HTTP-автоинструментация ──────────────────────────────────────────────────

instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/healthcheck", "/metrics"],
)


def setup_metrics(app: object) -> None:
    """Подключить Prometheus-инструментацию к FastAPI-приложению.

    Должна вызываться один раз в lifespan перед запуском uvicorn.
    Регистрирует /metrics endpoint (не включается в OpenAPI-схему).
    """
    instrumentator.instrument(app)  # type: ignore[arg-type]
    instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)  # type: ignore[arg-type]


# ── Бизнес-метрики ───────────────────────────────────────────────────────────

ai_jobs_queued = Gauge(
    "support_ai_jobs_queued_total",
    "Количество ai_jobs со статусом queued",
)

embedding_jobs_queued = Gauge(
    "support_embedding_jobs_queued_total",
    "Количество knowledge_embedding_jobs со статусом queued",
)

worker_job_duration = Histogram(
    "support_worker_job_duration_seconds",
    "Время обработки одной джобы воркером",
    labelnames=["worker"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)


@contextmanager
def record_job_duration(worker_name: str) -> Generator[None, None, None]:
    """Контекст-менеджер: записывает время выполнения одной джобы.

    Пример::

        with record_job_duration("ai"):
            await process_ai_job(db, job)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        worker_job_duration.labels(worker=worker_name).observe(
            time.perf_counter() - start
        )


async def refresh_queue_depth_metrics(database_url: str) -> None:
    """Обновить gauge-метрики глубины очередей.

    Вызывается из sla_worker.run_once() раз в 30 с — там уже есть периодический
    тик, экономим на отдельном поллере. Для SQLite (тесты) — no-op.
    """
    if not database_url.startswith("postgresql"):
        return

    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models.ai_job import AIJob
    from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob

    async with AsyncSessionLocal() as db:
        ai_count = await db.scalar(
            select(func.count()).where(AIJob.status == "queued")
        )
        emb_count = await db.scalar(
            select(func.count()).where(KnowledgeEmbeddingJob.status == "queued")
        )

    ai_jobs_queued.set(ai_count or 0)
    embedding_jobs_queued.set(emb_count or 0)
