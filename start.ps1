$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

& (Join-Path $root 'ai\start.ps1')

Start-Process powershell `
  -WindowStyle Hidden `
  -WorkingDirectory (Join-Path $root 'backend') `
  -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'start.ps1'

Start-Process powershell `
  -WindowStyle Hidden `
  -WorkingDirectory (Join-Path $root 'frontend') `
  -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', 'npm run dev'
