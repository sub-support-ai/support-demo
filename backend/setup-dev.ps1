param(
    [string] $Python = "python",
    [switch] $UseTrustedHosts,
    [switch] $Recreate
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title,
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command
    )

    Write-Host $Title -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Title"
    }
}

function Assert-UsablePython {
    param([string] $PythonCommand)

    $probe = "import sys, sysconfig; print(sys.executable); print(sys.version.split()[0]); print(sysconfig.get_platform()); print(sys.base_prefix)"
    $raw = & $PythonCommand -c $probe
    if ($LASTEXITCODE -ne 0) {
        throw "Python command is not runnable: $PythonCommand"
    }

    $lines = @($raw)
    if ($lines.Count -lt 4) {
        throw "Could not inspect Python runtime: $PythonCommand"
    }

    $info = [PSCustomObject]@{
        executable = $lines[0]
        version = $lines[1]
        platform = $lines[2]
        base_prefix = $lines[3]
    }

    $version = [version] $info.version
    if ($version.Major -ne 3 -or $version.Minor -ne 12) {
        throw "Python 3.12 is required. Found $($info.version) at $($info.executable)"
    }

    if ($info.platform -like "mingw*" -or $info.base_prefix -like "*\msys64\*") {
        throw @"
Unsupported Python runtime: $($info.executable)
Platform: $($info.platform)

Use the official CPython 3.12 x64 for Windows, not MSYS/MinGW Python.
After installing it, run:
  .\setup-dev.ps1 -Python "C:\Path\To\Python312\python.exe"
"@
    }

    return $info
}

Set-Location $root

$pythonInfo = Assert-UsablePython $Python
Write-Host "Using Python $($pythonInfo.version): $($pythonInfo.executable)" -ForegroundColor Green

if ($Recreate -and (Test-Path -LiteralPath $venv)) {
    $resolvedRoot = (Resolve-Path -LiteralPath $root).Path
    $resolvedVenv = (Resolve-Path -LiteralPath $venv).Path
    if (-not $resolvedVenv.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove venv outside backend directory: $resolvedVenv"
    }
    Write-Host "Removing existing .venv..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Step "Creating backend .venv..." {
        & $Python -m venv $venv
    }
}
else {
    Invoke-Step "Refreshing backend .venv launcher..." {
        & $Python -m venv --upgrade $venv
    }
}

$pipArgs = @("install", "--upgrade", "pip", "setuptools", "wheel")
if ($UseTrustedHosts) {
    $pipArgs += @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org")
}
Invoke-Step "Updating packaging tools..." {
    & $venvPython -m pip @pipArgs
}

$installArgs = @("install", "-r", "requirements-dev.txt")
if ($UseTrustedHosts) {
    $installArgs += @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org")
}
Invoke-Step "Installing backend dev dependencies..." {
    & $venvPython -m pip @installArgs
}

Write-Host ""
Write-Host "Backend dev environment is ready." -ForegroundColor Green
Write-Host "Run checks with:"
Write-Host "  .\.venv\Scripts\python.exe -m pytest -q"
Write-Host "  .\.venv\Scripts\python.exe -m ruff check ."
Write-Host "  .\.venv\Scripts\python.exe -m mypy app"
