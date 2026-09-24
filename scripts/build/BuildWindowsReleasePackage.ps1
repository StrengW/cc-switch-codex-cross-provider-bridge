[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$OutputDir,
    # Directory holding the official python.org embeddable archives to ship inside
    # the Release. They are copied through untouched: re-packing upstream bytes
    # would make the pinned digest meaningless and the origin harder to verify.
    [string]$BundledRuntimeDir
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

# The public Windows artifact intentionally contains no executable we built.
# Users launch Start CodexBridge.cmd; the existing, tested source bootstrap
# prepares a user-local Python runtime and compiles the small tray launcher on
# the user's own machine. The antivirus rule this encodes is about our own
# unsigned binaries: the self-extracting Setup EXE and a frozen one-file bundle
# both tripped ML heuristics. An upstream publisher's runtime archive, pinned by
# version, source, and SHA-256, is a different thing and is allowed through,
# because requiring python.org to be reachable during the first run was the
# single biggest reason Windows users could not install at all.
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
    'VERSION',
    'CHANGELOG.md',
    'LICENSE',
    'SECURITY.md',
    'assets\CodexBridgeLauncher.ico',
    'docs\ARCHITECTURE.md',
    'docs\COMPATIBILITY.md',
    'docs\VERSIONING.md',
    'docs\PROJECT_OVERVIEW.zh-CN.md',
    'src\bridge\codex_provider_bridge.py',
    'src\launcher\CodexBridgeLauncher.cs',
    'src\launcher\LauncherUiText.cs',
    'src\launcher\ReleaseUpdateChecker.cs',
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

# Ship the upstream runtime archive so a first run never depends on reaching
# python.org. Only amd64 is bundled: it covers nearly every Windows user, and
# arm64/x86 keep using the mirror download built into StartCodexBridge.ps1.
$bundledRuntimeDigests = @{
    'python-3.12.10-embed-amd64.zip' = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
}
if (-not [string]::IsNullOrWhiteSpace($BundledRuntimeDir)) {
    $BundledRuntimeDir = [IO.Path]::GetFullPath($BundledRuntimeDir)
    $runtimeStage = Join-Path $stage 'runtime'
    New-Item -ItemType Directory -Path $runtimeStage -Force | Out-Null
    foreach ($runtimeName in $bundledRuntimeDigests.Keys) {
        $runtimeSource = Join-Path $BundledRuntimeDir $runtimeName
        if (-not (Test-Path -LiteralPath $runtimeSource -PathType Leaf)) {
            throw "Bundled Python runtime archive is missing: $runtimeSource"
        }
        $runtimeActual = (Get-FileHash -LiteralPath $runtimeSource -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($runtimeActual -ne $bundledRuntimeDigests[$runtimeName]) {
            throw "Bundled Python runtime digest mismatch for ${runtimeName}: expected $($bundledRuntimeDigests[$runtimeName]), got $runtimeActual"
        }
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $runtimeStage $runtimeName) -Force
        Write-Host "Bundled runtime verified: $runtimeName" -ForegroundColor DarkGray
    }
} else {
    Write-Warning 'No -BundledRuntimeDir given; this package will rely on the first-run download.'
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

function Wait-StageReadable {
    param([Parameter(Mandatory = $true)][string]$Stage)
    # A freshly copied multi-megabyte archive is routinely still held open by a
    # real-time scanner, and Compress-Archive fails outright on a locked source.
    # Polling for readability keeps the release build from failing at random on a
    # machine that is otherwise completely healthy.
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ($true) {
        $locked = @()
        foreach ($file in @(Get-ChildItem -LiteralPath $Stage -Recurse -File)) {
            try {
                $stream = [IO.File]::Open($file.FullName, 'Open', 'Read', 'None')
                $stream.Close()
            } catch {
                $locked += $file.FullName
            }
        }
        if ($locked.Count -eq 0) { return }
        if ([DateTime]::UtcNow -ge $deadline) {
            throw ('Staged release files are still locked: ' + ($locked -join ', '))
        }
        Start-Sleep -Milliseconds 500
    }
}

Wait-StageReadable -Stage $stage
$compressAttempts = 0
while ($true) {
    $compressAttempts++
    try {
        Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal -ErrorAction Stop
        break
    } catch {
        # Readability can be lost again between the check above and the archive
        # call, so retry a couple of times before treating it as a real failure.
        if ($compressAttempts -ge 3) { throw }
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  CodexBridge-Windows.zip" | Set-Content -LiteralPath $checksum -Encoding ascii

Write-Host "Built: $archive" -ForegroundColor Green
Write-Host "SHA-256: $hash" -ForegroundColor DarkGray
