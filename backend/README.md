[![CI/CD](https://img.shields.io/badge/CI-passing-brightgreen?logo=githubactions)](Ссылка_на_ваш_экшен)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
# Support Tickets API

FastAPI‑сервис для обработки обращений пользователей (тикеты) с Postgres (в Docker) и асинхронным SQLAlchemy.

## Структура
```
app/
  routers/       HTTP endpoints
  models/        SQLAlchemy ORM
  schemas/       Pydantic DTOs
  services/      бизнес-логика (audit, rate_limit, …)
  main.py        app factory + middleware
alembic/         миграции БД
tests/           pytest
```

## Быстрый старт (Docker)

1) Создайте файл `.env` на основе примера:

```bash
copy .env.example .env
```

2) Поднимите Postgres и приложение:

```bash
docker compose up --build
```

После старта:
- `GET /healthcheck` → `{"status":"ok","database":"ok"}`
- Swagger UI: `http://localhost:8000/docs`

Миграции БД накатываются автоматически при старте контейнера
(`alembic upgrade head` в `docker-compose.yml`).

## Быстрый старт (локально на Windows)

Важно: у вас Python запускается через `py` (а `python` может быть не в PATH).

1) Установите зависимости:

```bash
py -m pip install -r requirements-dev.txt
```

2) Создайте `.env`:

```bash
copy .env.example .env
```

3) Запустите Postgres (рекомендуется через Docker):

```bash
docker compose up -d db
```

4) Накатите миграции БД:

```bash
py -m alembic upgrade head
```

5) Для демо наполните таблицу агентов, чтобы роутинг назначал тикеты:

```bash
py -m scripts.seed_demo_agents
```

Скрипт идемпотентный: повторный запуск обновит демо-агентов, а не создаст
дубликаты. Пароль задаётся через `DEMO_AGENT_PASSWORD`; если переменная не
задана, используется локальный демо-пароль `DemoPass123!`.

Для демонстрации шаблонов ответов и поиска по базе знаний также запустите:

```bash
py -m scripts.seed_response_templates
py -m scripts.seed_knowledge_articles
```

Для подготовки semantic/RAG индекса после запуска AI-service можно посчитать embeddings для чанков:

```bash
py -m scripts.backfill_knowledge_embeddings --batch-size 16
```

Скрипт обновляет `knowledge_chunks.embedding_model`, `embedding_updated_at`, `token_count`.
Если в Postgres установлен pgvector, он также заполнит `knowledge_chunks.embedding`.
Если pgvector не установлен, скрипт не ломает локальный запуск и оставляет full-text поиск рабочим.
Для регулярной переиндексации можно задать `KNOWLEDGE_REINDEX_INTERVAL_SECONDS`.
По умолчанию `0`, то есть периодический reindex выключен.

База знаний использует PostgreSQL full-text search в production:

- `knowledge_articles.search_vector` создаётся миграцией как generated `tsvector`;
- GIN-индекс ускоряет поиск по статьям;
- ранжирование сочетает `ts_rank_cd`, фильтры по контексту, свежесть статьи и feedback пользователей;
- в тестах на SQLite используется переносимый fallback без PostgreSQL-специфичных операторов.
- pgvector-миграция добавляет vector-колонки и HNSW-индексы только если расширение `vector` доступно в Postgres.

6) Запустите API:

```bash
py -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

7) В отдельном терминале запустите worker ответов:

```bash
py -m app.workers.ai_worker
```

Без worker чат сохранит сообщение и покажет обработку, но ответ не появится,
пока задача не будет обработана.

8) В отдельном терминале запустите SLA worker:

```bash
py -m app.workers.sla_worker
```

Он периодически проверяет просроченные подтверждённые запросы и эскалирует их старшему специалисту отдела.

9) Для фонового заполнения RAG embeddings запустите worker базы знаний:

```bash
py -m app.workers.knowledge_embedding_worker
```

Админский endpoint `POST /api/v1/knowledge/{article_id}/reindex` пересобирает `search_text` и чанки статьи, затем ставит задачу в `knowledge_embedding_jobs`. Worker забирает задачу, вызывает AI-service `/ai/embed` и заполняет metadata чанков. Если в Postgres доступен pgvector, также заполняется vector-колонка `knowledge_chunks.embedding`.

Для локального запуска рядом с AI-service обычно нужно переопределить:

```env
POSTGRES_HOST=localhost
AI_SERVICE_URL=http://localhost:8001
AI_SERVICE_API_KEY=
```

## Миграции БД (Alembic)

Схема БД версионируется через Alembic. Список возможных команд:

```bash
# Применить все миграции до актуальной версии (всегда безопасно, идемпотентно)
py -m alembic upgrade head

# Посмотреть текущую версию БД
py -m alembic current

# История миграций
py -m alembic history

# Создать новую миграцию после изменения моделей
# (Alembic сравнит модели с текущей БД и сгенерит diff)
py -m alembic revision --autogenerate -m "добавил поле X в таблицу Y"

# ВАЖНО: прочитать сгенерированную миграцию перед коммитом.
# autogenerate не распознаёт переименования (воспринимает как drop+add,
# что потеряет данные) и может упустить изменения типов.

# Откатить одну миграцию назад
py -m alembic downgrade -1
```

Файлы миграций живут в `alembic/versions/` и коммитятся в git.

### Существующая БД (апгрейд с v0.1 → v0.2)

Если БД уже была развёрнута до того, как появился Alembic — таблицы уже
существуют, и `alembic upgrade head` упадёт с "relation already exists".
Нужно единожды "приклеить" текущее состояние к baseline-миграции:

```bash
py -m alembic stamp head
```

Эта команда записывает в `alembic_version` что база "уже на актуальной
версии", не выполняя сам upgrade. После этого все последующие миграции
пойдут обычным порядком.

## Тесты

По умолчанию тесты используют SQLite (async) и не требуют Postgres:

```bash
py -m pytest -q
```

Если хотите прогонять тесты на Postgres, задайте переменную окружения `TEST_DATABASE_URL`:

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db
py -m pytest -q
```

## Переменные окружения

Смотрите `.env.example`:
- `POSTGRES_HOST=db` — для запуска в Docker Compose (приложение обращается к сервису `db`)
- `AI_SERVICE_URL` — адрес локального AI-сервиса (Mistral через Ollama/llama.cpp). По требованию заказчика данные не покидают периметр предприятия, облачные API не используются.
- `AI_SERVICE_API_KEY` — общий секрет между backend и AI-service. В локальной разработке можно оставить пустым; для staging/prod задавайте длинную случайную строку в обоих сервисах.
- `JWT_SECRET_KEY` — длинная случайная строка. Генерация: `python -c "import secrets; print(secrets.token_urlsafe(64))"`. В `APP_ENV=production` дефолт запрещён — приложение упадёт на старте.
- `CORS_ORIGINS` — список источников фронта через запятую. Пусто — CORS выключен.
- `BOOTSTRAP_ADMIN_EMAIL` — email первого админа (нужно один раз, потом убрать).

## Демо-сценарий API

Минимальный путь для интерактивного прототипа:

1. `POST /api/v1/auth/register` — зарегистрировать пользователя.
2. `POST /api/v1/conversations/` — создать диалог.
3. `POST /api/v1/conversations/{id}/messages` — отправить сообщение.
4. Если в ответе `requires_escalation=true`, вызвать
   `POST /api/v1/conversations/{id}/escalate`.
5. Показать пользователю созданный черновик тикета.
6. `PATCH /api/v1/tickets/{ticket_id}/confirm` — подтвердить отправку тикета
   в отдел.

