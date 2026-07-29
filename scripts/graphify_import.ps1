# Install a Graphify graph from export zip to a fixed path OUTSIDE OneDrive.
# Read-only on repo graphify-out/ — never rebuilds the graph.
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$InstallDir = Join-Path $env:USERPROFILE "graphify\LLM-Micro-Cap-trading-bot"
$GraphPath = Join-Path $InstallDir "graph.json"
$ManifestPath = Join-Path $InstallDir "manifest.json"
$MetaPath = Join-Path $InstallDir "graph.meta.json"

if (-not (Test-Path $ZipPath)) {
    throw "Zip not found: $ZipPath"
}

$tempDir = Join-Path $env:TEMP "graphify-import-$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
try {
    Expand-Archive -Path $ZipPath -DestinationPath $tempDir -Force

    $incomingGraph = Join-Path $tempDir "graph.json"
    $incomingMeta = Join-Path $tempDir "graph.meta.json"
    $incomingManifest = Join-Path $tempDir "manifest.json"

    if (-not (Test-Path $incomingGraph)) {
        throw "Invalid zip: missing graph.json"
    }
    if (-not (Test-Path $incomingMeta)) {
        throw "Invalid zip: missing graph.meta.json (use graphify_export.ps1 from the source PC)"
    }

    $meta = Get-Content $incomingMeta -Raw | ConvertFrom-Json
    $graphBytes = [System.IO.File]::ReadAllBytes($incomingGraph)
    $sha256 = [System.BitConverter]::ToString(
        [System.Security.Cryptography.SHA256]::Create().ComputeHash($graphBytes)
    ).Replace("-", "").ToLower()

    if ($meta.sha256 -ne $sha256) {
        throw "SHA256 mismatch — zip may be corrupt"
    }

    $py = Join-Path $RepoRoot "venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        $py = "python"
    }
    $code = @"
import json, sys
g = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(g.get("nodes", [])))
print(len(g.get("edges", [])))
"@
    $out = & $py -c $code $incomingGraph 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "graph.json is not valid JSON: $out"
    }
    $nodes = [int]$out[0]
    $edges = [int]$out[1]

    if ($nodes -ne [int]$meta.nodes) {
        throw "Node count mismatch: zip says $($meta.nodes), file has $nodes"
    }

    if ((Test-Path $GraphPath) -and -not $Force) {
        $existing = Get-Item $GraphPath
        if ($existing.Length -ge ($graphBytes.Length * 0.9)) {
            Write-Host "Existing graph already installed ($('{0:N0}' -f $existing.Length) bytes)." -ForegroundColor Yellow
            Write-Host "Use -Force to overwrite."
            return
        }
    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Copy-Item $incomingGraph $GraphPath -Force
    if (Test-Path $incomingManifest) {
        Copy-Item $incomingManifest $ManifestPath -Force
    }
    Copy-Item $incomingMeta $MetaPath -Force
}
finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Graphify import OK" -ForegroundColor Green
Write-Host "  Installed: $GraphPath"
Write-Host "  Nodes:     $nodes"
Write-Host "  Edges:     $edges"
Write-Host "  Exported:  $($meta.exported_at)"
Write-Host ""
Write-Host "MCP config (both PCs should use this path, NOT OneDrive graphify-out/):"
Write-Host @"

  "graphify-trading-bot": {
    "command": "$($env:USERPROFILE -replace '\\', '\\')\\.local\\bin\\graphify-mcp.exe",
    "args": [
      "$($GraphPath -replace '\\', '\\')"
    ]
  }

"@
Write-Host "Edit %USERPROFILE%\.cursor\mcp.json if needed, then restart Cursor."
