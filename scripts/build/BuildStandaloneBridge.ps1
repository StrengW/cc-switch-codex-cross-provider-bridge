[CmdletBinding()]
param(
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}

$source = Join-Path $ProjectRoot 'src\bridge\codex_provider_bridge.py'
$outDir = Join-Path $ProjectRoot '.build\bridge'
$workDir = Join-Path $ProjectRoot '.build\pyinstaller-work'
$specDir = Join-Path $ProjectRoot '.build\pyinstaller-spec'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Bridge source not found: $source" }
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -eq $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if ($null -eq $python) { throw 'Python 3.10+ is required only for this optional standalone developer build. Normal repository quick-start bootstraps its own runtime.' }

# Windows PowerShell 5.1 can promote stderr from a native command to a terminating
# NativeCommandError when $ErrorActionPreference is 'Stop'. Probe availability with
# importlib instead of intentionally running a missing module.
$pyInstallerProbe = & $python.Source -c "import importlib.util; print('1' if importlib.util.find_spec('PyInstaller') else '0')"
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Python environment for PyInstaller.' }
$pyInstallerAvailable = (($pyInstallerProbe | Select-Object -Last 1) -as [string]).Trim() -eq '1'
if (-not $pyInstallerAvailable) {
    Write-Host 'Installing PyInstaller for this build...' -ForegroundColor Cyan
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python.Source -m pip install --disable-pip-version-check pyinstaller
        $pipExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($pipExitCode -ne 0) { throw 'Could not install PyInstaller.' }
}

$savedErrorActionPreference = $ErrorActionPreference
try {
    # PyInstaller may emit normal build diagnostics on stderr. Let the native process
    # finish and use its exit code instead of treating diagnostics as PowerShell errors.
    $ErrorActionPreference = 'Continue'
    & $python.Source -m PyInstaller --onefile --name codex_provider_bridge --distpath $outDir --workpath $workDir --specpath $specDir $source
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedErrorActionPreference
}
if ($pyInstallerExitCode -ne 0) { throw "PyInstaller exited with code $pyInstallerExitCode" }
$exe = Join-Path $outDir 'codex_provider_bridge.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Standalone bridge build did not produce codex_provider_bridge.exe.' }
Write-Host "Built: $exe" -ForegroundColor Green
