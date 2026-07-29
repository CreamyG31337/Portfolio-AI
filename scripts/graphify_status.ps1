# Show where Graphify graph lives and whether it looks healthy.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FixedInstall = Join-Path $env:USERPROFILE "graphify\LLM-Micro-Cap-trading-bot"
$RepoGraph = Join-Path $RepoRoot "graphify-out\graph.json"
$McpConfig = Join-Path $env:USERPROFILE ".cursor\mcp.json"

function Show-GraphInfo {
    param([string]$Label, [string]$Path)
    if (-not (Test-Path $Path)) {
        Write-Host "  $Label : (missing)"
        return
    }
    $item = Get-Item $Path
    Write-Host "  $Label : $($item.FullName)"
    Write-Host "             $($item.Length) bytes, modified $($item.LastWriteTime)"
}

Write-Host "Graphify locations on this PC:"
Write-Host ""
Show-GraphInfo -Label "Fixed install (use this for MCP)" -Path (Join-Path $FixedInstall "graph.json")
Show-GraphInfo -Label "Repo graphify-out (build cache, ignore for MCP)" -Path $RepoGraph
Write-Host ""

if (Test-Path $McpConfig) {
    $raw = Get-Content $McpConfig -Raw
    if ($raw -match 'graphify-trading-bot') {
        Write-Host "MCP graphify-trading-bot entry: found in $McpConfig"
    } else {
        Write-Host "MCP graphify-trading-bot entry: NOT configured" -ForegroundColor Yellow
    }
} else {
    Write-Host "MCP config not found: $McpConfig" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Share graph:  .\scripts\graphify_export.ps1"
Write-Host "Receive graph: .\scripts\graphify_import.ps1 -ZipPath `"...\graphify-trading-bot-....zip`""
