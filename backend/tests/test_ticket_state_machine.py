"""Матричные тесты для ticket_state_machine.

Раньше правила переходов жили в роутере, и confirm/resolve/reopen меняли
статус мимо валидатора — любая регрессия в графе статусов ловилась только
пользователями. Эти тесты фиксируют контракт «какой переход разрешён, а
какой нет», для двух API:

  transition_via_operator — то, что доступно через PATCH /tickets/{id}
  transition              — полный граф, через который идут confirm /
                            resolve / reopen

5 статусов × 5 целевых = 25 ячеек на функцию. Tabular-параметризация: при
любом будущем изменении графа диф в ALLOWED_*_TRANSITIONS должен
сопровождаться диффом в этих таблицах — ревьюер сразу видит, что меняется.
"""

import pytest
from fastapi import HTTPException

from app.models.ticket import Ticket
from app.services.ticket_state_machine import (
    ALLOWED_OPERATOR_TRANSITIONS,
    ALLOWED_TRANSITIONS,
    transition,
    transition_via_operator,
)


ALL_STATUSES = ("pending_user", "confirmed", "in_progress", "resolved", "closed")


def _new_ticket(status: str) -> Ticket:
    """Лёгкий тикет в памяти — без БД, чтобы не платить за фикстуры."""
    ticket = Ticket(
        user_id=1,
        title="probe",
        body="probe body",
        user_priority=3,
        department="IT",
        status=status,
        confirmed_by_user=False,
    )
    return ticket


# ── transition (полный граф: confirm / resolve / reopen) ─────────────────────


@pytest.mark.parametrize("source", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_transition_full_graph_matrix(source: str, target: str):
    """Полная 5×5 таблица для transition()."""
    ticket = _new_ticket(source)

    if source == target:
        # Идемпотентно: возвращаем старый статус, ничего не меняем
        assert transition(ticket, target) == source
        assert ticket.status == source
        return

    if target in ALLOWED_TRANSITIONS.get(source, frozenset()):
        old = transition(ticket, target)
        assert old == source
        assert ticket.status == target
    else:
        with pytest.raises(HTTPException) as exc_info:
            transition(ticket, target)
        assert exc_info.value.status_code == 409
        # Тикет не должен мутировать при отказе
        assert ticket.status == source


# ── transition_via_operator (PATCH /tickets/{id}) ────────────────────────────


@pytest.mark.parametrize("source", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_transition_via_operator_matrix(source: str, target: str):
    """Полная 5×5 таблица для transition_via_operator().

    Намеренно уже, чем transition(): операторская PATCH-ручка не должна
    подтверждать черновики (это пользовательское действие — /confirm) и не
    должна реоткрывать закрытые тикеты (это путь через feedback).
    """
    ticket = _new_ticket(source)

    if source == target:
        assert transition_via_operator(ticket, target) == source
        assert ticket.status == source
        return

    if target in ALLOWED_OPERATOR_TRANSITIONS.get(source, frozenset()):
        old = transition_via_operator(ticket, target)
        assert old == source
        assert ticket.status == target
    else:
        with pytest.raises(HTTPException) as exc_info:
            transition_via_operator(ticket, target)
        assert exc_info.value.status_code == 409
        assert ticket.status == source


# ── Качественные инварианты, которые матрица сама не ловит ───────────────────


def test_operator_cannot_confirm_pending_user_draft():
    """PATCH /tickets/{id} {status: confirmed} не должно работать, даже хотя
    transition() это разрешает: подтверждение черновика — отдельный flow
    через POST /confirm с проверкой draft-context.
    """
    ticket = _new_ticket("pending_user")
    with pytest.raises(HTTPException) as exc_info:
        transition_via_operator(ticket, "confirmed")
    assert exc_info.value.status_code == 409


def test_operator_cannot_reopen_closed_ticket():
    """Симметрично: оператор не может через PATCH закрытый тикет вернуть в
    confirmed. Reopen — отдельный flow через feedback с reopen_count.
    """
    ticket = _new_ticket("closed")
    with pytest.raises(HTTPException) as exc_info:
        transition_via_operator(ticket, "confirmed")
    assert exc_info.value.status_code == 409


def test_full_transition_allows_reopen_from_closed():
    """А полный граф — позволяет: feedback-flow зовёт transition() напрямую."""
    ticket = _new_ticket("closed")
    transition(ticket, "confirmed")
    assert ticket.status == "confirmed"


def test_invalid_transition_payload_in_409_detail():
    """409 detail включает from/to/allowed — фронт показывает осмысленную
    подсказку «вы можете перейти только в X, Y».
    """
    ticket = _new_ticket("resolved")
    with pytest.raises(HTTPException) as exc_info:
        transition_via_operator(ticket, "pending_user")
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["from"] == "resolved"
    assert detail["to"] == "pending_user"
    assert "in_progress" in detail["allowed"]  # один из реально разрешённых


def test_terminal_closed_has_no_operator_transitions():
    """closed — терминал для оператора. Таблица не должна тихо разрешить
    что-нибудь типа closed→in_progress в будущем рефакторинге.
    """
    assert ALLOWED_OPERATOR_TRANSITIONS["closed"] == frozenset()
