# Локальный запуск backend'а через docker-compose.dev.yml.
#
# В Блоке 11 compose разделили на dev / prod (см. docs/deployment.md):
# default-имя docker-compose.yml больше не используется, поэтому без явного
# `-f docker-compose.dev.yml` команда `docker compose up` не найдёт файл.
#
# .env создаётся из .env.example при первом запуске — для dev-значений по
# умолчанию (POSTGRES_PASSWORD=postgres, RATE_LIMIT_BACKEND=memory и т.п.)
# этого достаточно. В .env.example комментарии объясняют, что нужно править.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env from .env.example' -ForegroundColor Yellow
}

Write-Host 'Starting backend (docker-compose.dev.yml)...' -ForegroundColor Cyan
docker compose -f docker-compose.dev.yml up --build
