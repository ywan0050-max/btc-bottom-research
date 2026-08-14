param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TemporaryRoot = Join-Path $ProjectRoot (".tmp\service-smoke-" + [Guid]::NewGuid().ToString("N"))
$RuntimePath = Join-Path $TemporaryRoot "runtime.json"
$DatabasePath = Join-Path $TemporaryRoot "smoke.duckdb"
$Server = $null
$Listener = $null
$PreviousEnvironment = @{
    BTC_RESEARCH_DISABLE_BACKGROUND_TASKS = $env:BTC_RESEARCH_DISABLE_BACKGROUND_TASKS
    BTC_RESEARCH_DB = $env:BTC_RESEARCH_DB
    BTC_RESEARCH_RUNTIME_FILE = $env:BTC_RESEARCH_RUNTIME_FILE
    PYTHONIOENCODING = $env:PYTHONIOENCODING
    PYTHONUTF8 = $env:PYTHONUTF8
}

try {
    New-Item -ItemType Directory -Force -Path $TemporaryRoot | Out-Null
    $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $Listener.Start()
    $OccupiedPort = ([Net.IPEndPoint]$Listener.LocalEndpoint).Port

    $env:BTC_RESEARCH_DISABLE_BACKGROUND_TASKS = "1"
    $env:BTC_RESEARCH_DB = $DatabasePath
    $env:BTC_RESEARCH_RUNTIME_FILE = $RuntimePath
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Host "Starting fallback check with occupied port $OccupiedPort..."

    $RunPath = Join-Path $ProjectRoot "run.py"
    $ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $ProcessInfo.FileName = (Resolve-Path -LiteralPath $PythonPath).Path
    $ProcessInfo.Arguments = "`"$RunPath`" --port $OccupiedPort"
    $ProcessInfo.WorkingDirectory = $ProjectRoot
    $ProcessInfo.UseShellExecute = $false
    $ProcessInfo.CreateNoWindow = $true
    $ProcessInfo.RedirectStandardOutput = $true
    $ProcessInfo.RedirectStandardError = $true
    $ProcessInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $ProcessInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $Server = New-Object System.Diagnostics.Process
    $Server.StartInfo = $ProcessInfo
    if (-not $Server.Start()) {
        throw "Could not start the real service process."
    }

    $Deadline = [DateTime]::UtcNow.AddSeconds(45)
    $Runtime = $null
    $HealthResponse = $null
    do {
        if ($Server.HasExited) {
            $OutputText = $Server.StandardOutput.ReadToEnd()
            $ErrorText = $Server.StandardError.ReadToEnd()
            throw "Service exited before becoming healthy with code $($Server.ExitCode). Output: $OutputText Error: $ErrorText"
        }
        if (Test-Path -LiteralPath $RuntimePath) {
            try {
                $Runtime = Get-Content -LiteralPath $RuntimePath -Raw | ConvertFrom-Json
                $HealthResponse = Invoke-WebRequest `
                    -UseBasicParsing `
                    -Uri "$($Runtime.localUrl)/api/health" `
                    -TimeoutSec 2
                if ($HealthResponse.StatusCode -eq 200) { break }
            } catch {
                $HealthResponse = $null
            }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $Deadline)

    if ($null -eq $Runtime -or $null -eq $HealthResponse -or $HealthResponse.StatusCode -ne 200) {
        throw "Service did not become healthy before the timeout."
    }
    if ([int]$Runtime.port -eq $OccupiedPort) {
        throw "The non-strict launcher did not avoid occupied port $OccupiedPort."
    }
    if ([string]$Runtime.host -ne "0.0.0.0") {
        throw "The service did not default to 0.0.0.0."
    }

    $Health = $HealthResponse.Content | ConvertFrom-Json
    if ($Health.status -ne "ok" -or $Health.version -ne "0.1.0") {
        throw "Unexpected health response from the real service."
    }
    if ([int]$Health.runtime.port -ne [int]$Runtime.port) {
        throw "Runtime metadata and health response disagree about the port."
    }
    if ([string]$HealthResponse.Headers["Cache-Control"] -notmatch "no-store") {
        throw "API Cache-Control header is missing no-store."
    }

    Write-Host "Checking API, PWA, and license routes on $($Runtime.localUrl)..."
    foreach ($Path in @(
        "/api/overview",
        "/api/sources",
        "/manifest.webmanifest",
        "/icon.svg",
        "/sw.js",
        "/LICENSE",
        "/"
    )) {
        $Response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri ($Runtime.localUrl + $Path) `
            -TimeoutSec 10
        if ($Response.StatusCode -ne 200) {
            throw "$Path returned $($Response.StatusCode)."
        }
    }

    Stop-Process -Id $Server.Id -Force
    $Server.WaitForExit(10000) | Out-Null
    $OutputText = $Server.StandardOutput.ReadToEnd()
    $ErrorText = $Server.StandardError.ReadToEnd()
    if (
        $OutputText -notmatch [regex]::Escape([string]$OccupiedPort) -or
        $OutputText -notmatch [regex]::Escape([string]$Runtime.port)
    ) {
        throw "The launcher output did not include both requested and actual ports. Output: $OutputText Error: $ErrorText"
    }
    if ($OutputText -notmatch [regex]::Escape([string]$Runtime.localUrl)) {
        throw "The launcher did not print the actual local URL. Output: $OutputText"
    }

    $StrictProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $CurrentPowerShellPath = (Get-Process -Id $PID).Path
    if ([string]::IsNullOrWhiteSpace($CurrentPowerShellPath)) {
        throw "Could not resolve the current PowerShell executable."
    }
    $StrictProcessInfo.FileName = $CurrentPowerShellPath
    $StartPath = Join-Path $ProjectRoot "start.ps1"
    $StrictProcessInfo.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$StartPath`" -Port $OccupiedPort -StrictPort"
    $StrictProcessInfo.WorkingDirectory = $ProjectRoot
    $StrictProcessInfo.UseShellExecute = $false
    $StrictProcessInfo.CreateNoWindow = $true
    $StrictProcessInfo.RedirectStandardOutput = $true
    $StrictProcessInfo.RedirectStandardError = $true
    $StrictProcessInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $StrictProcessInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $StrictProcess = New-Object System.Diagnostics.Process
    $StrictProcess.StartInfo = $StrictProcessInfo
    if (-not $StrictProcess.Start()) {
        throw "Could not start the strict-port launcher check."
    }
    Write-Host "Checking strict-port failure propagation for $OccupiedPort..."
    if (-not $StrictProcess.WaitForExit(30000)) {
        Stop-Process -Id $StrictProcess.Id -Force
        throw "Strict-port launcher check timed out."
    }
    $StrictOutput = $StrictProcess.StandardOutput.ReadToEnd()
    $StrictError = $StrictProcess.StandardError.ReadToEnd()
    if ($StrictProcess.ExitCode -eq 0) {
        throw "Strict-port launcher returned success for occupied port $OccupiedPort. Output: $StrictOutput Error: $StrictError"
    }
    if (($StrictOutput + $StrictError) -notmatch "Requested port $OccupiedPort is already in use") {
        throw "Strict-port launcher did not explain the occupied port. Output: $StrictOutput Error: $StrictError"
    }

    Write-Host "Port fallback succeeded: $OccupiedPort -> $($Runtime.port)"
    Write-Host "Real single-port service succeeded: $($Runtime.localUrl)"
    Write-Host "Strict-port failure propagated with exit code $($StrictProcess.ExitCode)"
} finally {
    if ($Server -and -not $Server.HasExited) {
        Stop-Process -Id $Server.Id -Force
        $Server.WaitForExit(10000) | Out-Null
    }
    if ($Listener) {
        $Listener.Stop()
    }
    foreach ($Name in $PreviousEnvironment.Keys) {
        $Value = $PreviousEnvironment[$Name]
        if ($null -eq $Value) {
            Remove-Item -Path "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$Name" -Value $Value
        }
    }
    if (Test-Path -LiteralPath $TemporaryRoot) {
        $Removed = $false
        foreach ($Attempt in 1..5) {
            try {
                Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force -ErrorAction Stop
                $Removed = $true
                break
            } catch {
                if ($Attempt -lt 5) {
                    Start-Sleep -Milliseconds (250 * $Attempt)
                }
            }
        }
        if (-not $Removed) {
            Write-Warning "Could not remove service smoke directory: $TemporaryRoot"
        }
    }
}
