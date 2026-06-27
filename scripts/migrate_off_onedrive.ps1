# Move the repo off OneDrive to a local path (default: C:\Projects\LLM-Micro-Cap-trading-bot).
# Fresh git clone + copy local-only files. Does NOT copy venv/node_modules/cache.
param(
    [string]$Source = "",
    [string]$Target = "C:\Projects\LLM-Micro-Cap-trading-bot",
    [string]$Remote = "https://github.com/CreamyG31337/Portfolio-AI.git",
    [switch]$SetupDeps,
    [switch]$SkipClone
)

$ErrorActionPreference = "Stop"

if (-not $Source) {
    $Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$Source = $Source.TrimEnd("\")
$Target = $Target.TrimEnd("\")

if ($Source -eq $Target) {
    throw "Source and target are the same path."
}

if ($Source -match "OneDrive" -and -not $env:GRAPHIFY_MIGRATE_OK) {
    Write-Host ""
    Write-Host "Close Cursor on the OneDrive folder before migrating." -ForegroundColor Yellow
    Write-Host "Then run this script again from PowerShell (not from the old workspace if possible)."
    Write-Host ""
}

Write-Host "Source (OneDrive): $Source"
Write-Host "Target (local):    $Target"
Write-Host ""

$targetParent = Split-Path $Target -Parent
if (-not (Test-Path $targetParent)) {
    New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
}

if (-not $SkipClone) {
    if (Test-Path $Target) {
        Write-Host "Target exists — pulling latest instead of cloning."
        Push-Location $Target
        try {
            git pull origin main
        }
        finally {
            Pop-Location
        }
    } else {
        Write-Host "Cloning repository..."
        git clone $Remote $Target
    }
}

function Copy-IfExists {
    param([string]$RelativePath)
    $from = Join-Path $Source $RelativePath
    $to = Join-Path $Target $RelativePath
    if (-not (Test-Path $from)) {
        return
    }
    $parent = Split-Path $to -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if (Test-Path $from -PathType Container) {
        Write-Host "  Copy dir:  $RelativePath"
        robocopy $from $to /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed for $RelativePath (exit $LASTEXITCODE)"
        }
    } else {
        Write-Host "  Copy file: $RelativePath"
        Copy-Item $from $to -Force
    }
}

Write-Host "Copying local-only files (not in git)..."
Copy-IfExists "trading_data"
Copy-IfExists "web_dashboard\.secrets"
Copy-IfExists "web_dashboard\test_credentials.json"
Copy-IfExists "mcps\mandrel\SERVER_METADATA.json"

foreach ($envName in @(".env", ".env.local", ".env.production", ".env.staging", ".env.test")) {
    Copy-IfExists $envName
}

# Graph build artifacts (optional; MCP should use %USERPROFILE%\graphify\...)
$graphOut = Join-Path $Source "graphify-out"
$targetGraphOut = Join-Path $Target "graphify-out"
if (Test-Path (Join-Path $graphOut "graph.json")) {
    New-Item -ItemType Directory -Path $targetGraphOut -Force | Out-Null
    foreach ($f in @("graph.json", "manifest.json", ".graphify_root")) {
        $src = Join-Path $graphOut $f
        if (Test-Path $src) {
            Write-Host "  Copy file: graphify-out\$f"
            Copy-Item $src (Join-Path $targetGraphOut $f) -Force
        }
    }
}

if ($SetupDeps) {
    Write-Host ""
    Write-Host "Setting up Python venv..."
    Push-Location $Target
    try {
        if (-not (Test-Path "venv\Scripts\python.exe")) {
            python -m venv venv
        }
        & .\venv\Scripts\python.exe -m pip install --upgrade pip
        & .\venv\Scripts\pip.exe install -r requirements.txt
        if (Test-Path "web_dashboard\requirements.txt") {
            & .\venv\Scripts\pip.exe install -r web_dashboard\requirements.txt
        }

        Write-Host "Installing Node dependencies (pnpm)..."
        if (Get-Command pnpm -ErrorAction SilentlyContinue) {
            pnpm install --frozen-lockfile
            Push-Location web_dashboard
            try {
                pnpm install --frozen-lockfile
            }
            finally {
                Pop-Location
            }
        } else {
            Write-Host "pnpm not found — skip Node install or install pnpm first." -ForegroundColor Yellow
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Migration complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Open in Cursor: $Target"
Write-Host "  2. File -> Open Folder -> $Target"
Write-Host "  3. Stop syncing the OneDrive copy (or delete after verifying)"
Write-Host "  4. Graphify MCP path unchanged: %USERPROFILE%\graphify\LLM-Micro-Cap-trading-bot\graph.json"
Write-Host ""
Write-Host "Verify: .\scripts\graphify_status.ps1"
if (-not $SetupDeps) {
    Write-Host "Deps not installed — re-run with -SetupDeps to create venv and pnpm install."
}
