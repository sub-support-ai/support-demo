"""
Тонкая обёртка над asyncpg LISTEN/NOTIFY для wakeup-сигналов воркеров.

ЗАЧЕМ:
  ai_worker поллит БД каждые 0.2 с (5 SELECT/сек в холостую).
  С pg_notify воркер спит бесконечно и просыпается только когда
  enqueue_*_job() вставил новую джобу и послал NOTIFY.

ДИЗАЙН:
  • Отдельное asyncpg-соединение для LISTEN (не из пула SQLAlchemy).
    SQLAlchemy async не поддерживает LISTEN/NOTIFY нативно.
  • Keepalive-задача переподключается при обрыве соединения (через 5 с).
  • SQLite (тесты): все функции работают как no-op; воркер переходит
    в режим таймаутного поллинга (max_wait_seconds).

ИСПОЛЬЗОВАНИЕ:

    # Отправка уведомления после коммита джобы:
    await notify(settings.DATABASE_URL, "ai_jobs")

    # Воркер:
    async with listen_for_notifications(url, "ai_jobs", stop_event) as wake:
        while not stop_event.is_set():
            processed = await run_once()
            if not processed:
                try:
                    await asyncio.wait_for(wake.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

logger = logging.getLogger(__name__)


def _is_postgres(database_url: str) -> bool:
    return database_url.startswith("postgresql")


def _to_asyncpg_dsn(database_url: str) -> str:
    """Конвертирует SQLAlchemy URL в DSN для asyncpg.

    'postgresql+asyncpg://user:pass@host/db'  →  'postgresql://user:pass@host/db'
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def notify(database_url: str, channel: str) -> None:
    """Послать NOTIFY на канал.

    Создаёт временное соединение, отправляет NOTIFY, закрывает.
    No-op для SQLite и в случае ошибки (воркер просто дождётся таймаута).
    """
    if not _is_postgres(database_url):
        return
    try:
        import asyncpg  # type: ignore[import-untyped]

        conn = await asyncpg.connect(_to_asyncpg_dsn(database_url))
        try:
            await conn.execute(f"NOTIFY {channel}")
        finally:
            await conn.close()
    except Exception:
        # Лёгкая ошибка: воркер подхватит джобу на следующем таймауте.
        # Логировать как WARNING, не как ERROR — это не критический путь.
        logger.warning("pg_notify: не удалось отправить NOTIFY %r", channel, exc_info=True)


@asynccontextmanager
async def listen_for_notifications(
    database_url: str,
    channel: str,
    stop_event: asyncio.Event,
    max_wait_seconds: float = 2.0,
) -> AsyncGenerator[asyncio.Queue[None], None]:
    """Контекст-менеджер: возвращает Queue, в которую кладётся None при NOTIFY.

    Для SQLite или channel="" — возвращает пустую Queue, воркер работает
    в режиме таймаутного поллинга через asyncio.wait_for(wake.get(), timeout=...).

    Keepalive-задача автоматически переподключается при обрыве соединения.

    Пример:

        async with listen_for_notifications(url, "ai_jobs", stop_event, 2.0) as wake:
            while not stop_event.is_set():
                processed = await run_once()
                if not processed:
                    try:
                        await asyncio.wait_for(wake.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass
    """
    wake_queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)

    # SQLite или пустой канал → просто отдаём пустую Queue, caller использует
    # таймаут как fallback. Никакого asyncpg-соединения не нужно.
    if not _is_postgres(database_url) or not channel:
        yield wake_queue
        return

    try:
        import asyncpg  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pg_notify: asyncpg недоступен, переходим в polling-режим")
        yield wake_queue
        return

    conn: asyncpg.Connection | None = None

    def _on_notify(
        _conn: object,
        _pid: int,
        _channel_name: str,
        _payload: str,
    ) -> None:
        # Вызывается из внутренней задачи asyncpg.
        # put_nowait с maxsize=1 коалесцирует дублирующиеся уведомления:
        # если воркер ещё не проснулся, второй NOTIFY просто игнорируется.
        with suppress(asyncio.QueueFull):
            wake_queue.put_nowait(None)

    async def _connect() -> asyncpg.Connection:
        c = await asyncpg.connect(_to_asyncpg_dsn(database_url))
        c.add_listener(channel, _on_notify)
        await c.execute(f"LISTEN {channel}")
        logger.info("pg_notify: LISTEN %r установлен", channel)
        return c

    async def _keepalive() -> None:
        """Следит за живостью LISTEN-соединения и переподключается при обрыве."""
        nonlocal conn
        while not stop_event.is_set():
            try:
                if conn is None or conn.is_closed():
                    conn = await _connect()
                # Лёгкий пинг: SELECT 1 подтверждает что сокет жив.
                await conn.execute("SELECT 1")
            except Exception:
                logger.warning(
                    "pg_notify: потеряно соединение LISTEN %r, переподключение через 5 с",
                    channel,
                    exc_info=True,
                )
                if conn is not None and not conn.is_closed():
                    with suppress(Exception):
                        await conn.close()
                conn = None
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)

    conn = await _connect()
    keepalive_task = asyncio.get_running_loop().create_task(_keepalive())

    try:
        yield wake_queue
    finally:
        stop_event.set()
        keepalive_task.cancel()
        with suppress(asyncio.CancelledError):
            await keepalive_task
        if conn is not None and not conn.is_closed():
            with suppress(Exception):
                await conn.close()
