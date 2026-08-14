param(
    [switch]$SkipAudit
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$TestTemp = Join-Path $ProjectRoot (".tmp\pytest-" + [Guid]::NewGuid().ToString("N"))
$StateTools = Join-Path $ProjectRoot "scripts\project-state.ps1"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python environment is missing. Run setup.ps1 first."
}
if (-not $NpmCommand) {
    throw "npm.cmd was not found. Install Node.js first."
}

try {
    Write-Host "Checking PowerShell launchers and project fingerprints..."
    foreach ($ScriptPath in @(
        (Join-Path $ProjectRoot "setup.ps1"),
        (Join-Path $ProjectRoot "start.ps1"),
        $StateTools,
        (Join-Path $ProjectRoot "scripts\service-smoke.ps1")
    )) {
        $Tokens = $null
        $ParseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$Tokens, [ref]$ParseErrors) | Out-Null
        if ($ParseErrors.Count -gt 0) {
            throw "PowerShell syntax check failed for $ScriptPath`: $($ParseErrors[0].Message)"
        }
    }
    . $StateTools
    foreach ($Kind in @("Python", "WebDependencies", "WebBuild")) {
        $Fingerprint = Get-ProjectInputFingerprint -ProjectRoot $ProjectRoot -Kind $Kind
        if ($Fingerprint -notmatch "^[0-9a-f]{64}$") {
            throw "Invalid $Kind input fingerprint."
        }
    }

    Write-Host "Checking Python syntax..."
    & $PythonPath -m compileall -q (Join-Path $ProjectRoot "app") (Join-Path $ProjectRoot "tests") (Join-Path $ProjectRoot "run.py")
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed." }

    Write-Host "Checking Python dependencies..."
    & $PythonPath -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Python dependency check failed." }

    & $PythonPath -c "import pytest" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "pytest is missing. Install requirements-dev.txt before running verification."
    }

    Write-Host "Running tests..."
    Push-Location $ProjectRoot
    try {
        & $PythonPath -m pytest -q tests -p no:cacheprovider --basetemp=$TestTemp
        if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    } finally {
        Pop-Location
    }

    Write-Host "Building the web application..."
    Push-Location (Join-Path $ProjectRoot "web")
    try {
        & $NpmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw "Web build failed." }
        if (-not $SkipAudit) {
            & $NpmCommand.Source audit --audit-level=high
            if ($LASTEXITCODE -ne 0) { throw "npm audit found a high-severity issue." }
        }
    } finally {
        Pop-Location
    }

    Write-Host "Running API and PWA smoke checks..."
    Push-Location $ProjectRoot
    try {
        & $PythonPath (Join-Path $ProjectRoot "scripts\smoke.py")
        if ($LASTEXITCODE -ne 0) { throw "API and PWA smoke checks failed." }
    } finally {
        Pop-Location
    }

    Write-Host "Running real-process single-port and port-fallback checks..."
    & (Join-Path $ProjectRoot "scripts\service-smoke.ps1") -PythonPath $PythonPath
    if ($LASTEXITCODE -ne 0) { throw "Real-process service smoke check failed." }

    Write-Host "Verification complete."
} finally {
    if (Test-Path -LiteralPath $TestTemp) {
        try {
            Remove-Item -LiteralPath $TestTemp -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not remove temporary test directory: $TestTemp"
        }
    }
}
