"""
Сервис роутинга тикетов.

Что делает этот файл:
  assign_agent()       — находит подходящего агента для тикета.
  unassign_agent()     — освобождает агента когда тикет закрывается.

Логика выбора агента:
  1. Смотрим на отдел тикета (IT / HR / finance).
  2. Если приоритет "критический" — сразу к самому опытному агенту
     (эскалация со слайда 7, п.5 презентации). Не ждём, когда свободный
     возьмёт в работу — критические обращения закрываем в первую очередь.
  3. Иначе если AI уверен на >= 0.8 — берём самого свободного агента
     (у кого меньше всего активных тикетов).
  4. Иначе (AI уверен < 0.8) — берём САМОГО ОПЫТНОГО агента
     (у кого наивысший ai_routing_score), чтобы старший проверил.

Почему отдельный сервис, а не прямо в роутере:
  Логику можно переиспользовать из разных мест (роутер тикетов,
  роутер conversations), и её удобно тестировать изолированно.
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.ticket import Ticket


async def assign_agent(
    db: AsyncSession,
    ticket: Ticket,
) -> Agent | None:
    """
    Назначает агента на тикет и увеличивает его счётчик.

    Возвращает агента если нашёл, None если в отделе нет активных агентов.

    Алгоритм:
      - ai_priority == "критический" → самый опытный (эскалация)
      - ai_confidence >= 0.8          → самый свободный (минимум active_ticket_count)
      - ai_confidence < 0.8           → самый опытный (максимум ai_routing_score)
    """
    confidence = ticket.ai_confidence or 0.0
    department = ticket.department
    is_critical = (ticket.ai_priority or "").strip().lower() == "критический"

    base_query = (
        select(Agent)
        .where(Agent.department == department)
        .where(Agent.is_active == True)
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    if is_critical or confidence < 0.8:
        # Критический приоритет или низкая уверенность → к старшему агенту
        query = base_query.order_by(Agent.ai_routing_score.desc())
    else:
        # Уверенный AI на обычном приоритете → самый свободный агент
        query = base_query.order_by(Agent.active_ticket_count.asc())

    result = await db.execute(query)
    agent = result.scalar_one_or_none()

    if agent:
        agent.active_ticket_count += 1
        ticket.agent_id = agent.id

    return agent


async def unassign_agent(
    db: AsyncSession,
    ticket: Ticket,
) -> None:
    """
    Вызывается когда тикет закрывается (resolved / closed).
    Уменьшает счётчик активных тикетов агента на 1.
    """
    if not ticket.agent_id:
        return

    await db.execute(
        update(Agent)
        .where(Agent.id == ticket.agent_id)
        .where(Agent.active_ticket_count > 0)
        .values(active_ticket_count=Agent.active_ticket_count - 1)
    )
