$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"

Write-Host "Stopping backend and removing dev DB volume..."
Push-Location $backend
docker compose -f docker-compose.dev.yml down -v --remove-orphans

Write-Host "Building backend..."
docker compose -f docker-compose.dev.yml build

Write-Host "Starting database..."
docker compose -f docker-compose.dev.yml up -d db

Write-Host "Checking migrations on clean DB..."
docker compose -f docker-compose.dev.yml run --rm app python -m alembic upgrade head

Write-Host "Starting backend services..."
docker compose -f docker-compose.dev.yml up -d

Write-Host "Checking backend health..."
Start-Sleep -Seconds 5
curl.exe http://127.0.0.1:8000/healthcheck

Pop-Location

Write-Host ""
Write-Host "Dev reset completed."