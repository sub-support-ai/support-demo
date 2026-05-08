# Развёртывание

Два compose-файла для двух режимов работы.

## docker-compose.dev.yml — локальная разработка

Запуск:

```bash
cd backend
docker compose -f docker-compose.dev.yml up
```

Что включено:
- `app` — bind-mount `.:/app`, uvicorn `--reload`, рестарт по изменениям кода
- `db` — Postgres с пробросом `5432:5432` (можно подключиться из IDE/psql)
- `ai-worker`, `sla-worker`, `knowledge-embedding-worker` — без рестарт-политики
- AI-сервис не запускается из этого файла; backend берёт `AI_SERVICE_URL=http://host.docker.internal:8001` и стучит на хост, где можно поднять `ai-service` отдельно

Что **не** включено:
- Healthcheck'и (для dev оверкилл — упало, поправил, перезапустил руками)
- Redis (по умолчанию `RATE_LIMIT_BACKEND=memory`, см. `app/rate_limit.py`)
- AI-service контейнер (запускается отдельно из `ai/ai-service/`)

## docker-compose.prod.yml — production

Запуск у заказчика:

```bash
cd backend
# 1. Подложить .env с секретами:
#    JWT_SECRET_KEY (длинная случайная строка, см. .env.example)
#    AI_SERVICE_API_KEY (обязателен при APP_ENV=production)
#    POSTGRES_PASSWORD (без него compose упадёт, см. ${POSTGRES_PASSWORD:?...})
#    APP_ENV=production
#    BOOTSTRAP_ADMIN_EMAIL=<email> — для регистрации первого админа
# 2. Заменить image-tag у ai-service на конкретный SHA из релиза
# 3. Запуск:
docker compose -f docker-compose.prod.yml up -d
```

### Что делает prod-compose кроме dev

| Что                                  | Зачем                                                                  |
|--------------------------------------|------------------------------------------------------------------------|
| `restart: unless-stopped` везде      | Рестарт после OOM-killer, рестарта хоста, неожиданного exit'а          |
| `healthcheck` на app/db/ai-service/redis | Воркеры стартуют, только когда зависимости подтвердили готовность   |
| `--workers 4` у uvicorn              | Распределение нагрузки на 4 процесса; rate-limiter общий через Redis   |
| `redis` сервис + `RATE_LIMIT_BACKEND=redis` | Лимит «5 попыток/мин» работает на N инстансов вместе, не на каждый отдельно |
| `appendonly yes` у Redis             | Счётчики переживают рестарт redis (иначе после restart'а брутфорс получает свежие 5 попыток) |
| Нет bind-mount исходников            | Код фиксируется на сборке, в runtime не меняется                       |
| Нет порта 5432 наружу                | БД доступна только сервисам внутри сети — внешний доступ через `docker exec` |
| `ai-service` развёрнут как сервис    | Mistral в соседнем контейнере, по требованию заказчика данные не покидают периметр |
| `ai_models` volume                   | Модель ~4 ГБ не пере-скачивается при каждом перезапуске контейнера     |

### Миграции при старте

В `command` у `app` сначала `alembic upgrade head`, затем `uvicorn`. Это значит:
- При деплое новой версии схема БД синхронизируется автоматически.
- Идемпотентно: если миграций нет, alembic ничего не делает.
- Rolling-restart безопасен: вторая реплика тоже сделает upgrade head, который no-op.

### Backup БД

Из compose сознательно убран — это решение деплой-инженера заказчика. Варианты:

```bash
# Cron на хосте (раз в час, в smb-share):
docker exec -t support-demo-db-1 pg_dump -U postgres app_db | gzip > /backup/db_$(date +%F_%H).sql.gz

# Или wal-g / pgbackrest для PITR — конфигурация выходит за рамки compose.
```

Главное условие — Postgres-контейнер живой и healthy, что обеспечивает healthcheck в этом файле.

### Fail-closed проверки на старте

Backend и ai-service оба отказываются стартовать при пустых критичных секретах в production:

- `app/config.py:__post_init_check__` → `JWT_SECRET_KEY`, `AI_SERVICE_API_KEY` обязательны при `APP_ENV=production`
- `ai/ai-service/main.py:_validate_startup_config()` → `AI_SERVICE_API_KEY` обязателен при `APP_ENV=production`

Это важно: при пустом ключе сервис тихо принимал бы любые запросы. Лучше упасть с понятным `RuntimeError`, чем открыть периметр.

### Smoke-тест после деплоя

```bash
# Backend здоровый
curl -f http://localhost:8000/healthcheck

# AI-сервис здоровый (внутри сети, через docker exec)
docker exec support-demo-app-1 curl -f http://ai-service:8001/healthcheck

# Регистрация bootstrap-админа (через email из .env BOOTSTRAP_ADMIN_EMAIL)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@acme.com","username":"admin","password":"<long secret>"}'
```

Если любой из этих шагов падает — смотреть `docker compose -f docker-compose.prod.yml logs <service>`.
