"""Запись событий в audit_log.

Конвенция: вызов log_event() — это часть ТОЙ ЖЕ транзакции, что и
основное действие. Пример:
    - DELETE /tickets/42:
        1) db.delete(ticket)
        2) await log_event(db, action="ticket.delete", ...)
        3) db.commit()  ← оба изменения попадают в БД одной транзакцией

Если шаг 3 упадёт — оба отката. Инвариант: если в audit_log есть запись
о ticket.delete, значит тикет действительно был удалён (и наоборот).
Это сильнее, чем "логируем в файл перед удалением" — там возможен
рассинхрон (залогировали, а БД упала перед commit).
"""

import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import DETAILS_MAX_LEN, AuditLog
from app.rate_limit import get_client_ip as _rate_limit_get_ip


# Маркер, который добавляется при обрезании длинного details.
# Его длина входит в DETAILS_MAX_LEN — см. _serialize_details ниже.
_TRUNCATED_SUFFIX = "...<truncated>"


def _client_ip(request: Optional[Request]) -> Optional[str]:
    """Реальный IP клиента с учётом X-Forwarded-For за прокси.

    Делегирует в rate_limit.get_client_ip, которая уже умеет читать
    TRUSTED_PROXY_COUNT и корректно парсит XFF-цепочку. За nginx
    audit_log будет показывать настоящий IP клиента, а не 127.0.0.1.

    Некоторые вызовы могут логировать без request (фоновые задачи) —
    тогда IP=None.
    """
    if request is None:
        return None
    return _rate_limit_get_ip(request)


def _serialize_details(details: Optional[dict[str, Any]]) -> Optional[str]:
    """Сериализовать details в JSON-строку, гарантированно не длиннее колонки.

    Зачем обрезаем: пользовательский ввод (например, form.username при
    login.failure) может быть произвольной длины. Если json.dumps выдал
    строку длиннее DETAILS_MAX_LEN, INSERT в audit_logs упадёт с
    StringDataRightTruncation (Postgres) или молча обрежет (SQLite) —
    атакующий через длинный username получает 500 и ломает /login
    для себя (а на Postgres — для всей таблицы в этой транзакции).

    Логика: всегда помещаемся в DETAILS_MAX_LEN. Если не влезло —
    обрезаем префикс и подклеиваем маркер _TRUNCATED_SUFFIX, чтобы
    при анализе журнала было видно "здесь было длиннее".
    """
    if details is None:
        return None
    raw = json.dumps(details, ensure_ascii=False)
    if len(raw) <= DETAILS_MAX_LEN:
        return raw
    keep = DETAILS_MAX_LEN - len(_TRUNCATED_SUFFIX)
    return raw[:keep] + _TRUNCATED_SUFFIX


async def log_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    request: Optional[Request] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Добавить событие в audit_log.

    ВАЖНО: функция НЕ делает commit — это ответственность вызывающего
    handler'а (см. docstring модуля). db.add() ставит объект в pending-очередь
    сессии, он уйдёт в БД вместе с остальными изменениями при db.commit().

    Все параметры после `db` — keyword-only (через `*`), чтобы случайно
    не перепутать порядок `action` и `user_id` в вызове.
    """
    entry = AuditLog(
        action=action,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        ip=_client_ip(request),
        details=_serialize_details(details),
    )
    db.add(entry)
    # Flush (но не commit): получаем id, ловим constraint-ошибки ДО
    # того как handler продолжит работу. Если флашить позже — ошибка
    # всплывёт из commit и придётся разбираться, какая именно модель
    # упала. При flush здесь — ошибка локальна этой строке.
    await db.flush()
