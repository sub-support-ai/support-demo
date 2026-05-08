from functools import lru_cache
from dotenv import load_dotenv
import os

load_dotenv()

# Маркер дефолтного небезопасного JWT_SECRET_KEY. В production запрещён —
# разворачиваем self-hosted у клиента, и дефолтный ключ = полная потеря
# безопасности токенов.
_DEFAULT_JWT_SECRET = "supersecretkey_change_in_production"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


class Settings:
    def __init__(self) -> None:
        self.APP_ENV = os.getenv("APP_ENV", "development")
        self.APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
        self.APP_PORT = _env_int("APP_PORT", 8000)
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "app_db")
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
        self.AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
        self.AI_SERVICE_API_KEY = os.getenv("AI_SERVICE_API_KEY") or None
        self.AI_SERVICE_TIMEOUT_SECONDS = _env_float(
            "AI_SERVICE_TIMEOUT_SECONDS", 180.0
        )
        self.AI_MODEL_VERSION_FALLBACK = os.getenv(
            "AI_MODEL_VERSION_FALLBACK", "mistral-unspecified"
        )
        self.KNOWLEDGE_SEMANTIC_SEARCH_ENABLED = (
            os.getenv("KNOWLEDGE_SEMANTIC_SEARCH_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.KNOWLEDGE_EMBEDDING_DIMENSION = _env_int(
            "KNOWLEDGE_EMBEDDING_DIMENSION", 768
        )
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_JWT_SECRET)
        self.JWT_EXPIRE_MINUTES = _env_int("JWT_EXPIRE_MINUTES", 60)
        self.BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL") or None
        self.CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "")
        self.AI_WORKER_STALE_RUNNING_SECONDS = _env_int(
            "AI_WORKER_STALE_RUNNING_SECONDS", 600
        )
        self.KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS = _env_int(
            "KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS", 900
        )
        # ── RAG-пороги ─────────────────────────────────────────────────────
        # Скор у нас вычисляется в _score_article (text_score + context +
        # freshness + feedback) и сильно зависит от: размера KB, длины
        # запросов, веса ts_rank_cd / cosine. На каждом клиенте распределение
        # будет своё, поэтому пороги — конфиг, а не релиз.
        self.RAG_SCORE_HIGH_THRESHOLD = _env_float("RAG_SCORE_HIGH_THRESHOLD", 8.0)
        self.RAG_SCORE_MEDIUM_THRESHOLD = _env_float("RAG_SCORE_MEDIUM_THRESHOLD", 4.0)
        # Под этим порогом confidence — «красная зона»: даже если AI не
        # просил эскалацию, мы её принудительно поднимаем (видим в чате
        # кнопку «Создать тикет»).
        self.RAG_CONFIDENCE_RED_ZONE = _env_float("RAG_CONFIDENCE_RED_ZONE", 0.6)
        # ── Rate-limiter ───────────────────────────────────────────────────
        # memory  — счётчики в памяти процесса, по uvicorn-воркеру свои.
        #           Подходит для self-hosted с одним worker'ом и demo.
        # redis   — общий счётчик через ZSET-sliding-window на REDIS_URL.
        #           Нужен, когда backend крутится в нескольких pod'ах:
        #           иначе лимит «5/мин» превращается в «5 × N pod'ов».
        self.RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    APP_ENV: str
    APP_HOST: str
    APP_PORT: int

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str

    AI_SERVICE_URL: str
    AI_SERVICE_API_KEY: str | None
    AI_SERVICE_TIMEOUT_SECONDS: float
    # Версия модели по умолчанию — fallback для AILog.model_version, когда
    # AI Service по какой-то причине не вернул это поле. Раньше использовался
    # литерал "unknown", но он отравлял датасет для дообучения: разные версии
    # модели сваливались в одну "unknown"-корзину, и метрики по версиям ломались.
    # Теперь fallback — это конкретная строка из .env, которая обновляется
    # вместе с деплоем (например, "mistral-7b-instruct-q4_K_M-2026-04").
    AI_MODEL_VERSION_FALLBACK: str
    KNOWLEDGE_SEMANTIC_SEARCH_ENABLED: bool
    KNOWLEDGE_EMBEDDING_DIMENSION: int

    # Секретный ключ для подписи JWT токенов
    # В продакшне — длинная случайная строка, хранится в .env
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int

    # Bootstrap-администратор: если email пользователя, который регистрируется
    # через POST /auth/register, совпадает с этим значением — он получает
    # role="admin" автоматически. Решает задачу "кто создаст первого админа":
    # в .env клиента указываем BOOTSTRAP_ADMIN_EMAIL=admin@acme.com, клиент
    # регистрируется сам, и в базе появляется первый админ.
    #
    # Сравнение case-insensitive (email'ы нечувствительны к регистру).
    # Если переменная не задана — bootstrap отключён, все регистрируются
    # как обычные пользователи.
    BOOTSTRAP_ADMIN_EMAIL: str | None

    # CORS: список origins через запятую, откуда браузер может стучаться.
    # Пример: "http://localhost:3000,https://support.acme.com"
    # Не используй "*" — это отключает credentials и открывает API всему интернету.
    # Если переменная пустая — CORS выключен (полезно для чисто server-to-server
    # сценариев без браузерного фронта).
    CORS_ORIGINS_RAW: str

    # Через сколько секунд running-задача считается зависшей. Используется
    # одновременно воркером (для авто-перевешивания в очередь) и API
    # (для is_stale-флага в ответе /jobs). Значение должно быть единым,
    # иначе UI и воркер начнут расходиться: оператор увидит "зависла"
    # на здоровой задаче или, наоборот, не увидит на реально зависшей.
    AI_WORKER_STALE_RUNNING_SECONDS: int
    KNOWLEDGE_EMBEDDING_WORKER_STALE_RUNNING_SECONDS: int

    # Пороги отсечения для RAG: «answer» / «clarify» / «escalate».
    RAG_SCORE_HIGH_THRESHOLD: float
    RAG_SCORE_MEDIUM_THRESHOLD: float
    RAG_CONFIDENCE_RED_ZONE: float

    # Бэкенд для rate-limiter и адрес Redis, если выбран redis-бэкенд.
    RATE_LIMIT_BACKEND: str
    REDIS_URL: str

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
        # Симметрично с ai-service: без AI_SERVICE_API_KEY бэкенд ходит
        # в AI без заголовка X-AI-Service-Key, и AI-сервис в production
        # тоже не стартует без ключа. Если переменная пуста на стороне
        # бэкенда — связка backend↔ai-service гарантированно сломана,
        # лучше упасть на старте, чем на первом обращении к /ai/answer.
        if self.APP_ENV == "production" and not self.AI_SERVICE_API_KEY:
            raise RuntimeError(
                "AI_SERVICE_API_KEY не задан при APP_ENV=production. "
                "Без него запросы к AI-сервису не аутентифицируются и будут отклонены."
            )
        # RAG-пороги: ловим перепутанные значения СРАЗУ (на старте), а не на
        # первом запросе в чат. Иначе при опечатке HIGH=4, MEDIUM=8 эскалация
        # начнёт срабатывать там, где должен быть answer — и наоборот.
        if self.RAG_SCORE_HIGH_THRESHOLD <= 0 or self.RAG_SCORE_MEDIUM_THRESHOLD <= 0:
            raise RuntimeError(
                "RAG_SCORE_HIGH_THRESHOLD и RAG_SCORE_MEDIUM_THRESHOLD должны быть > 0."
            )
        if self.RAG_SCORE_MEDIUM_THRESHOLD > self.RAG_SCORE_HIGH_THRESHOLD:
            raise RuntimeError(
                f"RAG_SCORE_MEDIUM_THRESHOLD ({self.RAG_SCORE_MEDIUM_THRESHOLD}) "
                f"не может быть больше RAG_SCORE_HIGH_THRESHOLD ({self.RAG_SCORE_HIGH_THRESHOLD}). "
                "Иначе ответы из KB будут отдавать «answer», когда уверенности нет."
            )
        if not 0.0 <= self.RAG_CONFIDENCE_RED_ZONE <= 1.0:
            raise RuntimeError(
                f"RAG_CONFIDENCE_RED_ZONE ({self.RAG_CONFIDENCE_RED_ZONE}) должен быть в [0, 1]: "
                "это порог по confidence модели, который сам нормирован в этом диапазоне."
            )
        # Опечатка в RATE_LIMIT_BACKEND молча уронит лимит в no-op (фабрика
        # бы не нашла нужный класс) — а это означает открытый /auth/login
        # для брутфорса. Требуем явное значение из whitelist.
        if self.RATE_LIMIT_BACKEND not in {"memory", "redis"}:
            raise RuntimeError(
                f"RATE_LIMIT_BACKEND={self.RATE_LIMIT_BACKEND!r} не поддерживается. "
                "Допустимы 'memory' и 'redis'."
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
