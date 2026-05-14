"""Единая state-machine для статусов тикетов.

Прямое присваивание `ticket.status = X` запрещено — все переходы должны
идти через `transition` или `transition_via_operator`. Без этого правила
переходов разъезжаются по роутеру (раньше так и было: операторская матрица
жила в tickets.py, а confirm/resolve/reopen меняли статус мимо неё, и
любая регрессия в правилах ловилась только пользователями в проде).

Два набора:

    ALLOWED_TRANSITIONS         — полный граф, который видит сервис.
                                  Включает административные переходы:
                                  pending_user→confirmed (через /confirm),
                                  resolved/closed→confirmed (через reopen).
    ALLOWED_OPERATOR_TRANSITIONS — подмножество, доступное через
                                  PATCH /tickets/{id}. Намеренно НЕ
                                  включает reopen и подтверждение черновика:
                                  это административные пути, а не оператоский
                                  workflow.

Соответственно:
    transition_via_operator()   — для PATCH /tickets/{id}
    transition()                — для confirm / resolve / reopen
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.models.ticket import Ticket


# Терминальный статус — резолвить «closed → closed» как noop, отдельный
# приём в роутерах для запрета любых правок над закрытым тикетом.
TERMINAL_STATUSES: frozenset[str] = frozenset({"closed"})

# Полный граф разрешённых переходов по всем endpoint'ам.
# Источник истины для админских / системных путей (confirm / resolve / reopen).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_user": frozenset({"confirmed", "declined"}),
    "confirmed": frozenset({"in_progress", "resolved", "closed"}),
    "in_progress": frozenset({"confirmed", "resolved", "closed"}),
    "resolved": frozenset({"in_progress", "closed", "confirmed"}),  # последнее = reopen
    "closed": frozenset({"confirmed"}),  # reopen из терминала
}

# Что разрешено оператору через PATCH /tickets/{id}: то же, минус
# административные переходы (confirm/reopen — отдельные эндпоинты).
ALLOWED_OPERATOR_TRANSITIONS: dict[str, frozenset[str]] = {
    "confirmed": frozenset({"in_progress", "resolved", "closed"}),
    "in_progress": frozenset({"confirmed", "resolved", "closed"}),
    "resolved": frozenset({"in_progress", "closed"}),
    "closed": frozenset(),  # терминал; reopen — через feedback-endpoint
}


def _raise_invalid(
    old_status: str,
    new_status: str,
    allowed: frozenset[str],
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "Invalid ticket status transition",
            "from": old_status,
            "to": new_status,
            "allowed": sorted(allowed),
        },
    )


def transition(ticket: Ticket, new_status: str) -> str:
    """Универсальный переход. Применяется к confirm / resolve / reopen.

    Возвращает старый статус. Идемпотентен: same → same → no-op (как и в
    PATCH /tickets/{id}, чтобы при повторном вызове не получать 409).
    """
    old_status = ticket.status
    if old_status == new_status:
        return old_status
    allowed = ALLOWED_TRANSITIONS.get(old_status, frozenset())
    if new_status not in allowed:
        raise _raise_invalid(old_status, new_status, allowed)
    ticket.status = new_status
    return old_status


def transition_via_operator(ticket: Ticket, new_status: str) -> str:
    """Переход, инициированный оператором через PATCH /tickets/{id}.

    Узкое подмножество ALLOWED_TRANSITIONS: оператор не может через одну
    ручку и подтвердить черновик (это пользовательское действие), и
    переоткрыть закрытый тикет (это административное действие через
    feedback-flow).
    """
    old_status = ticket.status
    if old_status == new_status:
        return old_status
    allowed = ALLOWED_OPERATOR_TRANSITIONS.get(old_status, frozenset())
    if new_status not in allowed:
        raise _raise_invalid(old_status, new_status, allowed)
    ticket.status = new_status
    return old_status
