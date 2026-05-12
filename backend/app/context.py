"""
Request-scoped context variables.

Позволяет любому коду внутри запроса прочитать request_id без явной
передачи через параметры. Middleware устанавливает значение перед вызовом
обработчика; logging-фильтр читает его и добавляет в каждую строку лога.

Пример чтения request_id из любого сервиса:

    from app.context import request_id_ctx
    rid = request_id_ctx.get()   # "" — если вызвано вне контекста запроса
"""

from contextvars import ContextVar

# Значение по умолчанию — пустая строка, чтобы логи воркеров и стартап-кода
# не падали с KeyError при форматировании rid=%(request_id)s.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
