<#
.SYNOPSIS
    Run the Module 07 traffic simulator from PowerShell (no raw Python). Streams
    realistic optimization turns into your Cosmos account so you can watch them flow
    Cosmos -> Fabric mirror -> Power BI / Optimization Console in near-real-time.

.DESCRIPTION
    Auto-detects your deployed workshop folder + its virtual environment, reads the
    Cosmos endpoint from your `azd` environment, prompts for the tenant and rate, then
    runs analytics/traffic_simulator.py under the venv. Ctrl+C to stop.

.PARAMETER Tenant
    Tenant to write the live turns under. Prompted (default `DemoLive`) when omitted.
    `DemoLive` is a dedicated demo tenant, separate from the seeded tenants; to watch it,
    filter your report/console to the tenant you choose here.

.PARAMETER Rate
    Turns per minute (default 120).

.PARAMETER Minutes
    How long to run (default 10). Ignored when -Forever is set.

.PARAMETER Forever
    Run until you press Ctrl+C.

.PARAMETER Assume
    Which model mix to write (direct mode). `auto` (default) reads the tenant's
    model-selection OptimizationPolicy: baseline single-model until you apply it,
    capability-tiered once active — so apply -> simulate -> re-measure shows a real
    cost delta. `baseline`/`tiered` force the mix regardless of policy.

.PARAMETER WorkshopRoot
    The deployed workshop folder (holds .azure + the venv). Auto-detected when omitted.

.EXAMPLE
    .\Run-TrafficSimulator.ps1
    Interactive: prompts for the tenant, then streams 120 turns/min for 10 minutes.

.EXAMPLE
    .\Run-TrafficSimulator.ps1 -Tenant marvel -Rate 200 -Forever
#>
[CmdletBinding()]
param(
    [string]$Tenant,
    [int]$Rate = 120,
    [int]$Minutes = 10,
    [switch]$Forever,
    [ValidateSet('auto', 'baseline', 'tiered')]
    [string]$Assume = 'auto',
    [string]$WorkshopRoot
)

$ErrorActionPreference = 'Stop'
$scriptDir = $PSScriptRoot
$simPy = Join-Path $scriptDir 'traffic_simulator.py'

function Fail($text) {
    Write-Host ''
    Write-Host "ERROR: $text" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $simPy)) {
    Fail "traffic_simulator.py not found next to this script ($simPy)."
}

# --- Resolve the deployed workshop tree (holds .azure + the venv) -------------
if (-not $WorkshopRoot) {
    $repoRoot = Resolve-Path (Join-Path $scriptDir '..')
    $candidates = @('02_completed', '01_exercises') |
        ForEach-Object { Join-Path $repoRoot $_ } |
        Where-Object { Test-Path (Join-Path $_ '.azure') }
    if ($candidates.Count -eq 0) {
        Fail "No azd environment found. Run 'azd up' in your workshop folder first (or pass -WorkshopRoot)."
    }
    elseif ($candidates.Count -eq 1) {
        $WorkshopRoot = $candidates[0]
    }
    else {
        Write-Host 'Multiple deployed workshop folders found:' -ForegroundColor Yellow
        for ($i = 0; $i -lt $candidates.Count; $i++) { Write-Host "  [$($i + 1)] $($candidates[$i])" }
        $pick = Read-Host 'Which one did you deploy? Enter a number'
        $idx = 0
        if (-not [int]::TryParse($pick, [ref]$idx) -or $idx -lt 1 -or $idx -gt $candidates.Count) {
            Fail "Invalid selection '$pick'."
        }
        $WorkshopRoot = $candidates[$idx - 1]
    }
}
$WorkshopRoot = (Resolve-Path $WorkshopRoot).Path

$python = @(
    (Join-Path $WorkshopRoot '.venv-travel\Scripts\python.exe'),
    (Join-Path $WorkshopRoot 'venv\Scripts\python.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    Fail "No virtual environment under $WorkshopRoot (looked for .venv-travel and venv). Re-run 'azd up'."
}

# --- Preflight: Azure sign-in (Cosmos uses DefaultAzureCredential) ------------
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail "'az' is not on PATH. Install the Azure CLI." }
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { Fail "You are not signed in to Azure. Run 'az login' then re-run." }

# --- Tenant prompt -----------------------------------------------------------
if (-not $Tenant) {
    $entered = Read-Host "Tenant to write live turns under [DemoLive]"
    $Tenant = if ([string]::IsNullOrWhiteSpace($entered)) { 'DemoLive' } else { $entered.Trim() }
}

# --- Read the deployment's Cosmos endpoint so we target the right account -----
$cosmos = ''
Push-Location $WorkshopRoot
try {
    $cosmos = (azd env get-values 2>$null |
        Select-String -Pattern '^COSMOSDB_ENDPOINT=' |
        ForEach-Object { ($_ -split '=', 2)[1].Trim().Trim('"') } |
        Select-Object -First 1)
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host "Workshop folder : $WorkshopRoot"
Write-Host "Tenant          : $Tenant"
Write-Host "Rate            : $Rate turns/min"
Write-Host ("Duration        : " + $(if ($Forever) { 'until Ctrl+C' } else { "$Minutes minutes" }))
Write-Host ("Model policy    : " + $(if ($Assume -eq 'auto') { 'auto (baseline until you apply model-selection, then tiered)' } else { "$Assume (forced)" }))
if ($cosmos) { Write-Host "Cosmos          : $cosmos" }
Write-Host ''
Write-Host "Streaming live turns under tenant '$Tenant' - watch your Power BI report" -ForegroundColor Cyan
Write-Host "(filtered to '$Tenant') or the Optimization Console update. Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host ''

$argList = @($simPy, '--tenant', $Tenant, '--rate', "$Rate", '--assume', $Assume)
if ($Forever) { $argList += '--forever' } else { $argList += @('--minutes', "$Minutes") }

$prev = $env:COSMOSDB_ENDPOINT
if ($cosmos) { $env:COSMOSDB_ENDPOINT = $cosmos }
try {
    & $python @argList
}
finally {
    $env:COSMOSDB_ENDPOINT = $prev
}
