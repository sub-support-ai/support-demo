"""Отправка email-уведомлений через SMTP.

Конфигурация читается из Settings (SMTP_HOST / SMTP_PORT / SMTP_USER /
SMTP_PASSWORD / SMTP_FROM). Если SMTP_HOST не задан — отправка молча
пропускается (no-op): это позволяет держать notifications-код включённым
в development без поднятого SMTP-сервера.

Используется для:
  - Уведомления пользователя о смене статуса тикета (confirmed → in_progress
    → resolved → closed).
  - Уведомления агента о назначении нового тикета (опционально).
"""

import asyncio
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def _build_message(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
) -> MIMEText:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    return msg


def _send_sync(
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: Optional[str],
    smtp_password: Optional[str],
    from_addr: str,
    use_tls: bool,
) -> None:
    """Синхронная отправка. Запускается в thread-pool из async-обёртки."""
    msg = _build_message(to, subject, body, from_addr)
    context = ssl.create_default_context() if use_tls else None

    if use_tls and smtp_port == 465:
        # SMTPS (SSL с самого начала)
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as smtp:
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(from_addr, [to], msg.as_string())
    else:
        # STARTTLS или plain (для dev/внутренних relay)
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            if use_tls:
                smtp.starttls(context=context)
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(from_addr, [to], msg.as_string())


async def send_email(
    to: str,
    subject: str,
    body: str,
) -> None:
    """Отправляет письмо получателю *to* с темой *subject* и текстом *body*.

    Конфигурация берётся из Settings. При пустом SMTP_HOST или любой ошибке
    пишем WARNING в лог — не поднимаем исключение, чтобы ошибка почты не
    прерывала основной request-flow.
    """
    settings = get_settings()

    if not settings.SMTP_HOST:
        logger.debug("SMTP_HOST не задан — email не отправляется (to=%s)", to)
        return

    smtp_password = (
        settings.SMTP_PASSWORD.get_secret_value()
        if settings.SMTP_PASSWORD else None
    )

    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            _send_sync,
            to,
            subject,
            body,
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_USER,
            smtp_password,
            settings.SMTP_FROM,
            settings.SMTP_USE_TLS,
        )
        logger.info("Email отправлен", extra={"to": to, "subject": subject})
    except Exception:
        logger.warning(
            "Не удалось отправить email",
            extra={"to": to, "subject": subject},
            exc_info=True,
        )


# ── Шаблоны уведомлений ───────────────────────────────────────────────────────

_STATUS_SUBJECTS = {
    "confirmed": "Ваш запрос #{ticket_id} принят в работу",
    "in_progress": "Запрос #{ticket_id} взят агентом в работу",
    "resolved": "Запрос #{ticket_id} решён — требуется ваша оценка",
    "closed": "Запрос #{ticket_id} закрыт",
}

_STATUS_BODIES = {
    "confirmed": (
        "Здравствуйте, {name}!\n\n"
        "Ваш запрос «{title}» (#{ticket_id}) принят и направлен в отдел {department}.\n"
        "Ожидаемый срок решения: {sla_deadline}.\n\n"
        "С уважением,\nСлужба поддержки"
    ),
    "in_progress": (
        "Здравствуйте, {name}!\n\n"
        "Агент приступил к обработке вашего запроса «{title}» (#{ticket_id}).\n"
        "Мы уведомим вас о результате.\n\n"
        "С уважением,\nСлужба поддержки"
    ),
    "resolved": (
        "Здравствуйте, {name}!\n\n"
        "Ваш запрос «{title}» (#{ticket_id}) отмечен как решённый.\n"
        "Если проблема не устранена, вы можете открыть его повторно в системе.\n\n"
        "С уважением,\nСлужба поддержки"
    ),
    "closed": (
        "Здравствуйте, {name}!\n\n"
        "Запрос «{title}» (#{ticket_id}) закрыт.\n"
        "Спасибо за обращение!\n\n"
        "С уважением,\nСлужба поддержки"
    ),
}


<<<<<<< HEAD
=======
async def notify_agent_assigned(
    *,
    ticket_id: int,
    title: str,
    department: str,
    requester_name: Optional[str],
    agent_email: str,
    agent_name: Optional[str],
) -> None:
    """Уведомляет агента о назначении нового тикета."""
    subject = f"Вам назначен запрос #{ticket_id}"
    body = (
        f"Здравствуйте, {agent_name or 'агент'}!\n\n"
        f"Вам назначен новый запрос в отдел {department}:\n"
        f"  Тема: {title}\n"
        f"  Заявитель: {requester_name or 'Сотрудник'}\n\n"
        f"Войдите в систему, чтобы ознакомиться с деталями.\n\n"
        f"С уважением,\nСлужба поддержки"
    )
    await send_email(to=agent_email, subject=subject, body=body)


>>>>>>> 381505c1ad1a211574bae4e0656e1003860877d3
async def notify_ticket_status(
    *,
    ticket_id: int,
    title: str,
    status: str,
    requester_email: Optional[str],
    requester_name: Optional[str],
    department: str,
    sla_deadline: Optional[str] = None,
) -> None:
    """Отправляет уведомление заявителю о смене статуса тикета.

    Если статус не входит в *_STATUS_SUBJECTS* или email не задан — no-op.
    """
    if not requester_email or status not in _STATUS_SUBJECTS:
        return

    subject = _STATUS_SUBJECTS[status].format(ticket_id=ticket_id)
    body = _STATUS_BODIES[status].format(
        name=requester_name or "Сотрудник",
        title=title,
        ticket_id=ticket_id,
        department=department,
        sla_deadline=sla_deadline or "уточняется",
    )
    await send_email(to=requester_email, subject=subject, body=body)
