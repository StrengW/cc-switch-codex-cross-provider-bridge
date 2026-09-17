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
if ([string]::IsNullOrWhiteSpace($OutputDir)) { $OutputDir = Join-Path $ProjectRoot 'dist' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

function Find-Csc {
    $candidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    $cmd = Get-Command csc.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw 'C# compiler csc.exe was not found. This optional release builder needs .NET Framework 4.8 Developer Pack or a current .NET SDK.'
}

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$FilePath exited with code $LASTEXITCODE" }
}

$standaloneBuild = Join-Path $ProjectRoot 'scripts\build\BuildStandaloneBridge.ps1'
$standaloneBridge = Join-Path $ProjectRoot '.build\bridge\codex_provider_bridge.exe'
if (-not (Test-Path -LiteralPath $standaloneBridge -PathType Leaf)) {
    Write-Host 'Building standalone codex_provider_bridge.exe...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $standaloneBuild -ProjectRoot $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Standalone Bridge build failed with code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $standaloneBridge -PathType Leaf)) {
    throw 'Standalone codex_provider_bridge.exe was not produced. End-user releases must not depend on Python.'
}

$launcherBuild = Join-Path $ProjectRoot 'scripts\build\BuildCodexBridgeLauncher.ps1'
$launcherExe = Join-Path $ProjectRoot '.build\CodexBridgeLauncher.exe'
Write-Host 'Building CodexBridgeLauncher.exe...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcherBuild -ProjectRoot $ProjectRoot -OutputPath $launcherExe
if ($LASTEXITCODE -ne 0) { throw "Launcher build failed with code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath $launcherExe)) { throw 'CodexBridgeLauncher.exe was not produced.' }

$payloadDir = Join-Path $ProjectRoot '.build\setup-payload'
$payloadZip = Join-Path $ProjectRoot '.build\CodexBridgePayload.zip'
Remove-Item -LiteralPath $payloadDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $payloadZip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $payloadDir -Force | Out-Null

$payloadFiles = @(
    @{ Source = $launcherExe; Name = 'CodexBridgeLauncher.exe'; Required = $true },
    @{ Source = $standaloneBridge; Name = 'codex_provider_bridge.exe'; Required = $true },
    @{ Source = (Join-Path $ProjectRoot 'src\bridge\codex_provider_bridge.py'); Name = 'codex_provider_bridge.py'; Required = $false },
    @{ Source = (Join-Path $ProjectRoot 'scripts\windows\codex_bridge_manager.ps1'); Name = 'codex_bridge_manager.ps1'; Required = $true },
    @{ Source = (Join-Path $ProjectRoot 'scripts\windows\UninstallCodexBridge.ps1'); Name = 'UninstallCodexBridge.ps1'; Required = $true },
    @{ Source = (Join-Path $ProjectRoot 'scripts\unix\codex_bridge_manager.sh'); Name = 'codex_bridge_manager.sh'; Required = $false },
    @{ Source = (Join-Path $ProjectRoot 'assets\CodexBridgeLauncher.ico'); Name = 'CodexBridgeLauncher.ico'; Required = $false }
)
foreach ($item in $payloadFiles) {
    if (-not (Test-Path -LiteralPath $item.Source)) {
        if ($item.Required) { throw "Required payload file missing: $($item.Source)" }
        continue
    }
    Copy-Item -LiteralPath $item.Source -Destination (Join-Path $payloadDir $item.Name) -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($payloadDir, $payloadZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

$setupExe = Join-Path $OutputDir 'CodexBridge-Setup.exe'
Remove-Item -LiteralPath $setupExe -Force -ErrorAction SilentlyContinue
$csc = Find-Csc
$refs = @(
    '/reference:System.dll',
    '/reference:System.Core.dll',
    '/reference:System.Windows.Forms.dll',
    '/reference:System.IO.Compression.dll',
    '/reference:System.IO.Compression.FileSystem.dll'
)
$args = @('/nologo','/target:winexe','/optimize+','/platform:anycpu',('/out:' + $setupExe),('/resource:' + $payloadZip + ',CodexBridgePayload.zip')) + $refs
$icon = Join-Path $ProjectRoot 'assets\CodexBridgeLauncher.ico'
if (Test-Path -LiteralPath $icon) { $args += ('/win32icon:' + $icon) }
$args += (Join-Path $ProjectRoot 'src\setup\CodexBridgeSetup.cs')
Write-Host 'Building CodexBridge-Setup.exe...'
Invoke-Checked -FilePath $csc -Arguments $args

Remove-Item -LiteralPath $payloadDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $payloadZip -Force -ErrorAction SilentlyContinue
Write-Host "Built: $setupExe" -ForegroundColor Green
