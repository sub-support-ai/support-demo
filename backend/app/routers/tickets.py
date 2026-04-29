"""
Роутер тикетов — финальная версия с:
  - JWT защитой на все эндпоинты
  - Роутингом через app/services/routing.py (assign_agent / unassign_agent)
  - Логикой confidence < 0.8 → старший агент (внутри assign_agent)
  - Эндпоинтом PATCH /tickets/{id}/resolve — агент закрывает тикет
  - Записью feedback в ai_logs при resolve
  - Фильтром по department для Frontend 2
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.ai_log import AILog
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketDraftUpdate, TicketRead, TicketStatusUpdate
from app.services.audit import log_event
from app.services.routing import assign_agent, unassign_agent

router = APIRouter(prefix="/tickets", tags=["tickets"])


# ── Хелпер: загрузка тикета с проверкой доступа ───────────────────────────────
#
# ЗАЧЕМ отдельная функция, а не inline-проверка в каждой ручке:
#   1. DRY — одна и та же логика нужна в get/patch/resolve/delete.
#   2. Defense in depth — если добавим новый эндпоинт и забудем позвать хелпер,
#      баг будет виден при code review (прямой SELECT Ticket — красный флаг).
#   3. Единое место для изменения логики (когда появится роль agent).
#
# ПОЧЕМУ 404, а не 403, когда доступа нет:
#   Если вернуть 403 "Forbidden" — клиент понимает, что тикет с таким ID
#   существует, просто не ему. Это позволяет перебором вычислить количество
#   тикетов в системе и их диапазон ID. 404 "Not Found" не палит существование.

async def get_ticket_for_user(
    ticket_id: int,
    db: AsyncSession,
    current_user: User,
) -> Ticket:
    """Загрузить тикет и проверить, что текущий пользователь имеет к нему доступ.

    Доступ есть у:
      - владельца тикета (ticket.user_id == current_user.id)
      - администратора (current_user.role == "admin")

    Во всех остальных случаях — 404 (не 403, чтобы не палить существование ID).
    """
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    if current_user.role == "admin":
        return ticket

    if ticket.user_id != current_user.id:
        # НЕ 403 — см. комментарий выше про "don't leak resource existence"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    return ticket


# ── Схема для resolve ─────────────────────────────────────────────────────────

class ResolvePayload(BaseModel):
    """
    Тело запроса при закрытии тикета агентом.

    agent_accepted_ai_response:
        True  — агент согласился с черновиком AI и отправил его как есть
        False — агент написал свой ответ
    correction_lag_seconds:
        Сколько секунд прошло между созданием тикета и закрытием.
        Нужно для метрик скорости работы.
    """
    agent_accepted_ai_response: bool
    correction_lag_seconds: int | None = None


# ── POST /tickets/ ─────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать тикет",
    description="Создаёт тикет, вызывает AI классификацию и назначает агента. "
                "Если AI уверен < 0.8 — назначается старший агент для проверки.",
)
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ai_classifier import classify_ticket

    ai_result = await classify_ticket(
        ticket_id=0,
        title=payload.title,
        body=payload.body,
    )

    # Приоритет: явное поле от пользователя > ответ AI > "IT" по умолчанию
    department = payload.department or ai_result.get("department") or "IT"

    ticket = Ticket(
        # user_id ВСЕГДА из токена — не из тела запроса. См. комментарий в
        # TicketCreate (app/schemas/ticket.py) про атаку подмены user_id.
        user_id=current_user.id,
        title=payload.title,
        body=payload.body,
        user_priority=payload.user_priority,
        department=department,
        ai_category=ai_result.get("category"),
        ai_priority=ai_result.get("priority"),
        ai_confidence=ai_result.get("confidence"),
        ai_processed_at=datetime.now(timezone.utc),
    )
    db.add(ticket)
    await db.flush()

    await assign_agent(db, ticket)
    # flush до refresh — иначе SELECT из refresh() затрёт agent_id в памяти
    await db.flush()

    # Пишем AILog при создании — время ответа AI попадает в метрики
    # "1,01 сек" из питч-дека (ai_response_time_ms).
    #
    # model_version: если AI Service не вернул — берём настроенный fallback
    # из .env (AI_MODEL_VERSION_FALLBACK), а не литерал "unknown". Литерал
    # отравлял датасет: разные версии модели сваливались в одну корзину
    # "unknown", метрики качества по версиям не считались.
    settings = get_settings()
    db.add(AILog(
        ticket_id=ticket.id,
        model_version=(
            ai_result.get("model_version")
            or settings.AI_MODEL_VERSION_FALLBACK
        ),
        predicted_category=ai_result.get("category") or "неизвестно",
        predicted_priority=ai_result.get("priority") or "средний",
        confidence_score=float(ai_result.get("confidence") or 0.0),
        routed_to_agent_id=ticket.agent_id,
        ai_response_draft=ai_result.get("draft_response"),
        ai_response_time_ms=ai_result.get("response_time_ms"),
    ))

    await db.refresh(ticket)

    await log_event(
        db,
        action="ticket.create",
        user_id=current_user.id,
        target_type="ticket",
        target_id=ticket.id,
        request=request,
        details={"department": ticket.department, "ai_priority": ticket.ai_priority},
    )

    return ticket


# ── GET /tickets/ ──────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[TicketRead],
    summary="Список тикетов",
    description="Возвращает тикеты с пагинацией. "
                "Фильтр department: IT, HR, finance.",
)
async def list_tickets(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    department: str | None = Query(default=None, description="Фильтр по отделу: IT, HR, finance"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Ticket)

    # Обычный пользователь видит ТОЛЬКО свои тикеты.
    # Админ — все (в т.ч. с фильтром по department).
    # Когда появится роль "agent" — добавим ветку Ticket.agent_id == ...
    if current_user.role != "admin":
        query = query.where(Ticket.user_id == current_user.id)

    if department:
        query = query.where(Ticket.department == department)
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


# ── GET /tickets/{id} ──────────────────────────────────────────────────────────

@router.get(
    "/{ticket_id}",
    response_model=TicketRead,
    summary="Получить тикет по ID",
)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_ticket_for_user(ticket_id, db, current_user)


# ── PATCH /tickets/{id} — обновить статус ─────────────────────────────────────

@router.patch(
    "/{ticket_id}",
    response_model=TicketRead,
    summary="Обновить статус тикета",
)
async def update_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_for_user(ticket_id, db, current_user)

    old_status = ticket.status
    ticket.status = payload.status

    closing_statuses = {"resolved", "closed"}
    if payload.status in closing_statuses and old_status not in closing_statuses:
        await unassign_agent(db, ticket)
        ticket.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(ticket)
    return ticket


# ── PATCH /tickets/{id}/draft — пользователь правит AI-черновик до отправки ──

@router.patch(
    "/{ticket_id}/draft",
    response_model=TicketRead,
    summary="Обновить черновик тикета перед отправкой",
    description=(
        "Позволяет владельцу тикета изменить pre-filled черновик до подтверждения: "
        "тему, описание, отдел, приоритет и поле 'что уже пробовали'."
    ),
)
async def update_ticket_draft(
    ticket_id: int,
    payload: TicketDraftUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_for_user(ticket_id, db, current_user)

    if ticket.status != "pending_user" or ticket.confirmed_by_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Редактировать можно только неподтвержденный черновик тикета",
        )

    update_data = payload.model_dump(exclude_unset=True)
    old_department = ticket.department

    if "title" in update_data and update_data["title"] is not None:
        ticket.title = update_data["title"].strip()
    if "body" in update_data and update_data["body"] is not None:
        ticket.body = update_data["body"].strip()
    if "department" in update_data and update_data["department"] is not None:
        ticket.department = update_data["department"]
    if "ai_priority" in update_data and update_data["ai_priority"] is not None:
        ticket.ai_priority = update_data["ai_priority"]
    if "steps_tried" in update_data:
        steps_tried = update_data["steps_tried"]
        ticket.steps_tried = steps_tried.strip() if steps_tried else None

    if not ticket.title or not ticket.body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Тема и описание черновика не должны быть пустыми",
        )

    if ticket.department != old_department:
        await unassign_agent(db, ticket)
        ticket.agent_id = None
        await assign_agent(db, ticket)

    await db.flush()
    await db.refresh(ticket)
    return ticket


# ── PATCH /tickets/{id}/confirm — пользователь подтверждает AI-черновик ───────

@router.patch(
    "/{ticket_id}/confirm",
    response_model=TicketRead,
    summary="Подтвердить отправку тикета",
    description=(
        "Подтверждает pre-filled тикет, созданный из диалога AI. "
        "Ставит confirmed_by_user=True и status=confirmed. "
        "Если агент ещё не назначен, запускает роутинг."
    ),
)
async def confirm_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_for_user(ticket_id, db, current_user)

    if ticket.status != "pending_user" or ticket.confirmed_by_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Подтвердить можно только неподтверждённый черновик тикета",
        )

    ticket.confirmed_by_user = True
    ticket.status = "confirmed"

    if ticket.agent_id is None:
        await assign_agent(db, ticket)

    await db.flush()
    await db.refresh(ticket)
    return ticket


# ── PATCH /tickets/{id}/resolve — агент закрывает тикет ───────────────────────

@router.patch(
    "/{ticket_id}/resolve",
    response_model=TicketRead,
    summary="Закрыть тикет (агент)",
    description=(
        "Агент принимает решение по тикету. Статус → closed, resolved_at = now(). "
        "Записывает в ai_logs: принял ли агент черновик AI и за сколько секунд."
    ),
)
async def resolve_ticket(
    ticket_id: int,
    payload: ResolvePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_for_user(ticket_id, db, current_user)

    old_status = ticket.status
    ticket.status = "closed"
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.confirmed_by_user = True

    if old_status not in {"resolved", "closed"}:
        await unassign_agent(db, ticket)

    # Записываем или обновляем ai_log
    log_result = await db.execute(
        select(AILog)
        .where(AILog.ticket_id == ticket_id)
        .order_by(AILog.created_at.desc())
        .limit(1)
    )
    ai_log = log_result.scalar_one_or_none()

    if ai_log:
        ai_log.agent_accepted_ai_response = payload.agent_accepted_ai_response
        ai_log.routing_was_correct = True
        ai_log.reviewed_at = datetime.now(timezone.utc)
        if payload.correction_lag_seconds is not None:
            ai_log.correction_lag_seconds = payload.correction_lag_seconds
    else:
        ai_log = AILog(
            ticket_id=ticket_id,
            model_version="manual",
            predicted_category=ticket.ai_category or "неизвестно",
            predicted_priority=ticket.ai_priority or "средний",
            confidence_score=ticket.ai_confidence or 0.0,
            agent_accepted_ai_response=payload.agent_accepted_ai_response,
            routing_was_correct=True,
            reviewed_at=datetime.now(timezone.utc),
            correction_lag_seconds=payload.correction_lag_seconds,
        )
        db.add(ai_log)

    await db.flush()
    await db.refresh(ticket)
    return ticket


# ── DELETE /tickets/{id} — только admin ───────────────────────────────────────

@router.delete(
    "/{ticket_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить тикет",
    description="Доступно только администраторам (role=admin).",
)
async def delete_ticket(
    ticket_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    # admin проходит проверку внутри get_ticket_for_user автоматически —
    # используем хелпер для единообразия (один паттерн загрузки во всех ручках).
    ticket = await get_ticket_for_user(ticket_id, db, admin)

    if ticket.status not in {"resolved", "closed"}:
        await unassign_agent(db, ticket)

    # Аудит ПЕРЕД db.delete — пока ticket ещё жив и его user_id/title доступны.
    # После delete объект становится "deleted" и трогать его поля нельзя.
    await log_event(
        db,
        action="ticket.delete",
        user_id=admin.id,
        target_type="ticket",
        target_id=ticket.id,
        request=request,
        details={"owner_user_id": ticket.user_id, "title": ticket.title},
    )

    await db.delete(ticket)
    await db.flush()
