# Support Demo

## Start

Выполните одну команду из корневой директории репозитория:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Запускает:

- Ollama, если ещё не запущена
- Сервис ИИ по адресу `http://localhost:8001`
- бэкенд + Postgres в Docker
- сервер разработки фронтенда

## End

Из `C:\Code\support-demo`:

```powershell
cd C:\Code\support-demo
```

Остановить backend + Postgres:

```powershell
cd backend
docker compose down
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

Удалить ещё и данные Postgres, вместо `docker compose down`:

```powershell
docker compose down -v
```

`-v` удалит базу данных. Для обычного завершения - `docker compose down`.
