[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$OutputPath,
    [switch]$LaunchAfterBuild,
    [int]$WaitForPid = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}

$source = Join-Path $ProjectRoot 'src\launcher\CodexBridgeLauncher.cs'
$uiSource = Join-Path $ProjectRoot 'src\launcher\LauncherUiText.cs'
$updateCheckerSource = Join-Path $ProjectRoot 'src\launcher\ReleaseUpdateChecker.cs'
$proj = Join-Path $ProjectRoot 'src\launcher\CodexBridgeLauncher.csproj'
$icon = Join-Path $ProjectRoot 'assets\CodexBridgeLauncher.ico'
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $buildDir = Join-Path $ProjectRoot '.build'
    New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
    $OutputPath = Join-Path $buildDir 'CodexBridgeLauncher.exe'
} else {
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Source not found: $source" }
if (-not (Test-Path -LiteralPath $uiSource -PathType Leaf)) { throw "Source not found: $uiSource" }
if (-not (Test-Path -LiteralPath $updateCheckerSource -PathType Leaf)) { throw "Source not found: $updateCheckerSource" }

if ($WaitForPid -gt 0) {
    try {
        $old = Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue
        if ($null -ne $old) { $old.WaitForExit(15000) | Out-Null }
    } catch { }
}

$candidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }

if ($candidates.Count -gt 0) {
    $csc = $candidates[0]
    Write-Host "Building CodexBridgeLauncher.exe with: $csc" -ForegroundColor Cyan
    $compilerArgs = @(
        '/nologo', '/target:winexe', '/optimize+', '/platform:anycpu',
        '/reference:System.dll', '/reference:System.Core.dll',
        '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll',
        "/out:$OutputPath"
    )
    if (Test-Path -LiteralPath $icon -PathType Leaf) { $compilerArgs += "/win32icon:$icon" }
    $compilerArgs += @($uiSource, $updateCheckerSource, $source)
    & $csc @compilerArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "csc.exe failed with exit code $LASTEXITCODE"
    }
} else {
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $dotnet) {
        throw 'No Windows C# compiler was available. Enable the built-in .NET Framework components or install a current .NET SDK, then run Start CodexBridge.cmd again.'
    }
    Write-Host 'Legacy csc.exe was not found; trying dotnet/MSBuild project build.' -ForegroundColor Cyan
    & $dotnet.Source build $proj -c Release
    if ($LASTEXITCODE -ne 0) { throw "dotnet build failed with exit code $LASTEXITCODE" }
    $built = Get-ChildItem -Path (Join-Path (Split-Path -Parent $proj) 'bin\Release') -Filter 'CodexBridgeLauncher.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $built) { throw 'Build succeeded but CodexBridgeLauncher.exe was not found.' }
    Copy-Item -LiteralPath $built.FullName -Destination $OutputPath -Force
}

Write-Host "Built: $OutputPath" -ForegroundColor Green
if ($LaunchAfterBuild) { Start-Process -FilePath $OutputPath -WorkingDirectory (Split-Path -Parent $OutputPath) }
