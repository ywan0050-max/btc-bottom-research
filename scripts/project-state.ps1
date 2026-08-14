function Get-ProjectInputFingerprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [ValidateSet("Python", "WebDependencies", "WebBuild")]
        [string]$Kind
    )

    $ResolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd("\")
    $Files = @()

    switch ($Kind) {
        "Python" {
            $Files = @(
                Join-Path $ResolvedRoot "requirements.txt"
            )
        }
        "WebDependencies" {
            $Files = @(
                Join-Path $ResolvedRoot "web\package.json"
                Join-Path $ResolvedRoot "web\package-lock.json"
            )
        }
        "WebBuild" {
            $Files = @(
                Join-Path $ResolvedRoot "web\package.json"
                Join-Path $ResolvedRoot "web\package-lock.json"
                Join-Path $ResolvedRoot "web\vite.config.js"
                Join-Path $ResolvedRoot "web\index.html"
            )
            foreach ($Directory in @("web\public", "web\src")) {
                $FullDirectory = Join-Path $ResolvedRoot $Directory
                if (-not (Test-Path -LiteralPath $FullDirectory -PathType Container)) {
                    throw "Required web input directory is missing: $FullDirectory"
                }
                $Files += Get-ChildItem -LiteralPath $FullDirectory -Recurse -File |
                    Select-Object -ExpandProperty FullName
            }
        }
    }

    $Entries = foreach ($File in ($Files | Sort-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
            throw "Required project input is missing: $File"
        }
        $ResolvedFile = (Resolve-Path -LiteralPath $File).Path
        if (-not $ResolvedFile.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Project input is outside the project root: $ResolvedFile"
        }
        $RelativePath = $ResolvedFile.Substring($ResolvedRoot.Length).TrimStart("\")
        $FileHash = (Get-FileHash -LiteralPath $ResolvedFile -Algorithm SHA256).Hash.ToLowerInvariant()
        "$RelativePath|$FileHash"
    }

    $Payload = [Text.Encoding]::UTF8.GetBytes(($Entries -join "`n"))
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Hasher.ComputeHash($Payload)
        return (($Digest | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $Hasher.Dispose()
    }
}

function Read-ProjectSetupState {
    param([Parameter(Mandatory = $true)][string]$StatePath)

    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-ProjectSetupState {
    param(
        [Parameter(Mandatory = $true)][string]$StatePath,
        [Parameter(Mandatory = $true)][string]$PythonFingerprint,
        [AllowNull()][string]$WebDependenciesFingerprint,
        [AllowNull()][string]$WebBuildFingerprint
    )

    $StateDirectory = Split-Path -Parent $StatePath
    New-Item -ItemType Directory -Force -Path $StateDirectory | Out-Null
    $TemporaryPath = "$StatePath.$PID.tmp"
    $State = [ordered]@{
        pythonFingerprint = $PythonFingerprint
        webDependenciesFingerprint = $WebDependenciesFingerprint
        webBuildFingerprint = $WebBuildFingerprint
        updatedAt = [DateTime]::UtcNow.ToString("o")
    }
    try {
        $State | ConvertTo-Json | Set-Content -LiteralPath $TemporaryPath -Encoding UTF8
        Move-Item -LiteralPath $TemporaryPath -Destination $StatePath -Force
    } finally {
        if (Test-Path -LiteralPath $TemporaryPath) {
            Remove-Item -LiteralPath $TemporaryPath -Force
        }
    }
}
