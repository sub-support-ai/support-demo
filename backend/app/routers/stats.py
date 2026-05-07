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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.ticket import Ticket
from app.models.ai_log import AILog
from app.models.ai_job import AIJob
from app.models.conversation import Conversation
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.user import User
from app.schemas.stats import AIStats, JobQueueStats, JobsStats, StatsResponse, TicketStats
from app.services.agents import get_active_agent_for_user
from app.services.sla import OPEN_STATUSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])


def _queue_stats(rows) -> JobQueueStats:
    by_status = {row.status: row.cnt for row in rows}
    return JobQueueStats(
        total=sum(by_status.values()),
        queued=by_status.get("queued", 0),
        running=by_status.get("running", 0),
        done=by_status.get("done", 0),
        failed=by_status.get("failed", 0),
    )


async def _ticket_scope_filters(
    db: AsyncSession,
    current_user: User,
):
    if current_user.role == "admin":
        return []
    if current_user.role == "agent":
        agent = await get_active_agent_for_user(db, current_user)
        if agent is None:
            return [Ticket.id == -1]
        return [Ticket.agent_id == agent.id]
    return [Ticket.user_id == current_user.id]


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
    ticket_filters = await _ticket_scope_filters(db, current_user)
    total_result = await db.execute(
        select(func.count()).select_from(Ticket).where(*ticket_filters)
    )
    total_tickets = total_result.scalar() or 0

    # По статусам: {"new": 5, "in_progress": 12, "resolved": 30, ...}
    status_result = await db.execute(
        select(Ticket.status, func.count().label("cnt"))
        .where(*ticket_filters)
        .group_by(Ticket.status)
    )
    by_status = {row.status: row.cnt for row in status_result}

    # По отделам: {"IT": 20, "HR": 5, "finance": 8}
    dept_result = await db.execute(
        select(Ticket.department, func.count().label("cnt"))
        .where(*ticket_filters)
        .group_by(Ticket.department)
    )
    by_department = {row.department: row.cnt for row in dept_result}

    # По источнику: {"ai_generated": 25, "user_written": 8, "ai_assisted": 3}
    source_result = await db.execute(
        select(Ticket.ticket_source, func.count().label("cnt"))
        .where(*ticket_filters)
        .group_by(Ticket.ticket_source)
    )
    by_source = {row.ticket_source: row.cnt for row in source_result}

    sla_overdue_result = await db.execute(
        select(func.count())
        .select_from(Ticket)
        .where(
            *ticket_filters,
            Ticket.status.in_(tuple(OPEN_STATUSES)),
            Ticket.sla_deadline_at.is_not(None),
            Ticket.sla_deadline_at < datetime.now(timezone.utc),
        )
    )
    reopen_result = await db.execute(
        select(func.coalesce(func.sum(Ticket.reopen_count), 0))
        .select_from(Ticket)
        .where(*ticket_filters)
    )
    sla_escalated_result = await db.execute(
        select(func.count())
        .select_from(Ticket)
        .where(
            *ticket_filters,
            Ticket.sla_escalated_at.is_not(None),
        )
    )

    ticket_stats = TicketStats(
        total=total_tickets,
        by_status=by_status,
        by_department=by_department,
        by_source=by_source,
        sla_overdue_count=sla_overdue_result.scalar() or 0,
        sla_escalated_count=sla_escalated_result.scalar() or 0,
        reopen_count=reopen_result.scalar() or 0,
    )

    # ── Статистика AI ─────────────────────────────────────────────────────────

    # Общие метрики из ai_logs одним запросом
    ai_stats_query = select(
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
    if current_user.role == "admin":
        pass
    elif current_user.role == "agent":
        ai_stats_query = (
            ai_stats_query
            .join(Ticket, AILog.ticket_id == Ticket.id)
            .where(*ticket_filters)
        )
    else:
        ai_stats_query = (
            ai_stats_query
            .outerjoin(Ticket, AILog.ticket_id == Ticket.id)
            .outerjoin(Conversation, AILog.conversation_id == Conversation.id)
            .where(
                or_(
                    Ticket.user_id == current_user.id,
                    Conversation.user_id == current_user.id,
                )
            )
        )
    ai_result = await db.execute(ai_stats_query)
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

    ai_jobs_result = await db.execute(
        select(AIJob.status, func.count().label("cnt")).group_by(AIJob.status)
    )
    knowledge_jobs_result = await db.execute(
        select(KnowledgeEmbeddingJob.status, func.count().label("cnt"))
        .group_by(KnowledgeEmbeddingJob.status)
    )
    jobs_stats = JobsStats(
        ai=_queue_stats(ai_jobs_result),
        knowledge_embeddings=_queue_stats(knowledge_jobs_result),
    )

    logger.info(
        "Статистика собрана",
        extra={"total_tickets": total_tickets, "total_ai_processed": total_processed}
    )

    return StatsResponse(tickets=ticket_stats, ai=ai_stats, jobs=jobs_stats)
