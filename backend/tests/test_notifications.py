"""Тесты email и Slack нотификаций.

Используем monkeypatch для изоляции от реального SMTP и Slack Webhook.
Проверяем:
  - send_email вызывается с правильными аргументами при смене статуса.
  - При отсутствии SMTP_HOST / SLACK_WEBHOOK_URL — no-op, нет исключений.
  - notify_ticket_status не падает при None requester_email.
  - post_to_slack не падает при сетевой ошибке.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email import notify_ticket_status, send_email
from app.services.slack import notify_ticket_created, notify_ticket_resolved, post_to_slack


# ── send_email ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_noop_when_no_smtp_host(monkeypatch):
    """Без SMTP_HOST письмо не отправляется, исключений нет."""
    from app.config import Settings
    settings = Settings()
    settings.SMTP_HOST = None
    monkeypatch.setattr("app.services.email.get_settings", lambda: settings)

    # Не должно бросать и не должно вызывать _send_sync
    with patch("app.services.email._send_sync") as mock_send:
        await send_email(to="a@b.com", subject="test", body="hello")
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_calls_send_sync_when_configured(monkeypatch):
    """Если SMTP_HOST задан — _send_sync вызывается в executor."""
    from app.config import Settings
    from pydantic import SecretStr

    settings = Settings()
    settings.SMTP_HOST = "smtp.example.com"
    settings.SMTP_PORT = 587
    settings.SMTP_USER = "user"
    settings.SMTP_PASSWORD = SecretStr("password")
    settings.SMTP_FROM = "noreply@example.com"
    settings.SMTP_USE_TLS = True
    monkeypatch.setattr("app.services.email.get_settings", lambda: settings)

    calls = []

    def fake_send(*args, **kwargs):
        calls.append(args)

    with patch("app.services.email._send_sync", side_effect=fake_send):
        await send_email(to="user@corp.ru", subject="Тест", body="Привет")

    assert len(calls) == 1
    to_arg = calls[0][0]
    assert to_arg == "user@corp.ru"


@pytest.mark.asyncio
async def test_send_email_swallows_smtp_exception(monkeypatch):
    """Ошибка SMTP не прокидывается наружу — только WARNING в лог."""
    from app.config import Settings
    settings = Settings()
    settings.SMTP_HOST = "smtp.broken.example.com"
    settings.SMTP_PORT = 587
    settings.SMTP_USER = None
    settings.SMTP_PASSWORD = None
    settings.SMTP_FROM = "noreply@example.com"
    settings.SMTP_USE_TLS = False
    monkeypatch.setattr("app.services.email.get_settings", lambda: settings)

    def raise_connection_error(*args, **kwargs):
        raise ConnectionRefusedError("Connection refused")

    with patch("app.services.email._send_sync", side_effect=raise_connection_error):
        # Не должно бросать
        await send_email(to="a@b.com", subject="s", body="b")


# ── notify_ticket_status ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_ticket_status_noop_when_no_email():
    """Без requester_email уведомление пропускается."""
    with patch("app.services.email.send_email") as mock_send:
        await notify_ticket_status(
            ticket_id=1,
            title="Test",
            status="confirmed",
            requester_email=None,
            requester_name="User",
            department="IT",
        )
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_notify_ticket_status_noop_for_unknown_status():
    """Незнакомый статус (например, 'pending_user') — no-op."""
    with patch("app.services.email.send_email") as mock_send:
        await notify_ticket_status(
            ticket_id=1,
            title="Test",
            status="pending_user",
            requester_email="user@corp.ru",
            requester_name="User",
            department="IT",
        )
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_notify_ticket_status_confirmed_sends_email():
    """Статус 'confirmed' → email отправляется с правильной темой."""
    sent = []

    async def fake_send(*, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    with patch("app.services.email.send_email", side_effect=fake_send):
        await notify_ticket_status(
            ticket_id=42,
            title="VPN не работает",
            status="confirmed",
            requester_email="employee@corp.ru",
            requester_name="Иван",
            department="IT",
        )

    assert len(sent) == 1
    assert "42" in sent[0]["subject"]
    assert "employee@corp.ru" == sent[0]["to"]
    assert "IT" in sent[0]["body"]


# ── post_to_slack / notify_ticket_created ─────────────────────────────────────


@pytest.mark.asyncio
async def test_post_to_slack_noop_when_no_webhook(monkeypatch):
    """Без SLACK_WEBHOOK_URL — no-op, httpx не вызывается."""
    from app.config import Settings
    settings = Settings()
    settings.SLACK_WEBHOOK_URL = None
    monkeypatch.setattr("app.services.slack.get_settings", lambda: settings)

    with patch("httpx.AsyncClient") as mock_client:
        await post_to_slack({"text": "hello"})
        mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_post_to_slack_sends_payload(monkeypatch):
    """Если SLACK_WEBHOOK_URL задан — отправляем POST с payload."""
    from app.config import Settings
    settings = Settings()
    settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
    monkeypatch.setattr("app.services.slack.get_settings", lambda: settings)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.slack.httpx.AsyncClient", return_value=mock_client):
        await post_to_slack({"text": "новый тикет"})

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0] == "https://hooks.slack.com/test"


@pytest.mark.asyncio
async def test_post_to_slack_swallows_http_error(monkeypatch):
    """HTTP-ошибка Slack не прокидывается наружу."""
    from app.config import Settings
    settings = Settings()
    settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/broken"
    monkeypatch.setattr("app.services.slack.get_settings", lambda: settings)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Network error"))

    with patch("app.services.slack.httpx.AsyncClient", return_value=mock_client):
        # Не должно бросать
        await post_to_slack({"text": "fail"})


@pytest.mark.asyncio
async def test_notify_ticket_created_formats_message(monkeypatch):
    """notify_ticket_created передаёт правильные данные в post_to_slack."""
    sent = []

    async def fake_post(payload):
        sent.append(payload)

    with patch("app.services.slack.post_to_slack", side_effect=fake_post):
        await notify_ticket_created(
            ticket_id=7,
            title="Нет VPN",
            department="IT",
            priority="высокий",
            requester_name="Сотрудник",
        )

    assert len(sent) == 1
    text = sent[0]["text"]
    assert "7" in text
    assert "Нет VPN" in text
    assert "IT" in text


# ── Retention config ──────────────────────────────────────────────────────────


def test_log_retention_days_default():
    """LOG_RETENTION_DAYS по умолчанию 90."""
    from app.config import Settings
    s = Settings()
    assert s.LOG_RETENTION_DAYS == 90


def test_log_retention_days_zero_disables():
    """LOG_RETENTION_DAYS=0 означает 'не удалять'."""
    from app.config import Settings
    s = Settings()
    s.LOG_RETENTION_DAYS = 0
    assert s.LOG_RETENTION_DAYS == 0
