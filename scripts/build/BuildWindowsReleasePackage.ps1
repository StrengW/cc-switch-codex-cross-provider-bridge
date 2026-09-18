[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$OutputDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ProjectRoot 'dist'
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# The public Windows artifact intentionally contains no prebuilt executable.
# Users launch Start CodexBridge.cmd; the existing, tested source bootstrap
# prepares a user-local Python runtime and compiles the small tray launcher on
# the user's own machine. This avoids distributing the old unsigned custom
# self-extracting Setup EXE + PyInstaller one-file combination that triggered
# antivirus ML heuristics, without changing Bridge/Launcher runtime semantics.
$stage = Join-Path $ProjectRoot '.build\windows-release-package'
$archive = Join-Path $OutputDir 'CodexBridge-Windows.zip'
$checksum = $archive + '.sha256'
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $checksum -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $stage -Force | Out-Null

$files = @(
    'Start CodexBridge.cmd',
    'Uninstall CodexBridge.cmd',
    'README.md',
    'README.en.md',
    'LICENSE',
    'SECURITY.md',
    'assets\CodexBridgeLauncher.ico',
    'docs\ARCHITECTURE.md',
    'src\bridge\codex_provider_bridge.py',
    'src\launcher\CodexBridgeLauncher.cs',
    'src\launcher\CodexBridgeLauncher.csproj',
    'scripts\build\BuildCodexBridgeLauncher.ps1',
    'scripts\windows\StartCodexBridge.ps1',
    'scripts\windows\codex_bridge_manager.ps1',
    'scripts\windows\UninstallCodexBridge.ps1'
)

foreach ($relative in $files) {
    $source = Join-Path $ProjectRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required Windows release file is missing: $relative"
    }
    $destination = Join-Path $stage $relative
    $parent = Split-Path -Parent $destination
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

# Defense-in-depth: formal Windows Release assets must not accidentally regress
# to shipping an unsigned executable, PyInstaller bundle, or legacy Setup EXE.
$prebuiltExecutables = @(Get-ChildItem -LiteralPath $stage -Recurse -File -Filter '*.exe' -ErrorAction SilentlyContinue)
if ($prebuiltExecutables.Count -ne 0) {
    throw ('Windows release package unexpectedly contains executable(s): ' + (($prebuiltExecutables | ForEach-Object FullName) -join ', '))
}
if (Test-Path -LiteralPath (Join-Path $stage 'src\setup')) {
    throw 'Legacy Setup source must not be included in the normal-user Windows Release package.'
}

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  CodexBridge-Windows.zip" | Set-Content -LiteralPath $checksum -Encoding ascii

Write-Host "Built: $archive" -ForegroundColor Green
Write-Host "SHA-256: $hash" -ForegroundColor DarkGray
