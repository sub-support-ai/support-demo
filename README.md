# Support Demo

# Точка поддержки

AI-сервис для автоматизации внутренних обращений сотрудников в службу поддержки.

## Возможности

- чат сотрудника с AI-ассистентом;
- поиск по базе знаний;
- автоматическая классификация обращений;
- создание тикета при неуверенности AI;
- маршрутизация по отделам;
- локальный запуск LLM через Ollama;
- self-hosted архитектура.

## Архитектура

Frontend: React + Vite + Mantine  
Backend: FastAPI + PostgreSQL + SQLAlchemy + Alembic  
AI-service: FastAPI + Ollama + Mistral + nomic-embed-text  
RAG: база знаний + full-text search + semantic search через embeddings

## Предусловия

Перед первым запуском должны быть установлены:

- **Docker Desktop** — для backend + Postgres ([download](https://www.docker.com/products/docker-desktop/))
- **Ollama** — локальный LLM-runtime ([download](https://ollama.com/download)).
  После установки выполните один раз:
  ```powershell
  ollama pull mistral
  ollama pull nomic-embed-text
  ```
- **Python 3.12** — для AI-сервиса ([download](https://www.python.org/downloads/))
- **Node.js 18+** — для фронта ([download](https://nodejs.org/))

`start.ps1` сам проверит, что Docker / Python / Node на месте, и подскажет
ссылку на установку, если чего-то не хватает.

## Start

Выполните одну команду из корневой директории репозитория:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```


Что происходит при первом запуске:

- Создаётся `ai/ai-service/.venv` с зависимостями (~1-2 мин).
- Создаётся `backend/.env` из `.env.example` (для prod-развёртывания значения
  в нём надо подправить — см. `backend/docs/deployment.md`).
- `npm install` поднимает `node_modules` фронта.
- Поднимается Ollama (если ещё не запущена).
- Поднимается AI-сервис на `http://localhost:8001`.
- Поднимается backend + Postgres в Docker (`docker-compose.dev.yml`).
- Поднимается dev-сервер фронта на `http://localhost:5173`.

Backend и frontend открываются в отдельных окнах PowerShell — в них видны
логи, и закрывать их можно по отдельности.

## End

Из `C:\Code\support-demo`:

```powershell
cd C:\Code\support-demo
```

Остановить backend + Postgres:

```powershell
cd backend
docker compose -f docker-compose.dev.yml down
```

Остановить frontend и AI service, если они запущены из `start.ps1`:

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess -Force
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8001).OwningProcess -Force
```

Остановить Ollama:

```powershell
Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force
```

Проверить, что порты свободны:

```powershell
netstat -ano | findstr ":8000 :8001 :5173 :5432"
```

Удалить ещё и данные Postgres, вместо обычного `down`:

```powershell
docker compose -f docker-compose.dev.yml down -v
```

`-v` удалит volume с базой. Для обычного завершения — без `-v`.
