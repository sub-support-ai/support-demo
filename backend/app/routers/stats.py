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
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.ai_fallback_event import AIFallbackEvent
from app.models.ai_job import AIJob
from app.models.ai_log import AILog
from app.models.conversation import Conversation
from app.models.knowledge_article import KnowledgeArticle, KnowledgeArticleFeedback
from app.models.knowledge_embedding_job import KnowledgeEmbeddingJob
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.ticket_rating import TicketRating
from app.models.user import User
from app.schemas.stats import (
    AIFallbacksStats,
    AIStats,
    JobQueueStats,
    JobsStats,
    KBArticleQualityItem,
    KBQualityStats,
    KnowledgeScoreBucket,
    KnowledgeScoreDistribution,
    StatsResponse,
    TicketStats,
    UnansweredQuery,
)
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
    total_result = await db.execute(select(func.count()).select_from(Ticket).where(*ticket_filters))
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

    # Топ-темы (ai_category) — для дашборда «Популярные категории»
    category_result = await db.execute(
        select(Ticket.ai_category, func.count().label("cnt"))
        .where(*ticket_filters, Ticket.ai_category.is_not(None))
        .group_by(Ticket.ai_category)
        .order_by(func.count().desc())
        .limit(20)
    )
    # Словарь уже отсортирован по убыванию (Python 3.7+ dict сохраняет порядок вставки)
    by_category = {row.ai_category: row.cnt for row in category_result if row.ai_category}

    sla_overdue_result = await db.execute(
        select(func.count())
        .select_from(Ticket)
        .where(
            *ticket_filters,
            Ticket.status.in_(tuple(OPEN_STATUSES)),
            Ticket.sla_deadline_at.is_not(None),
            Ticket.sla_deadline_at < datetime.now(UTC),
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

    # TTFR = среднее (first_response_at - created_at) по решённым/закрытым тикетам
    # TTR  = среднее (resolved_at - created_at)
    # epoch() переводит interval в секунды (PostgreSQL-специфично; SQLite в тестах
    # не поддерживает эту функцию — там avg будет None, и мы защищаемся проверкой).
    ttfr_result = await db.execute(
        select(
            func.avg(func.extract("epoch", Ticket.first_response_at - Ticket.created_at)).label(
                "avg_ttfr"
            )
        ).where(
            *ticket_filters,
            Ticket.first_response_at.is_not(None),
        )
    )
    ttr_result = await db.execute(
        select(
            func.avg(func.extract("epoch", Ticket.resolved_at - Ticket.created_at)).label("avg_ttr")
        ).where(
            *ticket_filters,
            Ticket.resolved_at.is_not(None),
        )
    )
    avg_ttfr = ttfr_result.scalar()
    avg_ttr = ttr_result.scalar()

    # Средняя CSAT-оценка (1–5) по оценённым тикетам из скоупа пользователя.
    # JOIN всегда: исключаем «осиротевшие» оценки (тикет удалён), а для admin
    # ticket_filters=[] → WHERE () опускается, возвращается глобальный avg.
    csat_query = (
        select(func.avg(TicketRating.rating).label("avg_csat"))
        .join(Ticket, TicketRating.ticket_id == Ticket.id)
        .where(*ticket_filters)
    )
    csat_result = await db.execute(csat_query)
    avg_csat = csat_result.scalar()

    ticket_stats = TicketStats(
        total=total_tickets,
        by_status=by_status,
        by_department=by_department,
        by_source=by_source,
        by_category=by_category,
        sla_overdue_count=sla_overdue_result.scalar() or 0,
        sla_escalated_count=sla_escalated_result.scalar() or 0,
        reopen_count=reopen_result.scalar() or 0,
        avg_ttfr_seconds=round(float(avg_ttfr), 1) if avg_ttfr is not None else None,
        avg_ttr_seconds=round(float(avg_ttr), 1) if avg_ttr is not None else None,
        avg_csat_score=round(float(avg_csat), 2) if avg_csat is not None else None,
    )

    # ── Статистика AI ─────────────────────────────────────────────────────────

    # Общие метрики из ai_logs одним запросом
    ai_stats_query = select(
        func.count().label("total"),
        func.avg(AILog.confidence_score).label("avg_confidence"),
        # Тикеты с низкой уверенностью (< 0.8) — нужна проверка агентом
        func.sum(case((AILog.confidence_score < 0.8, 1), else_=0)).label("low_confidence"),
        # Роутинг подтверждён агентом
        func.sum(case((AILog.routing_was_correct.is_(True), 1), else_=0)).label("routing_correct"),
        # Роутинг исправлен агентом
        func.sum(case((AILog.routing_was_correct.is_(False), 1), else_=0)).label(
            "routing_incorrect"
        ),
        # AI решил без тикета
        func.sum(case((AILog.outcome == "resolved_by_ai", 1), else_=0)).label("resolved_by_ai"),
        # AI создал тикет (пользователь принял или написал свой)
        func.sum(
            case((AILog.outcome.in_(["escalated_ai_ticket", "escalated_user_ticket"]), 1), else_=0)
        ).label("escalated"),
        # Обратная связь
        func.sum(case((AILog.user_feedback == "helped", 1), else_=0)).label("feedback_helped"),
        func.sum(case((AILog.user_feedback == "not_helped", 1), else_=0)).label(
            "feedback_not_helped"
        ),
    )
    if current_user.role == "admin":
        pass
    elif current_user.role == "agent":
        ai_stats_query = ai_stats_query.join(Ticket, AILog.ticket_id == Ticket.id).where(
            *ticket_filters
        )
    else:
        ai_stats_query = (
            ai_stats_query.outerjoin(Ticket, AILog.ticket_id == Ticket.id)
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
        round(routing_correct / total_reviewed * 100, 1) if total_reviewed > 0 else 0.0
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
        select(KnowledgeEmbeddingJob.status, func.count().label("cnt")).group_by(
            KnowledgeEmbeddingJob.status
        )
    )
    jobs_stats = JobsStats(
        ai=_queue_stats(ai_jobs_result),
        knowledge_embeddings=_queue_stats(knowledge_jobs_result),
    )

    logger.info(
        "Статистика собрана",
        extra={"total_tickets": total_tickets, "total_ai_processed": total_processed},
    )

    return StatsResponse(tickets=ticket_stats, ai=ai_stats, jobs=jobs_stats)


# ── Fallback-события AI ─────────────────────────────────────────────────────


# Дефолтное окно — 24 часа: за этот период обычно успевают набраться значимые
# цифры (если в час идёт <1 события, недельный график был бы полезнее, но
# на демо кейс «AI лёг полчаса назад» важнее, чем недельный тренд).
DEFAULT_FALLBACKS_WINDOW = timedelta(hours=24)
MAX_FALLBACKS_WINDOW_DAYS = 30


@router.get(
    "/ai/fallbacks",
    response_model=AIFallbacksStats,
    summary="Агрегат fallback-событий AI за окно времени",
    description=(
        "Возвращает количество событий fallback'а AI-сервиса за указанное окно "
        "с группировкой по причинам (timeout/connect/http_5xx/broken_json/"
        "empty_response) и источникам (answer/classify). Только админам — "
        "содержит чувствительную информацию о работе инфраструктуры."
    ),
)
async def get_ai_fallbacks_stats(
    since: datetime | None = Query(
        default=None,
        description=(
            "Начало окна (ISO8601 с таймзоной). По умолчанию — 24 часа назад. "
            f"Окно ограничено {MAX_FALLBACKS_WINDOW_DAYS} днями для защиты от scan'а всей таблицы."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    now = datetime.now(UTC)
    if since is None:
        since_dt = now - DEFAULT_FALLBACKS_WINDOW
    else:
        # Ограничиваем глубину окна: запрос «всё за всё время» по таблице
        # без LIMIT'а на больших объёмах съест диск IO.
        earliest_allowed = now - timedelta(days=MAX_FALLBACKS_WINDOW_DAYS)
        since_dt = max(since, earliest_allowed)

    # Если входящий datetime naive — считаем UTC, иначе фильтр по
    # AIFallbackEvent.created_at >= since будет сравнивать разные TZ.
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=UTC)

    by_reason_result = await db.execute(
        select(AIFallbackEvent.reason, func.count().label("cnt"))
        .where(AIFallbackEvent.created_at >= since_dt)
        .group_by(AIFallbackEvent.reason)
    )
    by_reason = {row.reason: int(row.cnt) for row in by_reason_result}

    by_service_result = await db.execute(
        select(AIFallbackEvent.service, func.count().label("cnt"))
        .where(AIFallbackEvent.created_at >= since_dt)
        .group_by(AIFallbackEvent.service)
    )
    by_service = {row.service: int(row.cnt) for row in by_service_result}

    return AIFallbacksStats(
        since=since_dt.isoformat(),
        total=sum(by_reason.values()),
        by_reason=by_reason,
        by_service=by_service,
    )


# ── Качество базы знаний ────────────────────────────────────────────────────

_EXPIRY_WARN_DAYS = 14
_MIN_FEEDBACK_FOR_QUALITY = 3
_UNANSWERED_LIMIT = 25


@router.get(
    "/knowledge",
    response_model=KBQualityStats,
    summary="Качество базы знаний",
    description=(
        "Возвращает статьи с плохой обратной связью, никогда не показанные, "
        "с истекающим сроком и запросы без KB-ответа. Только для admin."
    ),
)
async def get_kb_quality(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    now = datetime.now(UTC)
    expiry_threshold = now + timedelta(days=_EXPIRY_WARN_DAYS)

    bad_result = await db.execute(
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_active.is_(True),
            (KnowledgeArticle.not_helped_count + KnowledgeArticle.not_relevant_count)
            > KnowledgeArticle.helped_count,
            (
                KnowledgeArticle.helped_count
                + KnowledgeArticle.not_helped_count
                + KnowledgeArticle.not_relevant_count
            )
            >= _MIN_FEEDBACK_FOR_QUALITY,
        )
        .order_by(
            (KnowledgeArticle.not_helped_count + KnowledgeArticle.not_relevant_count).desc()
        )
        .limit(20)
    )
    not_helping = [_article_quality_item(a) for a in bad_result.scalars().all()]

    never_result = await db.execute(
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_active.is_(True),
            KnowledgeArticle.view_count == 0,
        )
        .order_by(KnowledgeArticle.id.asc())
        .limit(30)
    )
    never_shown = [_article_quality_item(a) for a in never_result.scalars().all()]

    expiring_result = await db.execute(
        select(KnowledgeArticle)
        .where(
            KnowledgeArticle.is_active.is_(True),
            KnowledgeArticle.expires_at.is_not(None),
            KnowledgeArticle.expires_at <= expiry_threshold,
        )
        .order_by(KnowledgeArticle.expires_at.asc())
        .limit(20)
    )
    expiring_soon = [_article_quality_item(a) for a in expiring_result.scalars().all()]

    escalated_conv_ids_q = (
        select(Conversation.id)
        .where(Conversation.status == "escalated")
        .scalar_subquery()
    )
    unansw_result = await db.execute(
        select(
            Message.content.label("query"),
            func.count().label("cnt"),
            func.max(Message.created_at).label("last_seen"),
        )
        .where(
            Message.role == "user",
            Message.conversation_id.in_(escalated_conv_ids_q),
            func.length(Message.content) > 10,
        )
        .group_by(Message.content)
        .order_by(func.count().desc())
        .limit(_UNANSWERED_LIMIT)
    )
    unanswered_queries = [
        UnansweredQuery(query=row.query, count=int(row.cnt), last_seen=row.last_seen)
        for row in unansw_result
    ]

    return KBQualityStats(
        not_helping=not_helping,
        never_shown=never_shown,
        expiring_soon=expiring_soon,
        unanswered_queries=unanswered_queries,
    )


def _article_quality_item(article: KnowledgeArticle) -> KBArticleQualityItem:
    total = article.helped_count + article.not_helped_count + article.not_relevant_count
    ratio = round(article.helped_count / total, 2) if total > 0 else None
    return KBArticleQualityItem(
        id=article.id,
        title=article.title,
        department=article.department,
        view_count=article.view_count,
        helped_count=article.helped_count,
        not_helped_count=article.not_helped_count,
        not_relevant_count=article.not_relevant_count,
        expires_at=article.expires_at,
        helpfulness_ratio=ratio,
    )


# ── Score distribution для калибровки порогов ───────────────────────────────

_SCORE_BUCKETS: list[tuple[float, float]] = [
    (0.0, 2.0),
    (2.0, 4.0),
    (4.0, 6.0),
    (6.0, 8.0),
    (8.0, 12.0),
    (12.0, 16.0),
    (16.0, 24.0),
    (24.0, 999.0),
]


@router.get(
    "/knowledge/score-distribution",
    response_model=KnowledgeScoreDistribution,
    summary="Распределение KB-скор'ов за период (для калибровки порогов)",
)
async def get_kb_score_distribution(
    days: int = Query(default=30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    settings = get_settings()
    since = datetime.now(UTC) - timedelta(days=days)

    rows = await db.execute(
        select(KnowledgeArticleFeedback.score, KnowledgeArticleFeedback.decision).where(
            KnowledgeArticleFeedback.created_at >= since
        )
    )
    records = list(rows.all())
    total = len(records)

    counts = [0] * len(_SCORE_BUCKETS)
    decision_counts: dict[str, int] = {}
    for score, decision in records:
        s = float(score or 0.0)
        for index, (start, end) in enumerate(_SCORE_BUCKETS):
            if start <= s < end:
                counts[index] += 1
                break
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    buckets = [
        KnowledgeScoreBucket(range_start=start, range_end=end, count=cnt)
        for (start, end), cnt in zip(_SCORE_BUCKETS, counts, strict=True)
    ]

    return KnowledgeScoreDistribution(
        period_days=days,
        total_feedback_records=total,
        buckets=buckets,
        decision_distribution=decision_counts,
        current_thresholds={
            "high": settings.RAG_SCORE_HIGH_THRESHOLD,
            "medium": settings.RAG_SCORE_MEDIUM_THRESHOLD,
            "red_zone": settings.RAG_CONFIDENCE_RED_ZONE,
        },
    )
