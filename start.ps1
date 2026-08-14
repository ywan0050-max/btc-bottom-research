param(
    [int]$Port = 0,
    [switch]$StrictPort,
    [switch]$Reload,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PipPath = Join-Path $ProjectRoot ".venv\Scripts\pip.exe"
$WebIndex = Join-Path $ProjectRoot "web\dist\index.html"
$LocalTemp = Join-Path $ProjectRoot ".tmp"
New-Item -ItemType Directory -Force -Path $LocalTemp | Out-Null
$env:TEMP = $LocalTemp
$env:TMP = $LocalTemp
$env:npm_config_cache = Join-Path $LocalTemp "npm-cache"

function Get-RunningRuntime {
    param([string]$RuntimeFile)

    if (-not (Test-Path -LiteralPath $RuntimeFile)) {
        return $null
    }

    try {
        $Runtime = Get-Content -LiteralPath $RuntimeFile -Raw | ConvertFrom-Json
        $LocalUrl = [string]$Runtime.localUrl
        if ([string]::IsNullOrWhiteSpace($LocalUrl)) {
            return $null
        }
        $Health = Invoke-RestMethod -UseBasicParsing -Uri "$LocalUrl/api/health" -TimeoutSec 2
        if ($Health.status -eq "ok" -and $Health.runtime.port -eq $Runtime.port) {
            return $Runtime
        }
    } catch {
        return $null
    }

    return $null
}

function Start-BrowserWhenReady {
    param([string]$RuntimeFile)

    $EscapedRuntimeFile = $RuntimeFile.Replace("'", "''")
    $HelperScript = @"
`$RuntimeFile = '$EscapedRuntimeFile'
`$Deadline = [DateTime]::UtcNow.AddMinutes(5)
while ([DateTime]::UtcNow -lt `$Deadline) {
    if (Test-Path -LiteralPath `$RuntimeFile) {
        try {
            `$Runtime = Get-Content -LiteralPath `$RuntimeFile -Raw | ConvertFrom-Json
            `$LocalUrl = [string]`$Runtime.localUrl
            if (-not [string]::IsNullOrWhiteSpace(`$LocalUrl)) {
                `$Health = Invoke-RestMethod -UseBasicParsing -Uri "`$LocalUrl/api/health" -TimeoutSec 2
                if (`$Health.status -eq 'ok') {
                    Start-Process -FilePath `$LocalUrl
                    exit 0
                }
            }
        } catch {
        }
    }
    Start-Sleep -Milliseconds 500
}
"@
    $EncodedHelper = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($HelperScript))
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
        "-NoLogo",
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-EncodedCommand", $EncodedHelper
    ) | Out-Null
}

$RuntimeFile = Join-Path $ProjectRoot ".runtime.json"
if ($OpenBrowser -and $Port -eq 0 -and -not $StrictPort -and -not $Reload) {
    $RunningRuntime = Get-RunningRuntime -RuntimeFile $RuntimeFile
    if ($null -ne $RunningRuntime) {
        Write-Host "BTC Bottom Research Desk is already running."
        Write-Host "Local URL: $($RunningRuntime.localUrl)"
        if ($RunningRuntime.lanUrl) {
            Write-Host "LAN URL: $($RunningRuntime.lanUrl)"
        }
        Start-Process -FilePath ([string]$RunningRuntime.localUrl)
        exit 0
    }
}

if (-not (Test-Path -LiteralPath $PythonPath) -or -not (Test-Path -LiteralPath $PipPath)) {
    & (Join-Path $ProjectRoot "setup.ps1")
} elseif (-not (Test-Path -LiteralPath $WebIndex)) {
    Push-Location (Join-Path $ProjectRoot "web")
    try {
        if (-not (Test-Path -LiteralPath "node_modules")) {
            if (Test-Path -LiteralPath "package-lock.json") {
                npm ci
            } else {
                npm install
            }
            if ($LASTEXITCODE -ne 0) { throw "Failed to install web dependencies." }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Failed to build the web application." }
    } finally {
        Pop-Location
    }
}

$Arguments = @((Join-Path $ProjectRoot "run.py"))
if ($Port -gt 0) {
    $Arguments += @("--port", $Port)
}
if ($StrictPort) {
    $Arguments += "--strict-port"
}
if ($Reload) {
    $Arguments += "--reload"
}

if ($OpenBrowser) {
    Start-BrowserWhenReady -RuntimeFile $RuntimeFile
}

& $PythonPath @Arguments
