param(
    [string[]] $PytestArgs = @("-q"),
    [switch] $SkipRuff,
    [switch] $SkipMypy
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Local backend .venv is missing. Run: .\setup-dev.ps1"
}

Set-Location $root

$oldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -c "import pytest, ruff, mypy" *> $null
$dependencyCheckExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorActionPreference
if ($dependencyCheckExitCode -ne 0) {
    throw "Backend dev dependencies are missing or incomplete. Run: .\setup-dev.ps1"
}

Write-Host "Running backend tests..." -ForegroundColor Cyan
& $python -m pytest @PytestArgs
if ($LASTEXITCODE -ne 0) {
    throw "pytest failed"
}

if (-not $SkipRuff) {
    Write-Host "Running ruff..." -ForegroundColor Cyan
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "ruff failed"
    }
}

if (-not $SkipMypy) {
    Write-Host "Running mypy..." -ForegroundColor Cyan
    & $python -m mypy app
    if ($LASTEXITCODE -ne 0) {
        throw "mypy failed"
    }
}

Write-Host "Backend checks passed." -ForegroundColor Green
