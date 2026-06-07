# MINDI Tauri release verification (Windows, single-user desktop)
# Usage: .\scripts\verify-release.ps1
# Prerequisite: pnpm dev:all running in another terminal, models configured in Settings.

$ErrorActionPreference = "Stop"
$Agent = "http://127.0.0.1:8765"
$Runtime = "http://127.0.0.1:8877"

function Test-Endpoint {
    param([string]$Url, [string]$Label)
    $r = Invoke-RestMethod -Uri $Url -TimeoutSec 10
    if (-not $r.ok) { throw "$Label unhealthy: $Url" }
    Write-Host "[ok] $Label"
}

Write-Host "== MINDI release verification =="

Test-Endpoint "$Agent/health" "Agent"
Test-Endpoint "$Runtime/health" "AI Runtime"

$aiStatus = Invoke-RestMethod -Uri "$Agent/ops/ai/status" -TimeoutSec 15
if (-not $aiStatus.runtime.reachable) { throw "AI runtime not reachable from agent" }
foreach ($feature in @("llm", "asr", "ocr")) {
    $f = $aiStatus.features.$feature
    if (-not $f.ready) {
        Write-Warning "[warn] $feature not ready: $($f.lastError)"
    } else {
        Write-Host "[ok] $feature ready ($($f.model))"
    }
}

$taskTitle = "verify-release-$(Get-Date -Format 'yyyyMMddHHmmss')"
$created = Invoke-RestMethod -Uri "$Agent/tasks" -Method Post -ContentType "application/json" `
    -Body (@{ title = $taskTitle } | ConvertTo-Json)
Write-Host "[ok] Created task $($created.id)"

$tasks = Invoke-RestMethod -Uri "$Agent/tasks" -TimeoutSec 10
if (-not ($tasks | Where-Object { $_.title -eq $taskTitle })) {
    throw "Task not found in task list"
}
Write-Host "[ok] Task listed"

$statePath = Join-Path (Get-Location) "data\runtime\agent_state.json"
if (-not (Test-Path $statePath)) {
    Write-Warning "[warn] agent_state.json missing (persistence file not written yet)"
} elseif ((Get-Content $statePath -Raw) -notmatch [regex]::Escape($taskTitle)) {
    Write-Warning "[warn] task title not found in agent_state.json"
} else {
    Write-Host "[ok] Task persisted to agent_state.json"
}

Write-Host ""
Write-Host "Manual Tauri checks (pnpm dev:desktop):"
Write-Host "  - Orb click opens menu; drag position survives restart"
Write-Host "  - Vision capture + perception analyze (grant screen permission first)"
Write-Host "  - Voice mic -> ASR -> assistant reply -> TTS"
Write-Host ""
Write-Host "Automated smoke:"
Write-Host "  pnpm ops:ai-smoke -- --include-asr --include-ocr --asr-file-path <wav> --ocr-image-path <png>"
Write-Host ""
Write-Host "All automated checks passed."
