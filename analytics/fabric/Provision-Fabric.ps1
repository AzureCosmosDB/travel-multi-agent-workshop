<#
.SYNOPSIS
    Stands up the Microsoft Fabric analytics for Module 09: workspace, Cosmos mirror,
    the reverse-ETL notebook, and the translytical Apply/Revert User Data Function.
    PowerShell front end for the workshop - it prompts for the few values it needs and
    drives the proven provisioning underneath.

.DESCRIPTION
    `azd up` only creates the Fabric *capacity*. This script creates everything else:

        Phase 1  workspace  ->  assign to capacity  ->  workspace identity  ->  Cosmos RBAC
        (manual) create the Cosmos connection in the Fabric portal, copy its id
        Phase 2  mirrored database (starts replicating)  ->  Module 09 notebook  ->  Apply/Revert UDF

    The funnel_demo demo dataset the notebook reads is seeded automatically during `azd up`
    (postprovision), so there is nothing to seed here.

    Configuration (subscription, resource group, Cosmos account, capacity, database) is
    read automatically from your `azd` environment - you are only asked for the workspace
    name and the connection id from the portal step. Those two values (and the workshop
    folder) are remembered between runs in a local, git-ignored file and offered as the
    default at each prompt (press Enter to reuse); pass an explicit value or delete
    .provision-fabric.local.json to change one.

.PARAMETER WorkshopRoot
    The deployed workshop folder that holds your `azd` environment (the one you ran
    `azd up` in - e.g. ...\02_completed or ...\01_exercises). Auto-detected when omitted.

.PARAMETER WorkspaceName
    Fabric workspace display name to create/reuse. Prompted (with a default) when omitted.

.PARAMETER ConnectionId
    A pre-created Cosmos OAuth2 connection id. Provide it to skip the interactive
    portal prompt (useful for re-runs).

.PARAMETER Solution
    Upload the completed *_solution notebook instead of the learner (TODO) notebook.
    Use this for the 02_completed / demo path.

.PARAMETER Phase
    1   = workspace + identity + RBAC only (stop before the mirror)
    all = Phase 1, then the connection step, then the mirror + notebook  (default)

.EXAMPLE
    .\Provision-Fabric.ps1
    Interactive: detects your azd env, prompts for the workspace name, runs Phase 1,
    walks you through the portal connection, then creates the mirror and notebook.

.EXAMPLE
    .\Provision-Fabric.ps1 -Solution -ConnectionId 7ec42257-1111-2222-3333-444455556666
    Non-interactive re-run that uploads the completed notebook.
#>
[CmdletBinding()]
param(
    [string]$WorkshopRoot,
    [string]$WorkspaceName,
    [string]$ConnectionId,
    [switch]$Solution,
    [ValidateSet('1', 'all')]
    [string]$Phase = 'all'
)

$ErrorActionPreference = 'Stop'
$scriptDir = $PSScriptRoot
$provisionPy = Join-Path $scriptDir 'provision_fabric.py'

function Write-Section($text) {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor Cyan
    Write-Host " $text" -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor Cyan
}

function Fail($text) {
    Write-Host ''
    Write-Host "ERROR: $text" -ForegroundColor Red
    exit 1
}

# --- Saved defaults (workshop folder / workspace name / connection id) --------
# Remembered between runs in a local, git-ignored file so you don't re-enter them.
# Explicit -WorkshopRoot / -WorkspaceName / -ConnectionId always win; delete the file
# (or pass a new value) to change a remembered setting.
$stateFile = Join-Path $scriptDir '.provision-fabric.local.json'
$saved = $null
if (Test-Path $stateFile) {
    try { $saved = Get-Content -Raw $stateFile | ConvertFrom-Json } catch { $saved = $null }
}
function Save-State {
    try {
        $ws = if ($WorkshopRoot) { $WorkshopRoot } elseif ($saved) { $saved.WorkshopRoot } else { $null }
        $wn = if ($WorkspaceName) { $WorkspaceName } elseif ($saved) { $saved.WorkspaceName } else { $null }
        $ci = if ($ConnectionId) { $ConnectionId } elseif ($saved) { $saved.ConnectionId } else { $null }
        [ordered]@{ WorkshopRoot = $ws; WorkspaceName = $wn; ConnectionId = $ci } |
            ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
    }
    catch { }
}

if (-not (Test-Path $provisionPy)) {
    Fail "Cannot find provision_fabric.py next to this script ($provisionPy)."
}

# --- Resolve the deployed workshop tree (holds .azure + the venv) -------------
if (-not $WorkshopRoot -and $saved -and $saved.WorkshopRoot -and (Test-Path (Join-Path $saved.WorkshopRoot '.azure'))) {
    $WorkshopRoot = $saved.WorkshopRoot
}
if (-not $WorkshopRoot) {
    $repoRoot = Resolve-Path (Join-Path $scriptDir '..\..')
    $candidates = @('02_completed', '01_exercises') |
        ForEach-Object { Join-Path $repoRoot $_ } |
        Where-Object { Test-Path (Join-Path $_ '.azure') }

    if ($candidates.Count -eq 0) {
        Fail "No azd environment found. Run 'azd up' in your workshop folder first, then re-run this script (or pass -WorkshopRoot)."
    }
    elseif ($candidates.Count -eq 1) {
        $WorkshopRoot = $candidates[0]
    }
    else {
        Write-Host 'Multiple deployed workshop folders found:' -ForegroundColor Yellow
        for ($i = 0; $i -lt $candidates.Count; $i++) {
            Write-Host "  [$($i + 1)] $($candidates[$i])"
        }
        $pick = Read-Host 'Which one did you deploy? Enter a number'
        $idx = 0
        if (-not [int]::TryParse($pick, [ref]$idx) -or $idx -lt 1 -or $idx -gt $candidates.Count) {
            Fail "Invalid selection '$pick'."
        }
        $WorkshopRoot = $candidates[$idx - 1]
    }
}
$WorkshopRoot = (Resolve-Path $WorkshopRoot).Path

# --- Locate the Python interpreter from that tree's venv ----------------------
$python = @(
    (Join-Path $WorkshopRoot '.venv-travel\Scripts\python.exe'),
    (Join-Path $WorkshopRoot 'venv\Scripts\python.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    Fail "No virtual environment found under $WorkshopRoot (looked for .venv-travel and venv). Re-run 'azd up' or create the venv first."
}

# --- Preflight ---------------------------------------------------------------
Write-Section 'Preflight'
Write-Host "Workshop folder : $WorkshopRoot"
Write-Host "Python          : $python"

if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
    Fail "'azd' is not on PATH. Install the Azure Developer CLI and re-run."
}
try {
    az account show 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'not logged in' }
    Write-Host 'Azure login     : OK' -ForegroundColor Green
}
catch {
    Fail "You are not signed in to Azure. Run 'az login' (and 'azd auth login') then re-run."
}

# --- Workspace name ----------------------------------------------------------
if (-not $WorkspaceName) {
    $default = if ($saved -and $saved.WorkspaceName) { $saved.WorkspaceName } else { 'Multi-Agent Travel Workshop' }
    $entered = Read-Host "Fabric workspace name to create/reuse [$default]"
    $WorkspaceName = if ([string]::IsNullOrWhiteSpace($entered)) { $default } else { $entered.Trim() }
}
Write-Host "Workspace name  : $WorkspaceName"
Save-State

# --- Common argument builder -------------------------------------------------
$script:provisionExit = 0
function Invoke-Provision([string[]]$extraArgs) {
    $argList = @($provisionPy, '--workspace', $WorkspaceName) + $extraArgs
    if ($Solution) { $argList += '--solution' }
    Push-Location $WorkshopRoot
    try {
        & $python @argList
        $script:provisionExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

# --- Phase 1 -----------------------------------------------------------------
Write-Section 'Phase 1 - workspace, identity, Cosmos RBAC'
Invoke-Provision @('--phase', '1')
if ($script:provisionExit -ne 0) { Fail "Phase 1 failed (exit $script:provisionExit). See the output above." }
Write-Host 'Phase 1 complete.' -ForegroundColor Green

if ($Phase -eq '1') {
    Write-Host ''
    Write-Host 'Stopped after Phase 1 as requested. Re-run without -Phase 1 to create the mirror.'
    Save-State
    exit 0
}

# --- Manual portal connection step ------------------------------------------
if (-not $ConnectionId -and $saved -and $saved.ConnectionId) {
    # Remembered connection id - offer it as the default; press Enter to reuse it.
    $entered = (Read-Host "Cosmos connection id [$($saved.ConnectionId)] (Enter to reuse)").Trim()
    $ConnectionId = if ([string]::IsNullOrWhiteSpace($entered)) { $saved.ConnectionId } else { $entered }
}
if (-not $ConnectionId) {
    $cosmosEndpoint = ''
    Push-Location $WorkshopRoot
    try {
        $cosmosEndpoint = (azd env get-values 2>$null |
            Select-String -Pattern '^COSMOSDB_ENDPOINT=' |
            ForEach-Object { ($_ -split '=', 2)[1].Trim().Trim('"') } |
            Select-Object -First 1)
    }
    finally {
        Pop-Location
    }
    Write-Section 'Manual step - create the Cosmos connection (one time)'
    Write-Host 'You only need to create a CONNECTION object here - this script creates the' -ForegroundColor Yellow
    Write-Host 'mirrored database itself, using the connection id you provide below.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'In the Microsoft Fabric portal (https://app.fabric.microsoft.com):'
    Write-Host '  1. Click  Settings (gear, top-right)  ->  Manage connections and gateways.'
    Write-Host '     (This is a tenant-level setting, not your workspace settings.)'
    Write-Host '  2. On the  Connections  tab, click  + New.'
    Write-Host '  3. Connection type:  Azure Cosmos DB for NoSQL.'
    if ($cosmosEndpoint) {
        Write-Host "     Account / URL:  $cosmosEndpoint"
    }
    Write-Host '     Authentication method:  OAuth 2.0 (Organizational account)  ->  sign in,'
    Write-Host '     then click  Create.'
    Write-Host '  4. Open the new connection  ->  Settings and copy its  Connection ID  (a GUID).'
    Write-Host '     Do NOT start the "New mirrored database" wizard - this script does that step.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host 'Paste tip: use Ctrl+Shift+V to paste at the prompt below (in the VS Code' -ForegroundColor DarkGray
    Write-Host 'terminal, Ctrl+V shows a literal ^V). Or press Enter to exit and re-run:' -ForegroundColor DarkGray
    Write-Host '  .\Provision-Fabric.ps1 -ConnectionId <id>' -ForegroundColor DarkGray
    Write-Host ''
    $ConnectionId = (Read-Host 'Paste the Cosmos connection id here (Ctrl+Shift+V to paste), or press Enter to stop').Trim()
    if ([string]::IsNullOrWhiteSpace($ConnectionId)) {
        Write-Host 'No connection id provided - stopping after Phase 1. Re-run with -ConnectionId when ready.'
        exit 0
    }
}

# --- Phase 2 -----------------------------------------------------------------
Save-State
Write-Section 'Phase 2 - mirrored database + Module 09 notebook'
Invoke-Provision @('--phase', '2', '--connection-id', $ConnectionId)
if ($script:provisionExit -ne 0) { Fail "Phase 2 failed (exit $script:provisionExit). See the output above." }

Write-Section 'Done'
Write-Host 'Fabric analytics provisioned.' -ForegroundColor Green
Write-Host 'FABRIC_WORKSPACE_ID and FABRIC_MIRROR_ID were saved to your azd environment.'
Write-Host ''
Write-Host 'The funnel_demo analytics dataset was seeded during azd up, so the mirror already'
Write-Host 'has data to replicate. In the Fabric portal, open your workspace and confirm you see:'
Write-Host '  - a mirrored database that is replicating the Cosmos containers,'
Write-Host '  - the ConversionFunnelReverseETL notebook, and'
Write-Host '  - the optimization-apply-loop User Data Function (Power BI Apply/Revert).'
Write-Host 'Then continue with Module 09, Activity 2 (open the notebook and run sections 1 and 2).'
