from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"
MANAGER = ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1"
BRIDGE = ROOT / "src" / "bridge" / "codex_provider_bridge.py"
UNINSTALL = ROOT / "scripts" / "windows" / "UninstallCodexBridge.ps1"
START = ROOT / "scripts" / "windows" / "StartCodexBridge.ps1"
SETUP_BUILD = ROOT / "scripts" / "build" / "BuildCodexBridgeSetup.ps1"
ROOT_UNINSTALL = ROOT / "Uninstall CodexBridge.cmd"


def _normalized_sha256(path: Path) -> str:
    # Git may check PowerShell files out as CRLF on Windows. Normalize only
    # line endings so this guard still detects substantive core changes.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_tray_exposes_standard_uninstall_entry_with_confirmation():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    assert 'new ToolStripMenuItem(ui.T("Uninstall CodexBridge..."))' in text
    assert 'GetUninstallDialogText' in text
    assert 'MessageBoxButtons.YesNo' in text
    assert 'MessageBoxDefaultButton.Button2' in text
    assert 'Program.StopCcSwitchWatcher();' in text
    assert 'UninstallCodexBridge.ps1' in text


def test_windows_apps_and_features_uninstall_entry_is_registered():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    assert r'Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexBridge' in text
    assert 'RegisterWindowsUninstallEntry(installedExe, installDir);' in text
    assert 'UninstallString' in text
    assert 'QuietUninstallString' in text
    assert 'DisplayName", "CodexBridge"' in text


def test_uninstaller_removes_autostart_watcher_logs_runtime_and_app_state():
    text = UNINSTALL.read_text(encoding="utf-8-sig")
    assert 'CodexProviderBridgeCcSwitchWatcherStop' in text
    assert "Remove-ItemProperty -Path $startupKey -Name $startupValue" in text
    assert "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CodexBridge" in text
    assert 'Stop-Bridge' in text
    assert 'Stop-CcSwitch' in text
    assert 'Remove-StateRoot' in text
    assert "Remove-Item -LiteralPath $stateRoot -Recurse -Force" in text


def test_uninstaller_restores_preinstall_config_and_cleans_cpb_artifacts():
    text = UNINSTALL.read_text(encoding="utf-8-sig")
    assert 'preinstall-state.txt' in text
    assert 'preinstall-config.toml' in text
    assert "config.toml.bridge-backup-*" in text
    assert "cpb-*" in text
    assert 'prepare-direct-official' in text


def test_quickstart_copies_uninstaller_to_stable_runtime():
    text = START.read_text(encoding="utf-8-sig")
    assert "UninstallCodexBridge.ps1" in text
    launcher = LAUNCHER.read_text(encoding="utf-8-sig")
    assert 'CopyRuntimeFile(sourceDir, installDir, "UninstallCodexBridge.ps1", true);' in launcher


def test_optional_setup_payload_includes_uninstaller():
    text = SETUP_BUILD.read_text(encoding="utf-8-sig")
    assert "UninstallCodexBridge.ps1" in text
    setup = (ROOT / "src" / "setup" / "CodexBridgeSetup.cs").read_text(encoding="utf-8-sig")
    assert 'RegisterWindowsUninstallEntry(installedLauncher, appDir);' in setup


def test_repo_contains_fallback_uninstall_cmd():
    text = ROOT_UNINSTALL.read_text(encoding="utf-8")
    assert '%LOCALAPPDATA%\\CodexProviderBridge\\app\\UninstallCodexBridge.ps1' in text
    assert 'scripts\\windows\\UninstallCodexBridge.ps1' in text


def test_uninstall_feature_does_not_modify_bridge_or_manager_core():
    # Bridge re-baselined for the sanctioned diagnostic-log sanitizer layer only;
    # conversation-continuation core logic is unchanged. Manager core untouched.
    assert _normalized_sha256(BRIDGE) == "5d418498317fca43e6f8da9cbcef12f6ca4cbea737e98829845943effadfc351"
    assert _normalized_sha256(MANAGER) == "b3f4befd2c3e0b48f034235bd248bddcd02b8d4991a402f34eed6d46a9475480"
