"""Админский endpoint для просмотра аудита.

Только admin — потому что журнал содержит:
  - username'ы, которые пытались подобрать (login.failure.details)
  - IP, с которых ходили
  - связки "кто что удалил"

Обычному юзеру всё это видеть не нужно, агенту — тоже.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/",
    response_model=list[AuditLogRead],
    summary="Журнал важных событий",
    description=(
        "Возвращает последние события (login, register, ticket.create/delete, ...). "
        "Сортировка: новые сверху. Доступно только админу."
    ),
)
async def list_audit_events(
    user_id: int | None = Query(
        default=None,
        description="Фильтр: только события этого пользователя. None = все пользователи.",
    ),
    action: str | None = Query(
        default=None,
        description="Фильтр по типу события (login.success, ticket.delete, ...).",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Сколько записей вернуть. Потолок 500 — чтобы случайно не выгрести миллион.",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> list[AuditLog]:
    # Главный запрос: последние события, опционально по юзеру/action.
    # Сортировка по id, а не created_at — id монотонно растёт и индексирован
    # как PK, запрос дешёвый. created_at могут иметь равные значения
    # у двух событий одной транзакции (одинаковый func.now()).
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)

    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action is not None:
        query = query.where(AuditLog.action == action)

    result = await db.execute(query)
    return list(result.scalars().all())
