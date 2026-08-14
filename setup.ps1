param(
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
$LocalTemp = Join-Path $ProjectRoot ".tmp"
New-Item -ItemType Directory -Force -Path $LocalTemp | Out-Null
$env:TEMP = $LocalTemp
$env:TMP = $LocalTemp
$env:npm_config_cache = Join-Path $LocalTemp "npm-cache"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    $BasePython = $null
    $BaseArguments = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $DetectedVersion = & py -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $DetectedVersion -eq "3.12") {
            $BasePython = "py"
            $BaseArguments = @("-3.12")
        }
    }
    if (-not $BasePython -and (Get-Command python -ErrorAction SilentlyContinue)) {
        $DetectedVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($LASTEXITCODE -eq 0 -and $DetectedVersion -eq "3.12") {
            $BasePython = "python"
        }
    }
    if (-not $BasePython) {
        throw "Python 3.12 was not found. Install Python 3.12 and run setup.ps1 again."
    }
    Write-Host "Creating Python 3.12 environment..."
    & $BasePython @BaseArguments -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the Python environment." }
}

$PipPath = Join-Path $VenvPath "Scripts\pip.exe"
if (-not (Test-Path -LiteralPath $PipPath)) {
    Write-Host "Repairing pip in the Python environment..."
    & $PythonPath -m ensurepip --upgrade --default-pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to install pip in the Python environment." }
}

Write-Host "Installing Python dependencies..."
& $PythonPath -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies." }

if (-not $SkipWeb) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found. Install Node.js and run setup.ps1 again."
    }
    Push-Location (Join-Path $ProjectRoot "web")
    try {
        if (Test-Path -LiteralPath "package-lock.json") {
            npm ci
        } else {
            npm install
        }
        if ($LASTEXITCODE -ne 0) { throw "Failed to install web dependencies." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Failed to build the web application." }
    } finally {
        Pop-Location
    }
}

Write-Host "Setup complete."
