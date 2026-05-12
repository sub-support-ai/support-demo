$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Очистка зависших процессов на портах ─────────────────────────────────────
function Stop-Port {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "  Освобождён порт $Port (PID $($conn.OwningProcess))"
    }
}

Write-Host 'Освобождаем порты...'
Stop-Port 5173
Stop-Port 5174
Stop-Port 8001

Write-Host 'Останавливаем docker compose (backend)...'
$backendDir = Join-Path $root 'backend'
if (Test-Path (Join-Path $backendDir 'docker-compose.dev.yml')) {
    Push-Location $backendDir
    try {
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'

        docker compose -f docker-compose.dev.yml down

        if ($LASTEXITCODE -ne 0) {
            Write-Host "  docker compose down завершился с кодом $LASTEXITCODE, продолжаем запуск..."
        }
    }
    catch {
        Write-Host "  Не удалось остановить docker compose, продолжаем запуск..."
        Write-Host "  $($_.Exception.Message)"
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Pop-Location
    }
}

# ── Запуск сервисов ───────────────────────────────────────────────────────────
Write-Host 'Запуск AI-сервиса...'
& (Join-Path $root 'ai\start.ps1')

Write-Host 'Запуск backend (docker compose)...'
Start-Process powershell `
    -WindowStyle Normal `
    -WorkingDirectory $backendDir `
    -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'start.ps1'

$frontendDir = Join-Path $root 'frontend'
if (-not (Test-Path (Join-Path $frontendDir '.env.local'))) {
    Copy-Item (Join-Path $frontendDir '.env.example') (Join-Path $frontendDir '.env.local')
    Write-Host 'Created frontend .env.local'
}

Write-Host 'Запуск frontend...'
Start-Process powershell `
    -WindowStyle Normal `
    -WorkingDirectory (Join-Path $root 'frontend') `
    -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', 'if (-not (Test-Path node_modules)) { npm install }; npm run dev'

Write-Host ''
Write-Host '✓ Всё запущено.'
Write-Host '  Frontend : http://localhost:5173'
Write-Host '  Backend  : http://localhost:8000'
Write-Host '  AI       : http://localhost:8001'