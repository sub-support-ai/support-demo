from pydantic import BaseModel


class TicketStats(BaseModel):
    """Статистика по тикетам."""
    total: int                  # всего тикетов в системе
    by_status: dict[str, int]   # сколько тикетов в каждом статусе
    by_department: dict[str, int]  # сколько тикетов по отделам
    by_source: dict[str, int]   # ai_generated / user_written / ai_assisted
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
    total_processed: int            # сколько тикетов AI обработал
    avg_confidence: float           # средняя уверенность модели (0.0–1.0)
    low_confidence_count: int       # тикетов с уверенностью < 0.8 (нужна проверка)
    routing_correct_count: int      # агент подтвердил роутинг AI
    routing_incorrect_count: int    # агент исправил роутинг AI
    routing_accuracy_pct: float     # % правильного роутинга
    resolved_by_ai_count: int       # AI решил без тикета
    escalated_count: int            # AI создал тикет
    user_feedback_helped: int       # пользователь сказал "помогло"
    user_feedback_not_helped: int   # пользователь сказал "не помогло"


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


class KnowledgeArticleSummary(BaseModel):
    """Карточка статьи в KB-дашборде. Минимум для админа: title и счётчики."""
    article_id: int
    title: str
    department: str | None = None
    request_type: str | None = None
    view_count: int = 0
    helped_count: int = 0
    not_helped_count: int = 0
    not_relevant_count: int = 0
    helpfulness_pct: float | None = None  # helped / (helped+not_helped+not_relevant), None если 0
    is_active: bool = True
    expires_at: str | None = None  # ISO8601


class KnowledgeStats(BaseModel):
    """Метрики KB для админ-дашборда."""
    total_articles: int
    active_articles: int
    drafts: int  # is_active=False — обычно черновики из promote-to-kb
    by_department: dict[str, int]
    expiring_soon_count: int  # активных, у которых expires_at в ближайшие 30 дней
    expired_count: int  # активных, у которых expires_at уже прошёл (фильтруются на поиске)
    # Самые помогающие — топ по helped_count (и helpfulness_pct, как тай-брейк)
    top_helped: list[KnowledgeArticleSummary]
    # Самые «не помогающие» — топ по not_helped_count (явные кандидаты на ревью)
    top_not_helped: list[KnowledgeArticleSummary]
    # Никогда не показывались пользователям — view_count = 0. Кандидаты на удаление.
    never_shown: list[KnowledgeArticleSummary]


class KnowledgeScoreBucket(BaseModel):
    """Один бакет гистограммы score'ов из feedback'ов."""
    range_start: float
    range_end: float
    count: int


class KnowledgeScoreDistribution(BaseModel):
    """Распределение score'ов KB-результатов за период.

    Используется для калибровки RAG_SCORE_HIGH_THRESHOLD /
    RAG_SCORE_MEDIUM_THRESHOLD: админ смотрит, как реальные score'ы
    распределяются и какая доля улетает в answer/clarify/escalate.

    decision_distribution показывает, сколько KB-ответов вышло на каждое
    решение state-machine'а. Если answer = 90% — порог занижен (модель
    самоуверенная). Если escalate = 50% — порог завышен или KB пустая.
    """
    period_days: int
    total_feedback_records: int
    buckets: list[KnowledgeScoreBucket]
    decision_distribution: dict[str, int]  # answer / clarify / escalate
    current_thresholds: dict[str, float]   # high / medium / red_zone


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
