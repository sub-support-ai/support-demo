"""Простейший in-memory rate limiter — скользящее окно на deque.

Зачем мы вообще лимитируем /auth:
  - /auth/login без лимита = брутфорс пароля. Злоумышленник может
    проверить 100'000 паролей в минуту. Даже bcrypt не спасёт, если
    цель — подобрать слабый пароль (1234, qwerty).
  - /auth/register без лимита = спам регистрациями. Один скрипт может
    за минуту создать 10'000 пользователей и забить базу.

Почему пишем сами, а не берём библиотеку:
  - Это ~40 строк. Читается за минуту, понятно КАК работает.
  - Внешняя библиотека (slowapi/limits) тянет middleware, декораторы,
    свои исключения — на учебном проекте это чёрный ящик.
  - Нам достаточно: "не больше N запросов в M секунд с одного IP
    на конкретный endpoint".

Ограничения этой реализации (сознательные):
  - In-memory → счётчики живут только в этом процессе. Если запустить
    несколько worker'ов uvicorn, каждый будет считать отдельно.
    Для self-hosted одного worker'а этого хватает; на больших нагрузках
    нужно общее хранилище — но это далёкое "потом".
  - Счётчики не чистятся автоматически. Если уникальных IP миллионы,
    dict вырастет. На практике для /auth это не проблема.
"""

from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status


# Глобальный реестр всех созданных счётчиков — нужен только для _reset()
# в тестах (чтобы один вызов чистил всё, а не помнить список вручную).
_all_counters: list[dict[str, deque[float]]] = []


def _client_ip(request: Request) -> str:
    """IP клиента для ключа лимитера.

    request.client.host — это IP того, кто подключился к нашему сокету.
    За прокси (nginx, CloudFlare) это будет IP прокси, а не реального
    пользователя — тогда надо читать X-Forwarded-For, но ТОЛЬКО если
    приложение действительно за доверенным прокси (иначе любой клиент
    подделает заголовок и обойдёт лимит). Для self-hosted без прокси
    достаточно request.client.host.
    """
    return request.client.host if request.client else "unknown"


def rate_limit(max_calls: int, window_seconds: int):
    """Фабрика FastAPI-dependency с собственным счётчиком.

    Пример:
        @router.post("/login", dependencies=[Depends(rate_limit(5, 60))])

    Почему у каждого endpoint'а свой dict, а не общий на модуль:
      Если бы счётчик был один — 3 регистрации + 2 логина с одного IP
      внезапно упирались бы в общий лимит. Изолируем: /login считает
      только свои попытки, /register — только свои.

    Почему фабрика, а не одна функция с параметрами:
      FastAPI-dependency должна быть callable без аргументов. Замыкание
      над max_calls/window_seconds и собственным hits-словарём —
      естественное решение.
    """
    hits: dict[str, deque[float]] = defaultdict(deque)
    _all_counters.append(hits)   # чтобы _reset() мог очистить и этот тоже

    def dependency(request: Request) -> None:
        key = _client_ip(request)
        now = monotonic()   # monotonic не прыгает при смене системного времени
        q = hits[key]

        # Выкидываем таймстампы, которые уже не в окне.
        # deque.popleft() — O(1), в отличие от list.pop(0).
        cutoff = now - window_seconds
        while q and q[0] < cutoff:
            q.popleft()

        # Если в окне уже накопилось max_calls запросов — отказываем.
        if len(q) >= max_calls:
            # Retry-After — стандартный заголовок, говорит клиенту,
            # через сколько секунд можно пробовать снова.
            retry_after = int(window_seconds - (now - q[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов. Попробуй позже.",
                headers={"Retry-After": str(retry_after)},
            )

        # Регистрируем этот запрос и пропускаем.
        q.append(now)

    return dependency


def _reset() -> None:
    """Очистить счётчики ВСЕХ созданных лимитеров. Используется в тестах,
    чтобы предыдущий тест не засорял лимит следующему."""
    for hits in _all_counters:
        hits.clear()
