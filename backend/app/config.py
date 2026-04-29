from functools import lru_cache
from dotenv import load_dotenv
import os

load_dotenv()

# Маркер дефолтного небезопасного JWT_SECRET_KEY. В production запрещён —
# разворачиваем self-hosted у клиента, и дефолтный ключ = полная потеря
# безопасности токенов.
_DEFAULT_JWT_SECRET = "supersecretkey_change_in_production"


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", 8000))

    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "app_db")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")

    AI_SERVICE_URL: str = os.getenv("AI_SERVICE_URL", "http://ai-service:8001")
    # Версия модели по умолчанию — fallback для AILog.model_version, когда
    # AI Service по какой-то причине не вернул это поле. Раньше использовался
    # литерал "unknown", но он отравлял датасет для дообучения: разные версии
    # модели сваливались в одну "unknown"-корзину, и метрики по версиям ломались.
    # Теперь fallback — это конкретная строка из .env, которая обновляется
    # вместе с деплоем (например, "mistral-7b-instruct-q4_K_M-2026-04").
    AI_MODEL_VERSION_FALLBACK: str = os.getenv(
        "AI_MODEL_VERSION_FALLBACK", "mistral-unspecified"
    )

    # Секретный ключ для подписи JWT токенов
    # В продакшне — длинная случайная строка, хранится в .env
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", _DEFAULT_JWT_SECRET)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", 60))

    # Bootstrap-администратор: если email пользователя, который регистрируется
    # через POST /auth/register, совпадает с этим значением — он получает
    # role="admin" автоматически. Решает задачу "кто создаст первого админа":
    # в .env клиента указываем BOOTSTRAP_ADMIN_EMAIL=admin@acme.com, клиент
    # регистрируется сам, и в базе появляется первый админ.
    #
    # Сравнение case-insensitive (email'ы нечувствительны к регистру).
    # Если переменная не задана — bootstrap отключён, все регистрируются
    # как обычные пользователи.
    BOOTSTRAP_ADMIN_EMAIL: str | None = os.getenv("BOOTSTRAP_ADMIN_EMAIL") or None

    # CORS: список origins через запятую, откуда браузер может стучаться.
    # Пример: "http://localhost:3000,https://support.acme.com"
    # Не используй "*" — это отключает credentials и открывает API всему интернету.
    # Если переменная пустая — CORS выключен (полезно для чисто server-to-server
    # сценариев без браузерного фронта).
    CORS_ORIGINS_RAW: str = os.getenv("CORS_ORIGINS", "")

    @property
    def CORS_ORIGINS(self) -> list[str]:
        """Парсит CORS_ORIGINS из .env в список строк.

        Пустая строка → пустой список (CORS выключен).
        Пробелы вокруг origin'ов обрезаются.
        """
        raw = self.CORS_ORIGINS_RAW.strip()
        if not raw:
            return []
        return [o.strip() for o in raw.split(",") if o.strip()]

    def __post_init_check__(self) -> None:
        # При self-hosted развёртывании у клиента (слайд 6 презентации)
        # дефолтный ключ недопустим — любой с доступом к репозиторию
        # сможет выпускать валидные токены.
        if self.APP_ENV == "production" and self.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET:
            raise RuntimeError(
                "JWT_SECRET_KEY не задан в .env при APP_ENV=production. "
                "Сгенерируй длинную случайную строку и положи в переменные окружения."
            )

    @property
    def DATABASE_URL(self) -> str:
        # Прямой override через DATABASE_URL имеет приоритет — пригождается:
        #   - в тестах (sqlite+aiosqlite)
        #   - в Alembic-миграциях против тестовой БД
        #   - в staging-окружении, где URL может быть внешним (RDS, Supabase)
        override = os.getenv("DATABASE_URL")
        if override:
            return override

        # Иначе собираем из POSTGRES_* переменных — штатный путь для docker-compose.
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.__post_init_check__()
    return s
