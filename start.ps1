# Одно-кликовый запуск всего стека support-demo для локальной разработки.
#
# Что поднимает (в этом порядке):
#   1. Ollama (если не запущен) + AI-сервис на :8001
#   2. Backend (Postgres + uvicorn + воркеры) через docker-compose.dev.yml
#   3. Frontend (vite dev-server) на :5173
#
# Запуск:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# Предусловия (см. README → «Локальный запуск»):
#   - Docker Desktop запущен
#   - Ollama установлен (https://ollama.com/download)
#   - Python 3.12 в PATH (или через `py` launcher)
#   - Node.js 18+ в PATH
#
# При первом запуске:
#   - Создастся ai/ai-service/.venv с зависимостями (см. ai/start.ps1).
#   - Создастся backend/.env из .env.example.
#   - npm установит node_modules перед vite.
#
# Окна каждой подсистемы открываются отдельными процессами — closing терминал,
# из которого запускали этот скрипт, НЕ убивает фоновые процессы. Останавливать
# их вручную: `docker compose -f backend/docker-compose.dev.yml down`,
# Stop-Process для python/uvicorn, закрыть npm-окно.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Prerequisite {
    param(
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(Mandatory = $true)] [scriptblock] $Check,
        [Parameter(Mandatory = $true)] [string] $InstallHint
    )
    try {
        & $Check
        Write-Host "  [+] $Name" -ForegroundColor Green
    } catch {
        Write-Host "  [-] $Name -- not found" -ForegroundColor Red
        Write-Host "      $InstallHint" -ForegroundColor Yellow
        throw "Предусловие не выполнено: $Name"
    }
}

Write-Host '== support-demo: проверка предусловий ==' -ForegroundColor Cyan
Test-Prerequisite -Name 'Docker Desktop запущен' -InstallHint 'Запустите Docker Desktop вручную' -Check {
    docker info --format '{{.ServerVersion}}' | Out-Null
}
Test-Prerequisite -Name 'Python (py или python в PATH)' -InstallHint 'Установите Python 3.12: https://www.python.org/downloads/' -Check {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { Get-Command python -ErrorAction Stop | Out-Null }
}
Test-Prerequisite -Name 'Node.js (npm в PATH)' -InstallHint 'Установите Node.js 18+: https://nodejs.org/' -Check {
    Get-Command npm -ErrorAction Stop | Out-Null
}

# Ollama проверяется в ai/start.ps1 — он автостартует сервис, если установлен
# в %LOCALAPPDATA%\Programs\Ollama. Если установлен в другом месте — запустите
# `ollama serve` вручную перед этим скриптом.

Write-Host ''
Write-Host '== 1/3: AI-сервис (Ollama + uvicorn :8001) ==' -ForegroundColor Cyan
& (Join-Path $root 'ai\start.ps1')

Write-Host ''
Write-Host '== 2/3: Backend (docker-compose.dev.yml) ==' -ForegroundColor Cyan
Write-Host '       Логи backend идут в отдельное окно PowerShell.' -ForegroundColor DarkGray
Start-Process powershell `
    -WorkingDirectory (Join-Path $root 'backend') `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'start.ps1'

Write-Host ''
Write-Host '== 3/3: Frontend (vite :5173) ==' -ForegroundColor Cyan
Write-Host '       Логи frontend идут в отдельное окно PowerShell.' -ForegroundColor DarkGray
Start-Process powershell `
    -WorkingDirectory (Join-Path $root 'frontend') `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', 'npm install; npm run dev'

Write-Host ''
Write-Host '== Готово ==' -ForegroundColor Green
Write-Host '  Backend:    http://localhost:8000  (Swagger: /docs)'
Write-Host '  Frontend:   http://localhost:5173'
Write-Host '  AI service: http://localhost:8001/healthcheck'
Write-Host ''
Write-Host 'Подождите 10-30 секунд пока поднимутся контейнеры и vite.' -ForegroundColor DarkGray
