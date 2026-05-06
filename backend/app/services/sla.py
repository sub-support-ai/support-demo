from datetime import datetime, timedelta, timezone
from typing import Any

OPEN_STATUSES = {"confirmed", "in_progress"}
SLA_HOURS_BY_PRIORITY = {
    "критический": 4,
    "высокий": 8,
    "средний": 24,
    "низкий": 72,
}
DEFAULT_SLA_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_priority(priority: object) -> str:
    if not isinstance(priority, str):
        return "средний"
    return priority.strip().lower() or "средний"


def get_sla_hours(ticket: Any) -> int:
    priority = _normalize_priority(getattr(ticket, "ai_priority", None))
    return SLA_HOURS_BY_PRIORITY.get(priority, DEFAULT_SLA_HOURS)


def start_ticket_sla(ticket: Any, started_at: datetime | None = None) -> None:
    started = started_at or _utc_now()
    ticket.sla_started_at = started
    ticket.sla_deadline_at = started + timedelta(hours=get_sla_hours(ticket))
    if hasattr(ticket, "sla_escalated_at"):
        ticket.sla_escalated_at = None


def is_sla_breached(ticket: Any, now: datetime | None = None) -> bool:
    deadline = getattr(ticket, "sla_deadline_at", None)
    status = getattr(ticket, "status", None)
    if deadline is None or status not in OPEN_STATUSES:
        return False

    current_time = now or _utc_now()
    if deadline.tzinfo is None:
        current_time = current_time.replace(tzinfo=None)
    return deadline < current_time
