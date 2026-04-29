"""
Эндпоинт GET /api/v1/stats/ — аналитика системы.

Что возвращает:
- Статистика по тикетам: сколько, в каких статусах, по отделам
- Статистика AI: точность роутинга, средняя уверенность, обратная связь

Кому нужно:
- Frontend Dev — отображает на аналитической панели (его задача 9)
- Команда — следит за качеством AI в реальном времени
- Питч-дек — конкретные цифры для инвесторов
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.ticket import Ticket
from app.models.ai_log import AILog
from app.models.user import User
from app.schemas.stats import StatsResponse, TicketStats, AIStats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Возвращает аналитику по тикетам и работе AI.

    Все данные считаются за один запрос к БД — быстро и без нагрузки.
    """
    logger.info("Запрос статистики")

    # ── Статистика тикетов ────────────────────────────────────────────────────

    # Всего тикетов
    total_result = await db.execute(select(func.count()).select_from(Ticket))
    total_tickets = total_result.scalar() or 0

    # По статусам: {"new": 5, "in_progress": 12, "resolved": 30, ...}
    status_result = await db.execute(
        select(Ticket.status, func.count().label("cnt"))
        .group_by(Ticket.status)
    )
    by_status = {row.status: row.cnt for row in status_result}

    # По отделам: {"IT": 20, "HR": 5, "finance": 8}
    dept_result = await db.execute(
        select(Ticket.department, func.count().label("cnt"))
        .group_by(Ticket.department)
    )
    by_department = {row.department: row.cnt for row in dept_result}

    # По источнику: {"ai_generated": 25, "user_written": 8, "ai_assisted": 3}
    source_result = await db.execute(
        select(Ticket.ticket_source, func.count().label("cnt"))
        .group_by(Ticket.ticket_source)
    )
    by_source = {row.ticket_source: row.cnt for row in source_result}

    ticket_stats = TicketStats(
        total=total_tickets,
        by_status=by_status,
        by_department=by_department,
        by_source=by_source,
    )

    # ── Статистика AI ─────────────────────────────────────────────────────────

    # Общие метрики из ai_logs одним запросом
    ai_result = await db.execute(
        select(
            func.count().label("total"),
            func.avg(AILog.confidence_score).label("avg_confidence"),
            # Тикеты с низкой уверенностью (< 0.8) — нужна проверка агентом
            func.sum(
                case((AILog.confidence_score < 0.8, 1), else_=0)
            ).label("low_confidence"),
            # Роутинг подтверждён агентом
            func.sum(
                case((AILog.routing_was_correct == True, 1), else_=0)
            ).label("routing_correct"),
            # Роутинг исправлен агентом
            func.sum(
                case((AILog.routing_was_correct == False, 1), else_=0)
            ).label("routing_incorrect"),
            # AI решил без тикета
            func.sum(
                case((AILog.outcome == "resolved_by_ai", 1), else_=0)
            ).label("resolved_by_ai"),
            # AI создал тикет (пользователь принял или написал свой)
            func.sum(
                case((AILog.outcome.in_(
                    ["escalated_ai_ticket", "escalated_user_ticket"]
                ), 1), else_=0)
            ).label("escalated"),
            # Обратная связь
            func.sum(
                case((AILog.user_feedback == "helped", 1), else_=0)
            ).label("feedback_helped"),
            func.sum(
                case((AILog.user_feedback == "not_helped", 1), else_=0)
            ).label("feedback_not_helped"),
        )
    )
    ai_row = ai_result.one()

    total_processed = ai_row.total or 0
    avg_confidence = round(float(ai_row.avg_confidence or 0.0), 3)
    routing_correct = ai_row.routing_correct or 0
    routing_incorrect = ai_row.routing_incorrect or 0
    total_reviewed = routing_correct + routing_incorrect
    

    # % правильного роутинга — 0 если агенты ещё ничего не проверяли
    routing_accuracy = (
        round(routing_correct / total_reviewed * 100, 1)
        if total_reviewed > 0 else 0.0
    )

    ai_stats = AIStats(
        total_processed=total_processed,
        avg_confidence=avg_confidence,
        low_confidence_count=ai_row.low_confidence or 0,
        routing_correct_count=routing_correct,
        routing_incorrect_count=routing_incorrect,
        routing_accuracy_pct=routing_accuracy,
        resolved_by_ai_count=ai_row.resolved_by_ai or 0,
        escalated_count=ai_row.escalated or 0,
        user_feedback_helped=ai_row.feedback_helped or 0,
        user_feedback_not_helped=ai_row.feedback_not_helped or 0,
    )

    logger.info(
        "Статистика собрана",
        extra={"total_tickets": total_tickets, "total_ai_processed": total_processed}
    )

    return StatsResponse(tickets=ticket_stats, ai=ai_stats)
