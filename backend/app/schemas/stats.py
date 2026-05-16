from datetime import datetime

from pydantic import BaseModel


class TicketStats(BaseModel):
    """Статистика по тикетам."""

    total: int  # всего тикетов в системе
    by_status: dict[str, int]  # сколько тикетов в каждом статусе
    by_department: dict[str, int]  # сколько тикетов по отделам
    by_source: dict[str, int]  # ai_generated / user_written / ai_assisted
    # Топ-темы (ai_category): {"VPN access": 15, "printer": 8, ...}
    # Отсортированы по убыванию — первые N самых частых.
    by_category: dict[str, int] = {}
    sla_overdue_count: int = 0
    sla_escalated_count: int = 0
    reopen_count: int = 0
    # Среднее время первого ответа агента (секунды). None если данных нет.
    avg_ttfr_seconds: float | None = None
    # Среднее время полного решения тикета (секунды). None если данных нет.
    avg_ttr_seconds: float | None = None
    # Средняя оценка CSAT (1.0–5.0). None если оценок нет.
    avg_csat_score: float | None = None


class AIStats(BaseModel):
    """Статистика работы AI-классификатора."""

    total_processed: int  # сколько тикетов AI обработал
    avg_confidence: float  # средняя уверенность модели (0.0–1.0)
    low_confidence_count: int  # тикетов с уверенностью < 0.8 (нужна проверка)
    routing_correct_count: int  # агент подтвердил роутинг AI
    routing_incorrect_count: int  # агент исправил роутинг AI
    routing_accuracy_pct: float  # % правильного роутинга
    resolved_by_ai_count: int  # AI решил без тикета
    escalated_count: int  # AI создал тикет
    user_feedback_helped: int  # пользователь сказал "помогло"
    user_feedback_not_helped: int  # пользователь сказал "не помогло"


class JobQueueStats(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0


class JobsStats(BaseModel):
    ai: JobQueueStats
    knowledge_embeddings: JobQueueStats


class StatsResponse(BaseModel):
    """Полный ответ эндпоинта GET /api/v1/stats/."""

    tickets: TicketStats
    ai: AIStats
    jobs: JobsStats


class KBArticleQualityItem(BaseModel):
    id: int
    title: str
    department: str | None = None
    view_count: int = 0
    helped_count: int = 0
    not_helped_count: int = 0
    not_relevant_count: int = 0
    expires_at: datetime | None = None
    helpfulness_ratio: float | None = None


class UnansweredQuery(BaseModel):
    query: str
    count: int
    last_seen: datetime


class KBQualityStats(BaseModel):
    """Качество базы знаний — для страницы аналитики KB."""

    not_helping: list[KBArticleQualityItem] = []
    never_shown: list[KBArticleQualityItem] = []
    expiring_soon: list[KBArticleQualityItem] = []
    unanswered_queries: list[UnansweredQuery] = []


class KnowledgeScoreBucket(BaseModel):
    range_start: float
    range_end: float
    count: int


class KnowledgeScoreDistribution(BaseModel):
    period_days: int
    total_feedback_records: int
    buckets: list[KnowledgeScoreBucket]
    decision_distribution: dict[str, int]
    current_thresholds: dict[str, float]


class TrendPoint(BaseModel):
    """Одна точка тренда — дата (ISO YYYY-MM-DD) и значение."""

    date: str  # ISO-дата YYYY-MM-DD
    count: int


class TrendsResponse(BaseModel):
    """Тренды по тикетам за период — для линейных/столбчатых графиков.

    Каждая серия `tickets_created`/`tickets_resolved` содержит ровно
    `period_days + 1` точек (включая сегодняшнюю): дни без активности
    отдаются с count=0, чтобы фронт мог отрисовать непрерывный график
    без gap-логики на своей стороне.
    """

    period_days: int  # запрошенное окно (повтор из параметра)
    from_date: str  # начало окна, ISO-дата
    to_date: str  # конец окна (сегодня), ISO-дата
    tickets_created: list[TrendPoint]
    tickets_resolved: list[TrendPoint]


class AIFallbacksStats(BaseModel):
    """Агрегат fallback-событий за окно времени.

    by_reason / by_service — две независимые свёртки одних и тех же событий.
    UI на дашборде показывает их рядом: причина (timeout/connect/...) и
    источник (answer-чат / classify-тикет). Сумма в каждой свёртке == total.
    """

    since: str  # ISO8601 — начало окна, эхом от запроса
    total: int = 0
    by_reason: dict[str, int] = {}
    by_service: dict[str, int] = {}
