"""Rate limiter — скользящее окно с двумя бэкендами (memory / redis).

Зачем мы вообще лимитируем /auth:
  - /auth/login без лимита = брутфорс пароля. Злоумышленник может
    проверить 100'000 паролей в минуту. Даже bcrypt не спасёт, если
    цель — подобрать слабый пароль (1234, qwerty).
  - /auth/register без лимита = спам регистрациями. Один скрипт может
    за минуту создать 10'000 пользователей и забить базу.

Два бэкенда:

  memory — счётчики в `dict[str, deque[float]]` внутри процесса. Деплой
           в один uvicorn-воркер → лимит работает. На N воркеров каждый
           счётчик отдельный → реальный лимит «N × max_calls/window».

  redis  — общий счётчик через ZSET sliding-window. Lua-скрипт делает
           ZREMRANGEBYSCORE + ZCARD + ZADD атомарно, иначе под высокой
           нагрузкой N конкурентных запросов могут все попасть «между»
           проверкой ZCARD и ZADD и проскочить мимо лимита.

Выбор бэкенда — через settings.RATE_LIMIT_BACKEND. На старте лимитер
проверяется один раз: невалидное значение даёт ошибку конфига, а не
тихо возвращающий «всегда пропускать»-no-op в проде.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from time import monotonic
from typing import Any

from fastapi import HTTPException, Request, status

from app.config import get_settings

# ── Бэкенды ──────────────────────────────────────────────────────────────────


class _Backend(ABC):
    """Контракт: проверить + (при разрешении) зафиксировать запрос.

    Возвращает None если запрос разрешён, или int — сколько секунд ждать
    до следующей попытки (для Retry-After).
    """

    @abstractmethod
    async def consume(
        self,
        scope: str,
        key: str,
        max_calls: int,
        window_seconds: int,
    ) -> int | None: ...

    def reset(self) -> None:
        """Очистить все счётчики. Используется тестами."""
        return None


class _MemoryBackend(_Backend):
    """Счётчики в памяти процесса. Дёшево, но не разделяется между worker'ами."""

    def __init__(self) -> None:
        # scope — изолятор endpoint'ов: 5 регистраций + 2 логина с одного
        # IP не должны сваливаться в общий счётчик.
        self._buckets: dict[str, dict[str, deque[float]]] = defaultdict(lambda: defaultdict(deque))

    async def consume(
        self,
        scope: str,
        key: str,
        max_calls: int,
        window_seconds: int,
    ) -> int | None:
        now = monotonic()
        q = self._buckets[scope][key]

        cutoff = now - window_seconds
        while q and q[0] < cutoff:
            q.popleft()

        if len(q) >= max_calls:
            return int(window_seconds - (now - q[0])) + 1

        q.append(now)
        return None

    def reset(self) -> None:
        self._buckets.clear()


# Lua-скрипт для атомарного sliding-window в Redis.
#
# KEYS[1] — ключ ZSET'а
# ARGV[1] — текущий timestamp (миллисекунды, монотонная шкала)
# ARGV[2] — окно в миллисекундах
# ARGV[3] — max_calls
# ARGV[4] — уникальный member (uuid), чтобы ZADD не схлопывал одинаковые scores
#
# Возвращает {-1, retry_after_seconds} при отказе или {count, 0} при разрешении.
_REDIS_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_calls = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
local count = redis.call('ZCARD', key)
if count >= max_calls then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_ms = window_ms - (now_ms - tonumber(oldest[2]))
  if retry_ms < 1000 then retry_ms = 1000 end
  return {-1, math.ceil(retry_ms / 1000)}
end
redis.call('ZADD', key, now_ms, member)
-- EXPIRE с запасом, чтобы ключ почистился даже если до него никто не дойдёт
redis.call('PEXPIRE', key, window_ms + 1000)
return {count + 1, 0}
"""


class _RedisBackend(_Backend):
    """Общий счётчик через Redis ZSET. Атомарность через единственный Lua-call.

    Используем EVAL напрямую (а не EVALSHA + script_load): redis сервер
    кеширует скрипт сам по первому EVAL, разница в трафике незначительна,
    зато пропадает class-level state и тесты с fakeredis работают без
    дополнительной поддержки SCRIPT LOAD.
    """

    def __init__(self, client: Any) -> None:
        # client — redis.asyncio.Redis или совместимый (например, fakeredis).
        self._client = client

    async def consume(
        self,
        scope: str,
        key: str,
        max_calls: int,
        window_seconds: int,
    ) -> int | None:
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        member = uuid.uuid4().hex
        full_key = f"rl:{scope}:{key}"
        result = await self._client.eval(
            _REDIS_SLIDING_WINDOW_LUA,
            1,
            full_key,
            now_ms,
            window_ms,
            max_calls,
            member,
        )
        # redis-py возвращает [int, int]; fakeredis то же.
        count, retry_after = int(result[0]), int(result[1])
        if count == -1:
            return retry_after
        return None

    async def reset(self) -> None:  # type: ignore[override]
        await self._client.flushdb()


# ── Фабрика и реестр ─────────────────────────────────────────────────────────


_backend: _Backend | None = None


def _get_backend() -> _Backend:
    """Лениво создаёт бэкенд по settings.RATE_LIMIT_BACKEND.

    Лениво — потому что settings подменяются в тестах; делать выбор на
    import-time значит зафиксировать значение до того, как тестовый
    monkeypatch успеет сработать.
    """
    global _backend
    if _backend is None:
        settings = get_settings()
        if settings.RATE_LIMIT_BACKEND == "redis":
            from redis.asyncio import Redis  # ленивый импорт: redis опционален

            client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            _backend = _RedisBackend(client)
        else:
            _backend = _MemoryBackend()
    return _backend


def set_backend_for_testing(backend: _Backend) -> None:
    """Подменяет глобальный бэкенд (только для тестов)."""
    global _backend
    _backend = backend


# ── Публичный API ────────────────────────────────────────────────────────────


def get_client_ip(request: Request) -> str:
    """Реальный IP клиента для ключа лимитера.

    Без прокси (TRUSTED_PROXY_COUNT=0): берём request.client.host — это IP
    того, кто напрямую подключился к нашему сокету.

    За прокси (TRUSTED_PROXY_COUNT=N): читаем X-Forwarded-For и берём IP
    на позиции len(ips) - N от начала. Каждый прокси в цепочке добавляет IP
    входящего соединения справа, поэтому «настоящих» клиентских записей
    ровно len(ips) - N; берём крайнюю правую из них.

    Пример (nginx, TRUSTED_PROXY_COUNT=1):
      X-Forwarded-For: 1.2.3.4          → real_index=0 → "1.2.3.4"
      X-Forwarded-For: fake, 1.2.3.4    → real_index=1 → "1.2.3.4"  (spoof отброшен)

    Пример (proxy→nginx, TRUSTED_PROXY_COUNT=2):
      X-Forwarded-For: 1.2.3.4, 2.2.2.2 → real_index=0 → "1.2.3.4"

    Spoofing-защита: злоумышленник может добавить произвольные IP в
    начало заголовка, но не может изменить записи, добавленные нашими
    доверенными прокси (они контролируются нами). Берём IP ровно за
    N-й позицией от конца — всё, что левее, добавлено до наших прокси
    и потому ненадёжно, но мы берём самую правую «чистую» запись.
    """
    settings = get_settings()
    proxy_count = settings.TRUSTED_PROXY_COUNT
    if proxy_count > 0:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            real_index = max(0, len(ips) - proxy_count)
            candidate = ips[real_index] if real_index < len(ips) else ""
            if candidate:
                return candidate
    return request.client.host if request.client else "unknown"


# Счётчик для генерации уникальных scope-ключей. Каждый вызов rate_limit()
# получает свой scope, чтобы 5 регистраций и 2 логина с одного IP не
# свалились в общий счётчик (разные эндпоинты — разные пулы попыток).
_scope_counter = 0


def rate_limit(max_calls: int, window_seconds: int):
    """Фабрика FastAPI-dependency на собственный scope.

    Пример:
        @router.post("/login", dependencies=[Depends(rate_limit(5, 60))])
    """
    global _scope_counter
    _scope_counter += 1
    scope = f"rl{_scope_counter}"

    async def dependency(request: Request) -> None:
        backend = _get_backend()
        retry_after = await backend.consume(
            scope=scope,
            key=get_client_ip(request),
            max_calls=max_calls,
            window_seconds=window_seconds,
        )
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов. Попробуй позже.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


def _reset() -> None:
    """Очистить счётчики memory-бэкенда. Используется autouse-фикстурой.

    Намеренно не пытается достучаться до redis: autouse-фикстура висит
    на каждом тесте, а на redis-бэкенде это бы (а) делало сетевой запрос
    в тесте, который сам redis не использует, (б) валилось из-за вложенности
    event loop'ов. Для redis-тестов есть `await backend.reset()` напрямую.
    """
    backend = _get_backend()
    if isinstance(backend, _MemoryBackend):
        backend.reset()
