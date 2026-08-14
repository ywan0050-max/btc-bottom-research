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
$SetupStatePath = Join-Path $LocalTemp "setup-state.json"
$StateTools = Join-Path $ProjectRoot "scripts\project-state.ps1"
. $StateTools

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

$PythonFingerprint = Get-ProjectInputFingerprint -ProjectRoot $ProjectRoot -Kind Python
$SetupState = Read-ProjectSetupState -StatePath $SetupStatePath
$PythonSetupIsCurrent = (
    $null -ne $SetupState -and
    [string]$SetupState.pythonFingerprint -eq $PythonFingerprint
)

if (
    -not (Test-Path -LiteralPath $PythonPath) -or
    -not (Test-Path -LiteralPath $PipPath) -or
    -not $PythonSetupIsCurrent
) {
    if ($null -ne $SetupState -and -not $PythonSetupIsCurrent) {
        Write-Host "Python requirements changed; updating the local environment..."
    }
    & (Join-Path $ProjectRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Project setup failed." }
    $SetupState = Read-ProjectSetupState -StatePath $SetupStatePath
}

$VenvPythonVersion = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $VenvPythonVersion -ne "3.12") {
    throw "The existing .venv does not use Python 3.12. Rename or remove it manually, then run setup.ps1 again."
}

$WebDependenciesFingerprint = Get-ProjectInputFingerprint -ProjectRoot $ProjectRoot -Kind WebDependencies
$WebBuildFingerprint = Get-ProjectInputFingerprint -ProjectRoot $ProjectRoot -Kind WebBuild
$WebDependenciesAreCurrent = (
    $null -ne $SetupState -and
    [string]$SetupState.webDependenciesFingerprint -eq $WebDependenciesFingerprint -and
    (Test-Path -LiteralPath (Join-Path $ProjectRoot "web\node_modules") -PathType Container)
)
$WebBuildIsCurrent = (
    $null -ne $SetupState -and
    [string]$SetupState.webBuildFingerprint -eq $WebBuildFingerprint -and
    (Test-Path -LiteralPath $WebIndex -PathType Leaf)
)

if (-not $WebDependenciesAreCurrent -or -not $WebBuildIsCurrent) {
    $NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $NpmCommand) {
        throw "npm was not found. Install Node.js and run start.ps1 again."
    }
    Push-Location (Join-Path $ProjectRoot "web")
    try {
        if (-not $WebDependenciesAreCurrent) {
            Write-Host "Web dependencies changed or are missing; installing from the lock file..."
            if (Test-Path -LiteralPath "package-lock.json") {
                & $NpmCommand.Source ci
            } else {
                & $NpmCommand.Source install
            }
            if ($LASTEXITCODE -ne 0) { throw "Failed to install web dependencies." }
        }
        Write-Host "Web sources changed or the production build is missing; rebuilding..."
        & $NpmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw "Failed to build the web application." }
    } finally {
        Pop-Location
    }
    Write-ProjectSetupState `
        -StatePath $SetupStatePath `
        -PythonFingerprint $PythonFingerprint `
        -WebDependenciesFingerprint $WebDependenciesFingerprint `
        -WebBuildFingerprint $WebBuildFingerprint
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
$RunExitCode = $LASTEXITCODE
if ($RunExitCode -ne 0) {
    exit $RunExitCode
}
