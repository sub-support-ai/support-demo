from datetime import datetime, timedelta, timezone

from app.models.ticket import Ticket

OPEN_STATUSES = {"new", "pending_user", "confirmed", "in_progress", "ai_processing"}

SLA_HOURS_BY_PRIORITY = {
    "критический": 4,
    "высокий": 8,
    "средний": 24,
    "низкий": 72,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_priority(ticket: Ticket) -> str:
    if ticket.ai_priority:
        return ticket.ai_priority.lower()
    if ticket.user_priority <= 2:
        return "высокий"
    if ticket.user_priority == 3:
        return "средний"
    return "низкий"


def get_sla_hours(ticket: Ticket) -> int:
    return SLA_HOURS_BY_PRIORITY.get(_normalize_priority(ticket), 24)


def start_ticket_sla(ticket: Ticket, started_at: datetime | None = None) -> None:
    start = started_at or _now()
    ticket.sla_started_at = start
    ticket.sla_deadline_at = start + timedelta(hours=get_sla_hours(ticket))


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_sla_breached(ticket: Ticket, now: datetime | None = None) -> bool:
    if ticket.status not in OPEN_STATUSES or ticket.sla_deadline_at is None:
        return False
    return _as_aware(ticket.sla_deadline_at) < (now or _now())
