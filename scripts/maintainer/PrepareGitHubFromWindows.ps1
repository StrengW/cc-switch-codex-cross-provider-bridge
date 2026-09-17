[CmdletBinding()]
param([string]$ProjectRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git') -PathType Container)) {
    throw "Not a Git working tree: $ProjectRoot"
}
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if ($null -eq $git) { $git = Get-Command git -ErrorAction SilentlyContinue }
if ($null -eq $git) { throw 'Git was not found on PATH.' }
Push-Location $ProjectRoot
try {
    & $git.Source update-index --add --chmod=+x -- 'Start CodexBridge.command'
    & $git.Source update-index --add --chmod=+x -- 'scripts/unix/codex_bridge_manager.sh'
    & $git.Source update-index --add --chmod=+x -- 'scripts/unix/codex_bridge_watcher.sh'
    if ($LASTEXITCODE -ne 0) { throw "git update-index failed with exit code $LASTEXITCODE" }
    Write-Host 'macOS executable bits are recorded in the Git index.' -ForegroundColor Green
    Write-Host 'Now commit and push normally.'
} finally {
    Pop-Location
}
