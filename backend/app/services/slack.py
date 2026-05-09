"""Slack-уведомления через Incoming Webhook.

Конфигурация: SLACK_WEBHOOK_URL в Settings (.env).
Если URL не задан — все функции no-op (Development-friendly).

Используется как второй канал уведомлений помимо email:
  - Агенты видят новые тикеты в Slack-канале отдела.
  - Пользователи могут видеть статус через @bot (будущая интеграция).
"""

import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Таймаут на POST к Slack webhook: не хотим подвешивать request-flow
# если Slack API лагает.
_SLACK_TIMEOUT_SECONDS = 5.0


async def post_to_slack(payload: dict) -> None:
    """Отправляет payload на SLACK_WEBHOOK_URL.

    При пустом URL или любой сетевой ошибке — WARNING в лог, не исключение.
    """
    webhook_url = get_settings().SLACK_WEBHOOK_URL

    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL не задан — уведомление пропущено")
        return

    try:
        async with httpx.AsyncClient(timeout=_SLACK_TIMEOUT_SECONDS) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.debug("Slack уведомление отправлено")
    except Exception:
        logger.warning("Не удалось отправить Slack-уведомление", exc_info=True)


# ── Готовые хелперы ───────────────────────────────────────────────────────────

_DEPT_EMOJI = {"IT": ":computer:", "HR": ":busts_in_silhouette:", "finance": ":moneybag:"}
_PRIORITY_EMOJI = {
    "критический": ":rotating_light:",
    "высокий": ":red_circle:",
    "средний": ":yellow_circle:",
    "низкий": ":white_circle:",
}


async def notify_ticket_created(
    *,
    ticket_id: int,
    title: str,
    department: str,
    priority: Optional[str],
    requester_name: Optional[str],
    sla_deadline: Optional[str] = None,
) -> None:
    """Уведомляет канал поддержки о новом подтверждённом тикете."""
    dept_emoji = _DEPT_EMOJI.get(department, ":ticket:")
    priority_emoji = _PRIORITY_EMOJI.get(priority or "средний", ":white_circle:")

    text = (
        f"{dept_emoji} *Новый запрос #{ticket_id}*\n"
        f"*Тема:* {title}\n"
        f"*Отдел:* {department}  {priority_emoji} *Приоритет:* {priority or 'средний'}\n"
        f"*Заявитель:* {requester_name or 'Сотрудник'}"
    )
    if sla_deadline:
        text += f"\n*SLA до:* {sla_deadline}"

    await post_to_slack({"text": text})


async def notify_ticket_resolved(
    *,
    ticket_id: int,
    title: str,
    department: str,
    agent_name: Optional[str] = None,
) -> None:
    """Уведомляет канал о закрытии тикета агентом."""
    dept_emoji = _DEPT_EMOJI.get(department, ":ticket:")
    agent_part = f" (агент: {agent_name})" if agent_name else ""
    text = (
        f":white_check_mark: {dept_emoji} *Запрос #{ticket_id} решён{agent_part}*\n"
        f"*Тема:* {title}"
    )
    await post_to_slack({"text": text})
