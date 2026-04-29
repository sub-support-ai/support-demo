"""
Инициализация Sentry — системы отслеживания ошибок.

Что делает Sentry:
- Автоматически ловит все необработанные исключения
- Присылает уведомление на почту/в Slack когда что-то сломалось
- Показывает stack trace, параметры запроса, какой пользователь был

Как подключить:
1. Зайди на https://sentry.io и зарегистрируйся (бесплатно)
2. Создай новый проект: Platform = Python, Framework = FastAPI
3. Скопируй DSN (выглядит как https://abc123@o123.ingest.sentry.io/456)
4. Добавь в .env файл строку: SENTRY_DSN=https://...твой ключ...

Если SENTRY_DSN не задан — Sentry просто не подключится, приложение работает обычно.
"""

import logging

logger = logging.getLogger(__name__)


def setup_sentry() -> None:
    """
    Вызывается один раз при старте приложения (в main.py).
    Если SENTRY_DSN не задан — ничего не делает.
    """
    from app.config import get_settings
    import os

    dsn = os.getenv("SENTRY_DSN", "")

    if not dsn:
        logger.info("Sentry DSN не задан — мониторинг ошибок отключён")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        settings = get_settings()

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.APP_ENV,  # "development" или "production"
            # Записывает 100% транзакций в dev, 10% в prod (не перегружает квоту)
            traces_sample_rate=1.0 if settings.APP_ENV != "production" else 0.1,
            integrations=[
                FastApiIntegration(),        # ловит ошибки в эндпоинтах
                SqlalchemyIntegration(),     # ловит ошибки БД
                LoggingIntegration(
                    level=logging.INFO,      # INFO и выше — в Sentry как breadcrumbs
                    event_level=logging.ERROR,  # ERROR и выше — как отдельные события
                ),
            ],
            # Не отправляем пароли и токены в Sentry
            send_default_pii=False,
        )

        logger.info("Sentry подключён", extra={"environment": settings.APP_ENV})

    except ImportError:
        logger.warning(
            "Пакет sentry-sdk не установлен. "
            "Добавь sentry-sdk[fastapi] в requirements.txt"
        )
