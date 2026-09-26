<#
.SYNOPSIS
    Thin launcher for the canonical Python Fabric provisioner.

.DESCRIPTION
    Every argument is forwarded unchanged to provision_fabric.py. All orchestration,
    prompting, state handling, deployment, validation, and evidence generation live in
    Python. The Python process exit code is preserved.

.EXAMPLE
    .\Provision-Fabric.ps1 --environment staging --solution `
      --verify-semantic-model --verify-report --evidence-output .local\fabric-evidence.json
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$provisioner = Join-Path $PSScriptRoot 'provision_fabric.py'
& python $provisioner @Arguments
exit $LASTEXITCODE
