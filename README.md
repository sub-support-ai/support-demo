# Support Demo

## Start

Run one command from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

This starts:

- Ollama if it is not already running
- AI service on `http://localhost:8001`
- backend + Postgres in Docker
- frontend dev server
