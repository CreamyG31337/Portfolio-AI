# Pack Graphify graph for transfer between PCs (USB, email, etc.).
# Does NOT use OneDrive. Source: repo graphify-out/ or fixed install path.
param(
    [string]$SourceDir = "",
    [string]$OutputZip = "",
    [int]$MinNodes = 10000
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DefaultSource = Join-Path $RepoRoot "graphify-out"
$FixedInstall = Join-Path $env:USERPROFILE "graphify\LLM-Micro-Cap-trading-bot"

if (-not $SourceDir) {
    if (Test-Path (Join-Path $FixedInstall "graph.json")) {
        $SourceDir = $FixedInstall
    } else {
        $SourceDir = $DefaultSource
    }
}

$GraphPath = Join-Path $SourceDir "graph.json"
$ManifestPath = Join-Path $SourceDir "manifest.json"

if (-not (Test-Path $GraphPath)) {
    throw "graph.json not found at: $GraphPath"
}

function Get-GraphStats {
    param([string]$Path)
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
    $out = & $py -c $code $Path 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to parse graph.json: $out"
    }
    return @{
        Nodes = [int]$out[0]
        Edges = [int]$out[1]
    }
}

$stats = Get-GraphStats -Path $GraphPath
if ($stats.Nodes -lt $MinNodes) {
    throw "Refusing to export: only $($stats.Nodes) nodes (expected at least $MinNodes). Wrong or stale graph?"
}

$graphBytes = [System.IO.File]::ReadAllBytes($GraphPath)
$sha256 = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash($graphBytes)
).Replace("-", "").ToLower()

$meta = [ordered]@{
    exported_at   = (Get-Date).ToUniversalTime().ToString("o")
    source_dir    = (Resolve-Path $SourceDir).Path
    graph_bytes   = $graphBytes.Length
    manifest_bytes = if (Test-Path $ManifestPath) { (Get-Item $ManifestPath).Length } else { 0 }
    nodes         = $stats.Nodes
    edges         = $stats.Edges
    sha256        = $sha256
    mcp_graph_path = (Join-Path $FixedInstall "graph.json")
}

if (-not $OutputZip) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmm"
    $OutputZip = Join-Path $env:USERPROFILE "Desktop\graphify-trading-bot-$stamp.zip"
}

$tempDir = Join-Path $env:TEMP "graphify-export-$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
try {
    Copy-Item $GraphPath (Join-Path $tempDir "graph.json")
    if (Test-Path $ManifestPath) {
        Copy-Item $ManifestPath (Join-Path $tempDir "manifest.json")
    }
    ($meta | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $tempDir "graph.meta.json") -Encoding UTF8

    if (Test-Path $OutputZip) {
        Remove-Item $OutputZip -Force
    }
    Compress-Archive -Path (Join-Path $tempDir "*") -DestinationPath $OutputZip -Force
}
finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Graphify export OK" -ForegroundColor Green
Write-Host "  Zip:     $OutputZip ($('{0:N0}' -f (Get-Item $OutputZip).Length) bytes)"
Write-Host "  Nodes:   $($stats.Nodes)"
Write-Host "  Edges:   $($stats.Edges)"
Write-Host "  SHA256:  $sha256"
Write-Host ""
Write-Host "Transfer this zip to the other PC (USB, email, etc.) — NOT OneDrive graphify-out/."
Write-Host "On the other PC run:"
Write-Host "  .\scripts\graphify_import.ps1 -ZipPath `"<path-to-this-zip>`""
