# Merge safe code PRs (JWT fix, performance, palette UX). Leave doc-only PRs for later.
# Run from repo root with: .\scripts\merge_open_prs.ps1

$repo = "CreamyG31337/Portfolio-AI"
$toMerge = @(101, 106, 100, 105, 99)   # JWT, metrics, parallel load, toggles, settings UX
$toLeave = @(97, 98, 102, 103, 104)     # Doc/suggestions - implement changes then merge later

Write-Host "Merging code PRs: $($toMerge -join ', ')"
foreach ($num in $toMerge) {
    Write-Host "Merging PR $num..."
    gh pr merge $num --repo $repo --squash
    if ($LASTEXITCODE -ne 0) { Write-Host "  Failed (maybe already merged or conflict)." }
}
Write-Host "Done. Left for later (docs): $($toLeave -join ', ')"
Write-Host "After implementing CODE_REVIEW / PALETTE_AUDIT suggestions, merge those PRs manually."
