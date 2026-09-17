[CmdletBinding()]
param(
    [switch]$Confirmed,
    [switch]$Silent,
    [switch]$FromTemp,
    [int]$ParentPid = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$stateRoot = Join-Path $env:LOCALAPPDATA 'CodexProviderBridge'
$appDir = Join-Path $stateRoot 'app'
$uninstallStateDir = Join-Path $stateRoot 'uninstall'
$codexDir = Join-Path $env:USERPROFILE '.codex'
$codexConfig = Join-Path $codexDir 'config.toml'
$startupKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$startupValue = 'CodexBridgeLauncher'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexBridge'
$watcherStopEvent = 'Local\CodexProviderBridgeCcSwitchWatcherStop'

function Get-UiText {
    $culture = [Globalization.CultureInfo]::CurrentUICulture.Name
    $traditional = $culture -match '^(zh-TW|zh-HK|zh-MO)' -or $culture -like 'zh-Hant*'
    if ($culture -like 'zh*') {
        if ($traditional) {
            return @{
                Title = '解除安裝 CodexBridge？'
                Body = "這將解除安裝 CodexBridge，關閉 Bridge 和 CC Switch，並刪除本機程式、日誌和執行階段檔案。`r`n`r`nCodex 設定將恢復到安裝前狀態。聊天記錄不會被刪除。"
                SuccessTitle = 'CodexBridge 已解除安裝'
                SuccessBody = "CodexBridge 已從此電腦移除。`r`n`r`n如果 Codex / VS Code 仍在執行，請重新開啟後使用恢復的設定。"
                FallbackBody = "CodexBridge 已移除，但找不到完整的安裝前設定快照。Codex 已切換到直接 Official 路由。`r`n`r`n如果 Codex / VS Code 仍在執行，請重新開啟後再使用。"
            }
        }
        return @{
            Title = '卸载 CodexBridge？'
            Body = "这将卸载 CodexBridge，关闭 Bridge 和 CC Switch，并删除本地程序、日志和运行时文件。`r`n`r`nCodex 配置将恢复到安装前状态。聊天记录不会删除。"
            SuccessTitle = 'CodexBridge 已卸载'
            SuccessBody = "CodexBridge 已从此电脑移除。`r`n`r`n如果 Codex / VS Code 仍在运行，请重新打开后使用恢复后的配置。"
            FallbackBody = "CodexBridge 已移除，但没有找到完整的安装前配置快照。Codex 已切换为直接 Official 路由。`r`n`r`n如果 Codex / VS Code 仍在运行，请重新打开后再使用。"
        }
    }
    return @{
        Title = 'Uninstall CodexBridge?'
        Body = "This will uninstall CodexBridge, stop Bridge and CC Switch, and delete local program files, logs, and runtimes.`r`n`r`nCodex configuration will be restored to its pre-install state. Chat history will not be deleted."
        SuccessTitle = 'CodexBridge uninstalled'
        SuccessBody = "CodexBridge has been removed from this PC.`r`n`r`nIf Codex / VS Code is still running, reopen it to use the restored configuration."
        FallbackBody = "CodexBridge was removed, but a complete pre-install configuration snapshot was not available. Codex was switched to the direct Official route.`r`n`r`nIf Codex / VS Code is still running, reopen it before continuing."
    }
}

function Show-Confirm {
    if ($Silent -or $Confirmed) { return $true }
    Add-Type -AssemblyName System.Windows.Forms
    $t = Get-UiText
    $answer = [Windows.Forms.MessageBox]::Show(
        $t.Body,
        $t.Title,
        [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Warning,
        [Windows.Forms.MessageBoxDefaultButton]::Button2)
    return ($answer -eq [Windows.Forms.DialogResult]::Yes)
}

function Relaunch-FromTemp {
    if ($FromTemp) { return $false }
    $tempScript = Join-Path $env:TEMP ("CodexBridge-Uninstall-" + [Guid]::NewGuid().ToString('N') + '.ps1')
    Copy-Item -LiteralPath $PSCommandPath -Destination $tempScript -Force
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $tempScript + '"'),'-FromTemp')
    if ($Confirmed) { $args += '-Confirmed' }
    if ($Silent) { $args += '-Silent' }
    if ($ParentPid -gt 0) { $args += @('-ParentPid', [string]$ParentPid) }
    Start-Process -FilePath 'powershell.exe' -ArgumentList ($args -join ' ') -WindowStyle Hidden -WorkingDirectory $env:TEMP
    return $true
}

function Signal-WatcherStop {
    try {
        $evt = [Threading.EventWaitHandle]::OpenExisting($watcherStopEvent)
        try { $evt.Set() | Out-Null } finally { $evt.Dispose() }
    } catch { }
}

function Remove-Registration {
    try { Remove-ItemProperty -Path $startupKey -Name $startupValue -ErrorAction SilentlyContinue } catch { }
    try { Remove-Item -LiteralPath $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue } catch { }
}

function Stop-InstalledLaunchers {
    try {
        Get-Process -Name 'CodexBridgeLauncher' -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $path = $_.Path
                if ([string]::IsNullOrWhiteSpace($path) -or $path.StartsWith($appDir, [StringComparison]::OrdinalIgnoreCase)) {
                    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                }
            } catch {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { }
}

function Stop-Bridge {
    $manager = Join-Path $appDir 'codex_bridge_manager.ps1'
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { return }
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $manager stop *> $null
    } catch { }
}

function Stop-CcSwitch {
    foreach ($name in @('cc-switch','CC Switch','cc_switch','ccswitch')) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
    }
}

function Test-HasRestorableConfig {
    $modePath = Join-Path $uninstallStateDir 'preinstall-state.txt'
    $backupPath = Join-Path $uninstallStateDir 'preinstall-config.toml'
    $mode = if (Test-Path -LiteralPath $modePath -PathType Leaf) { (Get-Content -LiteralPath $modePath -TotalCount 1).Trim().ToLowerInvariant() } else { 'unknown' }
    if ($mode -eq 'existing' -and (Test-Path -LiteralPath $backupPath -PathType Leaf)) { return $true }
    if ($mode -eq 'absent') { return $true }
    $cleanBackup = Get-ChildItem -LiteralPath $codexDir -Filter 'config.toml.bridge-backup-*' -File -ErrorAction SilentlyContinue |
        Sort-Object Name | Where-Object {
            try {
                $candidate = [IO.File]::ReadAllText($_.FullName)
                $candidate -notmatch '127\.0\.0\.1:15722' -and $candidate -notmatch 'cpb-'
            } catch { $false }
        } | Select-Object -First 1
    return ($null -ne $cleanBackup)
}

function Prepare-DirectOfficialFallback {
    $manager = Join-Path $appDir 'codex_bridge_manager.ps1'
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { return }
    try { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $manager prepare-direct-official *> $null } catch { }
}

function Restore-PreinstallConfig {
    $modePath = Join-Path $uninstallStateDir 'preinstall-state.txt'
    $backupPath = Join-Path $uninstallStateDir 'preinstall-config.toml'
    $mode = if (Test-Path -LiteralPath $modePath -PathType Leaf) { (Get-Content -LiteralPath $modePath -TotalCount 1).Trim().ToLowerInvariant() } else { 'unknown' }

    if ($mode -eq 'existing' -and (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        New-Item -ItemType Directory -Path $codexDir -Force | Out-Null
        $temp = Join-Path $codexDir ("config.toml.codexbridge-uninstall-" + [Guid]::NewGuid().ToString('N'))
        Copy-Item -LiteralPath $backupPath -Destination $temp -Force
        Move-Item -LiteralPath $temp -Destination $codexConfig -Force
        return $true
    }

    if ($mode -eq 'absent') {
        Remove-Item -LiteralPath $codexConfig -Force -ErrorAction SilentlyContinue
        return $true
    }

    # Migration fallback for installations created before the dedicated uninstall snapshot existed.
    $cleanBackup = Get-ChildItem -LiteralPath $codexDir -Filter 'config.toml.bridge-backup-*' -File -ErrorAction SilentlyContinue |
        Sort-Object Name | Where-Object {
            try {
                $candidate = [IO.File]::ReadAllText($_.FullName)
                $candidate -notmatch '127\.0\.0\.1:15722' -and $candidate -notmatch 'cpb-'
            } catch { $false }
        } | Select-Object -First 1
    if ($null -ne $cleanBackup) {
        New-Item -ItemType Directory -Path $codexDir -Force | Out-Null
        Copy-Item -LiteralPath $cleanBackup.FullName -Destination $codexConfig -Force
        return $true
    }

    # Last-resort safe route was prepared before Bridge shutdown. Remove only
    # CodexBridge-owned catalog/token references that would point at deleted files.
    if (Test-Path -LiteralPath $codexConfig -PathType Leaf) {
        try {
            $text = [IO.File]::ReadAllText($codexConfig)
            $lines = [regex]::Split($text, '\r?\n') | Where-Object {
                $_ -notmatch '^\s*model_catalog_json\s*=\s*.*cpb-' -and
                $_ -notmatch '^\s*experimental_bearer_token\s*=\s*"PROXY_MANAGED"\s*$'
            }
            [IO.File]::WriteAllText($codexConfig, [string]::Join([Environment]::NewLine, $lines), (New-Object Text.UTF8Encoding($false)))
        } catch { }
    }
    return $false
}

function Remove-CodexBridgeCodexArtifacts {
    if (-not (Test-Path -LiteralPath $codexDir -PathType Container)) { return }
    $patterns = @(
        'cpb-*',
        'config.toml.bridge-backup-*',
        'config.toml.bridge-direct-official-backup-*',
        'config.toml.bridge-tmp-*',
        'config.toml.bridge-direct-official-tmp-*'
    )
    foreach ($pattern in $patterns) {
        Get-ChildItem -LiteralPath $codexDir -Filter $pattern -Force -ErrorAction SilentlyContinue | ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Force -Recurse -ErrorAction SilentlyContinue } catch { }
        }
    }
}

function Remove-StateRoot {
    for ($i = 0; $i -lt 12; $i++) {
        try {
            if (Test-Path -LiteralPath $stateRoot) {
                Remove-Item -LiteralPath $stateRoot -Recurse -Force -ErrorAction Stop
            }
            if (-not (Test-Path -LiteralPath $stateRoot)) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
}

if (Relaunch-FromTemp) { exit 0 }
if (-not (Show-Confirm)) { exit 1 }

Signal-WatcherStop
Remove-Registration
Stop-InstalledLaunchers
if ($ParentPid -gt 0) {
    try { Wait-Process -Id $ParentPid -Timeout 5 -ErrorAction SilentlyContinue } catch { }
}

$hasRestorableConfig = Test-HasRestorableConfig
if (-not $hasRestorableConfig) { Prepare-DirectOfficialFallback }
Stop-Bridge
$restored = Restore-PreinstallConfig
Stop-CcSwitch
Remove-CodexBridgeCodexArtifacts
Remove-StateRoot

if (-not $Silent) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $t = Get-UiText
        $message = if ($restored) { $t.SuccessBody } else { $t.FallbackBody }
        [Windows.Forms.MessageBox]::Show($message, $t.SuccessTitle, [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information) | Out-Null
    } catch { }
}

try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch { }
exit 0
