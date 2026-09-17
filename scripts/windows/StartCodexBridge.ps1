[CmdletBinding()]
param(
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-CodexBridgeFullPath {
    param(
        [AllowNull()][string]$Path,
        [Parameter(Mandatory = $true)][string]$Fallback
    )
    $candidate = if ([string]::IsNullOrWhiteSpace($Path)) { $Fallback } else { $Path }
    $candidate = ([string]$candidate).Trim().Trim([char]34).Trim([char]39)
    if ([string]::IsNullOrWhiteSpace($candidate)) { throw 'CodexBridge project path resolved to an empty value.' }
    try { return [IO.Path]::GetFullPath($candidate) }
    catch { throw "Invalid CodexBridge project path '$candidate': $($_.Exception.Message)" }
}

function Test-Python310 {
    param([string]$PythonExe)
    if ([string]::IsNullOrWhiteSpace($PythonExe) -or -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { return $false }
    try {
        & $PythonExe -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-SystemPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        try {
            $p = (& $py.Source -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
            if (-not [string]::IsNullOrWhiteSpace($p)) { $candidates.Add($p.Trim()) }
        } catch { }
    }
    foreach ($name in @('python.exe','python')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd -and -not $candidates.Contains($cmd.Source)) { $candidates.Add($cmd.Source) }
    }
    foreach ($candidate in $candidates) { if (Test-Python310 $candidate) { return [IO.Path]::GetFullPath($candidate) } }
    return $null
}

function Get-WindowsPythonPackageName {
    $arch = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432')
    if ([string]::IsNullOrWhiteSpace($arch)) { $arch = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITECTURE') }
    switch -Regex ($arch) {
        'ARM64' { return 'python-3.12.10-embed-arm64.zip' }
        'AMD64|IA64' { return 'python-3.12.10-embed-amd64.zip' }
        '^x86$' { return 'python-3.12.10-embed-win32.zip' }
        default { return 'python-3.12.10-embed-amd64.zip' }
    }
}

function Ensure-PortablePython {
    param([string]$StateRoot)
    $runtimeRoot = Join-Path $StateRoot 'runtime\python'
    $portablePython = Join-Path $runtimeRoot 'python.exe'
    if (Test-Python310 $portablePython) { return $portablePython }

    # An existing user Python is a valid offline fallback. We still prefer our
    # user-local runtime when it can be downloaded, so later repo moves do not matter.
    $systemPython = Find-SystemPython
    $package = Get-WindowsPythonPackageName
    $url = "https://www.python.org/ftp/python/3.12.10/$package"
    $downloadRoot = Join-Path $StateRoot 'downloads'
    $zip = Join-Path $downloadRoot $package
    $tempRuntime = "$runtimeRoot.tmp-$PID"
    New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
    Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue

    try {
        Write-Host '[CodexBridge] Preparing private Python runtime (first run only)...' -ForegroundColor Cyan
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
        New-Item -ItemType Directory -Path $tempRuntime -Force | Out-Null
        Expand-Archive -LiteralPath $zip -DestinationPath $tempRuntime -Force
        $candidate = Join-Path $tempRuntime 'python.exe'
        if (-not (Test-Python310 $candidate)) { throw 'Downloaded Python runtime did not start correctly.' }
        Remove-Item -LiteralPath $runtimeRoot -Recurse -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $tempRuntime -Destination $runtimeRoot -Force
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Write-Host '[CodexBridge] Private Python runtime is ready.' -ForegroundColor Green
        return $portablePython
    } catch {
        Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($systemPython)) {
            Write-Warning "Could not download the private Python runtime; using existing Python instead: $systemPython"
            return $systemPython
        }
        throw "Could not prepare Python automatically. Check internet access to python.org and try again. $($_.Exception.Message)"
    }
}

$ProjectRoot = Resolve-CodexBridgeFullPath -Path $ProjectRoot -Fallback (Join-Path $PSScriptRoot '..\..')
$stateRoot = Join-Path $env:LOCALAPPDATA 'CodexProviderBridge'
$bootstrapDir = Join-Path $stateRoot 'source-bootstrap'
New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null

$python = Ensure-PortablePython -StateRoot $stateRoot
[Environment]::SetEnvironmentVariable('CPB_PYTHON', $python, 'Process')

# Source quick-start is also an in-place updater for an existing installed copy.
# A packaged install may have left codex_provider_bridge.exe in the stable app
# directory. The manager intentionally prefers that EXE over the Python source,
# so merely copying a newer codex_provider_bridge.py would silently keep running
# the stale packaged Bridge. Stop the resident installed copy and remove only the
# stale Bridge EXE before relaunching from this source tree.
$installedAppDir = Join-Path $stateRoot 'app'
if (Test-Path -LiteralPath $installedAppDir -PathType Container) {
    Write-Host '[CodexBridge] Preparing installed copy for source update...' -ForegroundColor Cyan

    # Stop installed launcher/tray/watcher processes first so the CC Switch
    # trigger watcher cannot immediately race the Bridge stop and relaunch the
    # old packaged runtime while this update is being applied.
    Get-Process -Name 'CodexBridgeLauncher' -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $processPath = $_.Path
            if (-not [string]::IsNullOrWhiteSpace($processPath)) {
                $processDir = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($processPath))
                if ([string]::Equals($processDir.TrimEnd('\\'), [IO.Path]::GetFullPath($installedAppDir).TrimEnd('\\'), [StringComparison]::OrdinalIgnoreCase)) {
                    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                }
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 300

    $installedManager = Join-Path $installedAppDir 'codex_bridge_manager.ps1'
    if (Test-Path -LiteralPath $installedManager -PathType Leaf) {
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installedManager stop | Out-Host
        } catch {
            Write-Warning "Could not stop the previous resident Bridge cleanly before source update: $($_.Exception.Message)"
        }
    }

    $staleStandaloneBridge = Join-Path $installedAppDir 'codex_provider_bridge.exe'
    if (Test-Path -LiteralPath $staleStandaloneBridge -PathType Leaf) {
        try {
            Remove-Item -LiteralPath $staleStandaloneBridge -Force
            Write-Host '[CodexBridge] Removed stale packaged Bridge EXE so the updated source Bridge is selected.' -ForegroundColor DarkGray
        } catch {
            throw "Could not replace the installed Bridge runtime because the old standalone EXE is still locked: $($_.Exception.Message)"
        }
    }
}

$bridgeSource = Join-Path $ProjectRoot 'src\bridge\codex_provider_bridge.py'
$managerSource = Join-Path $ProjectRoot 'scripts\windows\codex_bridge_manager.ps1'
$uninstallerSource = Join-Path $ProjectRoot 'scripts\windows\UninstallCodexBridge.ps1'
$iconSource = Join-Path $ProjectRoot 'assets\CodexBridgeLauncher.ico'
$builder = Join-Path $ProjectRoot 'scripts\build\BuildCodexBridgeLauncher.ps1'
$launcher = Join-Path $bootstrapDir 'CodexBridgeLauncher.exe'

foreach ($required in @($bridgeSource, $managerSource, $uninstallerSource, $builder)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required CodexBridge file is missing: $required" }
}

Copy-Item -LiteralPath $bridgeSource -Destination (Join-Path $bootstrapDir 'codex_provider_bridge.py') -Force
Copy-Item -LiteralPath $managerSource -Destination (Join-Path $bootstrapDir 'codex_bridge_manager.ps1') -Force
Copy-Item -LiteralPath $uninstallerSource -Destination (Join-Path $bootstrapDir 'UninstallCodexBridge.ps1') -Force
if (Test-Path -LiteralPath $iconSource -PathType Leaf) {
    Copy-Item -LiteralPath $iconSource -Destination (Join-Path $bootstrapDir 'CodexBridgeLauncher.ico') -Force
}

Write-Host '[CodexBridge] Building the tiny Windows tray launcher locally...' -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $builder -ProjectRoot $ProjectRoot -OutputPath $launcher
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw 'Could not build CodexBridgeLauncher.exe with the Windows .NET compiler.'
}

Write-Host '[CodexBridge] Starting Codex Bridge...' -ForegroundColor Green
Write-Host 'After this first run, opening CC Switch will wake Codex Bridge automatically.' -ForegroundColor DarkGray
Start-Process -FilePath $launcher -WorkingDirectory $bootstrapDir
