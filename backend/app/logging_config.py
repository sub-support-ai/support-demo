"""
Настройка логирования для всего приложения.

Что здесь происходит:
- В development (локальная разработка) — логи читаемые, цветные, в консоль
- В production — логи в формате JSON (structured logs), удобны для поиска
  в любой системе мониторинга (Grafana, Datadog, CloudWatch и т.д.)

Пример JSON-лога:
{
  "timestamp": "2026-03-20T10:00:00Z",
  "level": "ERROR",
  "logger": "app.routers.users",
  "message": "User not found",
  "user_id": 42,
  "request_id": "abc-123"
}
"""

import logging
import sys
from app.config import get_settings

settings = get_settings()


class RequestIdFilter(logging.Filter):
    """Добавляет request_id из contextvars в каждую запись лога.

    Работает как Filter (не Formatter) — совместим с любым форматтером:
    JSONFormatter в production и plain-text в development.

    При вызове вне HTTP-запроса (воркеры, startup) request_id = "".
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Отложенный импорт: logging_config загружается раньше app.context
        # на первом старте. Deferred import безопасен — модуль уже в sys.modules
        # к моменту первого лог-вызова из реального запроса.
        from app.context import request_id_ctx
        record.request_id = request_id_ctx.get()
        return True


class JSONFormatter(logging.Formatter):
    """Форматирует лог-запись в одну строку JSON."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.formatMessage(record),
        }

        # Добавляем информацию об ошибке если есть
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Добавляем любые extra-поля которые передали в логгер
        # Например: logger.info("msg", extra={"user_id": 1, "ticket_id": 5})
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "module", "msecs", "message", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName", "taskName",
            ):
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging() -> None:
    """
    Вызывается один раз при старте приложения (в main.py).
    Настраивает формат логов для всего приложения.
    """
    handler = logging.StreamHandler(sys.stdout)

    # RequestIdFilter добавляется ДО форматтера — так request_id попадает
    # и в JSON-поля, и в plain-text формат, без изменения форматтеров.
    handler.addFilter(RequestIdFilter())

    if settings.APP_ENV == "production":
        handler.setFormatter(JSONFormatter())
        log_level = logging.INFO
    else:
        # В development — читаемый формат с rid= для удобной фильтрации логов
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | rid=%(request_id)s — %(message)s",
            datefmt="%H:%M:%S",
        ))
        log_level = logging.DEBUG

    # Применяем к корневому логгеру — все дочерние логгеры наследуют настройки
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]

    # Приглушаем слишком болтливые библиотеки
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
