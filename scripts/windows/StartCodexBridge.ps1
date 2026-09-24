[CmdletBinding()]
param(
    [string]$ProjectRoot,
    # Lets CI and support prove the runtime selection in isolation. The real
    # state root is renamed, never deleted, before a cold-start test.
    [string]$StateRootOverride,
    [switch]$PrepareRuntimeOnly
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

# A first run has to download an official python.org embeddable build. python.org
# alone is not enough: it is routinely unreachable or extremely slow for users in
# mainland China, and Invoke-WebRequest without -TimeoutSec waits forever, so the
# script used to hang silently on "Preparing private Python runtime" and report no
# error at all. The mirrors below serve byte-identical copies of the same artifact
# and the pinned SHA-256 proves that per download, so falling back to a mirror can
# never substitute a different runtime.
$script:PythonRuntimeMirrors = @(
    'https://www.python.org/ftp/python/3.12.10',
    'https://mirrors.huaweicloud.com/python/3.12.10',
    'https://registry.npmmirror.com/-/binary/python/3.12.10'
)
$script:PythonRuntimeDigests = @{
    'python-3.12.10-embed-amd64.zip' = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
    'python-3.12.10-embed-arm64.zip' = '3065efc3d382d1cda66757ac71ade11904fa6e350f5a97eb74811acd71ba5532'
    'python-3.12.10-embed-win32.zip' = '084b9eb24cb848605c895d05b738fbc2572efc8b4c18c415a824065864a2b853'
}

function Write-BootstrapLog {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$Message
    )
    try {
        $line = '[{0:yyyy-MM-dd HH:mm:ss}] {1}' -f [DateTime]::Now, $Message
        Add-Content -LiteralPath (Join-Path $StateRoot 'bootstrap.log') -Value $line -Encoding UTF8
    } catch { }
}

function Get-BootstrapText {
    # Same culture detection as UninstallCodexBridge.ps1, so the first-run console
    # and the uninstall dialog speak the same language to the same user.
    $culture = [Globalization.CultureInfo]::CurrentUICulture.Name
    $traditional = $culture -match '^(zh-TW|zh-HK|zh-MO)' -or $culture -like 'zh-Hant*'
    if ($culture -like 'zh*') {
        if ($traditional) {
            return @{
                Preparing = '[CodexBridge] 正在準備專用 Python 執行階段（僅首次執行需要，約 11 MB）...'
                Ready = '[CodexBridge] 專用 Python 執行階段已就緒。'
                FallbackWarning = '無法下載專用 Python 執行階段，改用本機已安裝的 Python：'
                DownloadFailed = "首次執行需要聯網取得 Python 執行階段，但 python.org 與兩個鏡像都未能完成下載。`r`n請檢查網路或代理設定後，重新雙擊 Start CodexBridge.cmd；也可以先自行安裝 Python 3.10 或更新版本，腳本會自動改用它。"
                PreparingBundled = '[CodexBridge] 正在安裝隨包附帶的 Python 執行階段（無需聯網）...'
                BundledRejected = '隨包執行階段不可用，改為聯網取得：'
                SeeLog = '完整失敗原因已記錄到：'
            }
        }
        return @{
            Preparing = '[CodexBridge] 正在准备专用 Python 运行时（仅首次运行需要，约 11 MB）...'
            Ready = '[CodexBridge] 专用 Python 运行时已就绪。'
            FallbackWarning = '无法下载专用 Python 运行时，改用本机已安装的 Python：'
            DownloadFailed = "首次运行需要联网获取 Python 运行时，但 python.org 与两个国内镜像都未能完成下载。`r`n请检查网络或代理设置后，重新双击 Start CodexBridge.cmd；也可以先自行安装 Python 3.10 或更高版本，脚本会自动改用它。"
            PreparingBundled = '[CodexBridge] 正在安装随包附带的 Python 运行时（无需联网）...'
            BundledRejected = '随包运行时不可用，改为联网获取：'
            SeeLog = '完整失败原因已记录到：'
        }
    }
    return @{
        Preparing = '[CodexBridge] Preparing private Python runtime (first run only, about 11 MB)...'
        Ready = '[CodexBridge] Private Python runtime is ready.'
        FallbackWarning = 'Could not download the private Python runtime; using existing Python instead:'
        DownloadFailed = "The first run has to download a Python runtime, but python.org and both mirrors failed.`r`nCheck your network or proxy and run Start CodexBridge.cmd again. Installing Python 3.10 or newer yourself also works: the script then uses that instead."
        PreparingBundled = '[CodexBridge] Installing the bundled Python runtime (no download needed)...'
        BundledRejected = 'The bundled runtime was rejected; falling back to a download:'
        SeeLog = 'Full failure details were written to:'
    }
}

function Get-PythonRuntimePackage {
    param(
        [Parameter(Mandatory = $true)][string]$Package,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$StateRoot
    )
    if (-not $script:PythonRuntimeDigests.ContainsKey($Package)) {
        throw "No pinned SHA-256 for Python runtime package '$Package'."
    }
    $expected = $script:PythonRuntimeDigests[$Package]
    $failures = New-Object System.Collections.Generic.List[string]
    # The progress stream costs more than the transfer itself on Windows PowerShell.
    $ProgressPreference = 'SilentlyContinue'
    foreach ($mirror in $script:PythonRuntimeMirrors) {
        $url = "$mirror/$Package"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination -TimeoutSec 60
            $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $expected) { throw "SHA-256 mismatch: expected $expected, got $actual" }
            return $url
        } catch {
            Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
            $failures.Add("$url -> $($_.Exception.Message)")
        }
    }
    $detail = $failures -join [Environment]::NewLine
    Write-BootstrapLog -StateRoot $StateRoot -Message "Python runtime download failed:$([Environment]::NewLine)$detail"
    throw "Every Python runtime source failed.$([Environment]::NewLine)$detail"
}

function Install-PythonRuntimeFromZip {
    param(
        [Parameter(Mandatory = $true)][string]$Zip,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    # The bundled artifact and a mirror download are the same official python.org
    # embeddable build, so both clear the identical pinned digest before anything
    # is extracted. Nothing reaches the runtime directory unverified.
    $actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256) {
        throw "Python runtime digest mismatch: expected $ExpectedSha256, got $actual ($Zip)"
    }

    $tempRuntime = "$RuntimeRoot.tmp-$PID"
    Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $tempRuntime -Force | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $tempRuntime -Force
    if (-not (Test-Python310 (Join-Path $tempRuntime 'python.exe'))) {
        Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue
        throw 'Python runtime did not start correctly after extraction.'
    }
    Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $tempRuntime -Destination $RuntimeRoot -Force
}

function Ensure-PortablePython {
    param([string]$StateRoot, [string]$ProjectRoot)
    $runtimeRoot = Join-Path $StateRoot 'runtime\python'
    $portablePython = Join-Path $runtimeRoot 'python.exe'
    if (Test-Python310 $portablePython) { return $portablePython }

    $text = Get-BootstrapText
    # An existing user Python is a valid offline fallback. We still prefer our
    # user-local runtime when it can be prepared, so later repo moves do not matter.
    $systemPython = Find-SystemPython
    $package = Get-WindowsPythonPackageName
    if (-not $script:PythonRuntimeDigests.ContainsKey($package)) {
        throw "No pinned SHA-256 for Python runtime package '$package'."
    }
    $expected = $script:PythonRuntimeDigests[$package]
    $tempRuntime = "$runtimeRoot.tmp-$PID"

    # The Release ZIP carries the official python.org embeddable build, so the
    # normal case needs no reachable python.org at all. Order: bundled artifact,
    # then the mirrors, then a Python the user already installed.
    $bundled = Join-Path $ProjectRoot "runtime\$package"
    if (Test-Path -LiteralPath $bundled -PathType Leaf) {
        try {
            Write-Host $text.PreparingBundled -ForegroundColor Cyan
            Write-BootstrapLog -StateRoot $StateRoot -Message "Installing bundled Python runtime from $bundled."
            Install-PythonRuntimeFromZip -Zip $bundled -RuntimeRoot $runtimeRoot -ExpectedSha256 $expected
            Write-Host $text.Ready -ForegroundColor Green
            Write-BootstrapLog -StateRoot $StateRoot -Message 'Private Python runtime ready from the bundled package.'
            return $portablePython
        } catch {
            Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue
            Write-BootstrapLog -StateRoot $StateRoot -Message "Bundled runtime rejected: $($_.Exception.Message)"
            Write-Warning "$($text.BundledRejected) $($_.Exception.Message)"
        }
    }

    $downloadRoot = Join-Path $StateRoot 'downloads'
    $zip = Join-Path $downloadRoot $package
    New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null

    try {
        Write-Host $text.Preparing -ForegroundColor Cyan
        Write-BootstrapLog -StateRoot $StateRoot -Message "Preparing private Python runtime ($package)."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $usedSource = Get-PythonRuntimePackage -Package $package -Destination $zip -StateRoot $StateRoot
        Install-PythonRuntimeFromZip -Zip $zip -RuntimeRoot $runtimeRoot -ExpectedSha256 $expected
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Write-Host $text.Ready -ForegroundColor Green
        Write-BootstrapLog -StateRoot $StateRoot -Message "Private Python runtime ready from $usedSource."
        return $portablePython
    } catch {
        Remove-Item -LiteralPath $tempRuntime -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Write-BootstrapLog -StateRoot $StateRoot -Message "Runtime preparation failed: $($_.Exception.Message)"
        if (-not [string]::IsNullOrWhiteSpace($systemPython)) {
            Write-Warning "$($text.FallbackWarning) $systemPython"
            return $systemPython
        }
        # This is the only thing a user sees when the first run cannot proceed, so it
        # has to be in their language and say what to do next. The English technical
        # detail is thrown afterwards so a bug report still carries it.
        Write-Host $text.DownloadFailed -ForegroundColor Red
        Write-Host "$($text.SeeLog) $(Join-Path $StateRoot 'bootstrap.log')" -ForegroundColor Red
        throw "Could not prepare Python automatically. $($_.Exception.Message)"
    }
}

function Get-LauncherProcessesInDirectory {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)

    $normalizedRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
    @(Get-Process -Name 'CodexBridgeLauncher' -ErrorAction SilentlyContinue) | ForEach-Object {
        try {
            $processPath = $_.Path
            if (-not [string]::IsNullOrWhiteSpace($processPath)) {
                $processDir = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($processPath))
                if ([string]::Equals($processDir.TrimEnd('\'), $normalizedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                    $_
                }
            }
        } catch { }
    }
}

function Stop-InstalledLauncherProcesses {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(Get-LauncherProcessesInDirectory -InstallRoot $InstallRoot)
        if ($remaining.Count -eq 0) { return }

        foreach ($process in $remaining) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
        foreach ($process in $remaining) {
            try { Wait-Process -Id $process.Id -Timeout 2 -ErrorAction SilentlyContinue | Out-Null } catch { }
        }

        if ([DateTime]::UtcNow -ge $deadline) { break }
        Start-Sleep -Milliseconds 200
    } while ($true)

    $remaining = @(Get-LauncherProcessesInDirectory -InstallRoot $InstallRoot)
    if ($remaining.Count -gt 0) {
        $ids = ($remaining | ForEach-Object Id) -join ', '
        throw "CodexBridge Launcher process(es) did not exit before update: $ids"
    }
}

$ProjectRoot = Resolve-CodexBridgeFullPath -Path $ProjectRoot -Fallback (Join-Path $PSScriptRoot '..\..')
$stateRoot = if ([string]::IsNullOrWhiteSpace($StateRootOverride)) {
    Join-Path $env:LOCALAPPDATA 'CodexProviderBridge'
} else {
    [IO.Path]::GetFullPath($StateRootOverride)
}
$bootstrapDir = Join-Path $stateRoot 'source-bootstrap'
New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null

$python = Ensure-PortablePython -StateRoot $stateRoot -ProjectRoot $ProjectRoot
[Environment]::SetEnvironmentVariable('CPB_PYTHON', $python, 'Process')

if ($PrepareRuntimeOnly) {
    # Prints the selected runtime and proves it executes, then stops. It touches
    # neither the launcher, nor autostart, nor the Codex config.
    Write-Host $python
    & $python -c 'import sys; print(sys.version)'
    exit 0
}

# Source quick-start is also an in-place updater for an existing installed copy.
# A packaged install may have left codex_provider_bridge.exe in the stable app
# directory. The manager intentionally prefers that EXE over the Python source,
# so merely copying a newer codex_provider_bridge.py would silently keep running
# the stale packaged Bridge. Stop the resident installed copy and remove only the
# stale Bridge EXE before relaunching from this source tree.
$installedAppDir = Join-Path $stateRoot 'app'
if (Test-Path -LiteralPath $installedAppDir -PathType Container) {
    Write-Host '[CodexBridge] Preparing installed copy for source update...' -ForegroundColor Cyan

    # Stop installed launcher/tray/watcher processes first and wait for every
    # role to exit. This prevents a stale watcher or full Launcher from racing
    # the copy and relaunching the old runtime during an in-place update.
    Stop-InstalledLauncherProcesses -InstallRoot $installedAppDir
    Stop-InstalledLauncherProcesses -InstallRoot $bootstrapDir

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
