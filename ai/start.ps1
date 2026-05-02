$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Join-Path $root 'ai-service'
Set-Location $serviceRoot

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
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "Timed out waiting for $Uri"
}

$ollamaProcess = Get-Process ollama -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    $ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (-not (Test-Path -LiteralPath $ollamaExe)) {
        throw "Ollama is not running and was not found at $ollamaExe"
    }

    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
    Wait-ForHttp -Uri 'http://localhost:11434/api/tags' -TimeoutSeconds 120
}

$pythonExe = Join-Path $serviceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Missing virtual environment Python at $pythonExe"
}

Start-Process `
    -FilePath $pythonExe `
    -WorkingDirectory $serviceRoot `
    -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '8001') `
    -WindowStyle Hidden

Wait-ForHttp -Uri 'http://localhost:8001/healthcheck' -TimeoutSeconds 120
