from pydantic import BaseModel


class TicketStats(BaseModel):
    """Статистика по тикетам."""
    total: int                  # всего тикетов в системе
    by_status: dict[str, int]   # сколько тикетов в каждом статусе
    by_department: dict[str, int]  # сколько тикетов по отделам
    by_source: dict[str, int]   # ai_generated / user_written / ai_assisted
    sla_overdue_count: int = 0
    sla_escalated_count: int = 0
    reopen_count: int = 0


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
