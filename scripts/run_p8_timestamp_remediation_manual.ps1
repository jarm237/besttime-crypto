# Project-root entry point for the sealed P8 timestamp-remediation runner.

[CmdletBinding()]
param(
    [ValidateSet("start", "status", "stop", "foreground")]
    [string]$Mode = "start"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Runner = Join-Path $ProjectRoot "runtime\worktrees\timestamp-remediation-20260901-01\scripts\run_p8_timestamp_remediation_manual.ps1"

if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Sealed timestamp-remediation runner not found: $Runner"
}

& powershell -ExecutionPolicy Bypass -File $Runner -Mode $Mode
exit $LASTEXITCODE
