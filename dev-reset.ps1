$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$composeFile = "docker-compose.dev.yml"

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    docker compose -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Uri,
        [int] $TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Uri -TimeoutSec 3 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

Push-Location $backend
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host "Created backend .env from .env.example" -ForegroundColor Yellow
    }

    Write-Host "Stopping backend and removing dev DB volume..." -ForegroundColor Cyan
    Invoke-Compose @("down", "-v", "--remove-orphans")

    Write-Host "Building backend image..." -ForegroundColor Cyan
    Invoke-Compose @("build")

    Write-Host "Starting database..." -ForegroundColor Cyan
    Invoke-Compose @("up", "-d", "db")

    Write-Host "Applying migrations on a clean database..." -ForegroundColor Cyan
    Invoke-Compose @("run", "--rm", "app", "python", "-m", "alembic", "upgrade", "head")

    Write-Host "Seeding demo users, agents, templates and knowledge base..." -ForegroundColor Cyan
    Invoke-Compose @("run", "--rm", "app", "python", "-m", "scripts.seed_demo_agents")
    Invoke-Compose @("run", "--rm", "app", "python", "-m", "scripts.seed_response_templates")
    Invoke-Compose @("run", "--rm", "app", "python", "-m", "scripts.seed_knowledge_articles")

    Write-Host "Starting backend services and workers..." -ForegroundColor Cyan
    Invoke-Compose @("up", "-d", "app", "ai-worker", "sla-worker", "knowledge-embedding-worker")

    Write-Host "Checking backend health..." -ForegroundColor Cyan
    if (-not (Wait-ForHttp -Uri "http://127.0.0.1:8000/healthcheck" -TimeoutSeconds 120)) {
        Write-Host "Backend did not respond on /healthcheck." -ForegroundColor Red
        Write-Host "Check logs: cd backend; docker compose -f docker-compose.dev.yml logs app --tail=100" -ForegroundColor Yellow
        throw "Backend healthcheck failed"
    }

    Write-Host ""
    Write-Host "Dev reset completed." -ForegroundColor Green
    Write-Host "Backend: http://127.0.0.1:8000"
    Write-Host "Demo users:"
    Write-Host "  demo_user / DemoPass123!"
    Write-Host "  demo_admin / DemoPass123!"
    Write-Host "  it_agent / DemoPass123!"
}
finally {
    Pop-Location
}
