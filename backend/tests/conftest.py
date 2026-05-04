import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

# Отдельная база для тестов — не трогает рабочие данные.
# По умолчанию используем SQLite, чтобы тесты проходили "из коробки"
# без поднятого Postgres. При необходимости можно переопределить через env:
#   TEST_DATABASE_URL=postgresql+asyncpg://...  (например, в CI)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///./test.db",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# App imports must happen after DATABASE_URL is forced to the test database.
from app.database import Base, get_db
from app.main import app

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)
TestSessionLocal = async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Создаём все таблицы перед тестами, удаляем после.

    Намеренно НЕ используем alembic upgrade head — в тестах важна скорость
    (сотни запусков в день на CI). metadata.create_all создаёт схему за
    один SQL-батч, миграции прогоняли бы каждую revision последовательно.

    Целостность миграций для прода проверяется отдельно в CI — на пустом
    Postgres прогоняется `alembic upgrade head`; см. .github/workflows/ci.yml.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Каждый тест стартует с чистыми счётчиками лимитера.

    В обычной жизни tests/ делают десятки запросов с одного и того же
    фейкового IP (127.0.0.1) — без сброса пятый POST /auth/register
    получил бы 429, и каскад тестов развалился бы на ровном месте.

    Тест, который проверяет САМ лимит, делает reset ещё раз в начале,
    чтобы гарантированно стартовать с чистого листа.
    """
    from app.rate_limit import _reset
    _reset()
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Сессия с rollback после каждого теста — тесты изолированы."""
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    """HTTP-клиент с подменой get_db на тестовую сессию."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
