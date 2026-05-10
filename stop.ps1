$root = Split-Path -Parent $MyInvocation.MyCommand.Path
 
Write-Host 'Stopping backend + Postgres...'
Push-Location (Join-Path $root 'backend')
docker compose -f docker-compose.dev.yml down
Pop-Location
 
Write-Host 'Stopping frontend and AI service...'
@(5173, 5174, 8001) | ForEach-Object {
    $conn = Get-NetTCPConnection -LocalPort $_ -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "  Port $_ freed"
    }
}
 
Write-Host 'Stopping Ollama...'
Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
 
Write-Host 'Done.'
