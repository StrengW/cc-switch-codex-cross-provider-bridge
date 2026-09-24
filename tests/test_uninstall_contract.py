from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"
MANAGER = ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1"
BRIDGE = ROOT / "src" / "bridge" / "codex_provider_bridge.py"
UNINSTALL = ROOT / "scripts" / "windows" / "UninstallCodexBridge.ps1"
START = ROOT / "scripts" / "windows" / "StartCodexBridge.ps1"
SETUP_BUILD = ROOT / "scripts" / "build" / "BuildCodexBridgeSetup.ps1"
ROOT_UNINSTALL = ROOT / "Uninstall CodexBridge.cmd"
MACOS_UNINSTALL = ROOT / "scripts" / "unix" / "codex_bridge_uninstall.sh"
MACOS_LAUNCHER = ROOT / "src" / "launcher-macos" / "CodexBridgeLauncher.swift"


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
    # Bridge re-baselined for the sanctioned diagnostic-log sanitizer layer, the
    # sanctioned route-edge inference fix in CatalogConfigGuard.guard_once, and the
    # Official-route HTTP upstream fix (route resolved once in _handle, guard
    # re-asserts its config keys every pass, retrying config reads);
    # conversation-continuation core logic is unchanged.
    # Manager re-baselined for the sanctioned backup-retention cap, which prunes
    # the config.toml backups the manager itself writes. Uninstall behaviour is
    # unchanged: it still restores the pre-install config and removes every
    # artifact family.
    assert _normalized_sha256(BRIDGE) == "11bda5ae3300aecac9202c4e0885c5f68e7181b89d3ddb51284bd968d9a87a5f"
    assert _normalized_sha256(MANAGER) == "260c8ff75e9c139d62233838f7b6701acd6f279cb903d6949c55bb31a69ee052"


def test_macos_uninstall_removes_every_bridge_artifact_family():
    text = MACOS_UNINSTALL.read_text(encoding="utf-8")
    for pattern in (
        "config.toml.bridge-backup-*",
        "config.toml.bridge-direct-official-backup-*",
        ".*.bridge-tmp-*",
        ".*.bridge-direct-official-tmp-*",
        "cpb-*",
    ):
        assert pattern in text
    assert "sudo" not in text


def test_macos_uninstall_leaves_codex_config_working_without_clobbering_third_party():
    text = MACOS_UNINSTALL.read_text(encoding="utf-8")
    # The handoff is gated on the config actually pointing at the local Bridge,
    # because prepare-direct-official rewrites model_provider unconditionally.
    assert "config_points_at_bridge" in text
    assert "restore_earliest_clean_backup" in text
    assert "strip_bridge_owned_config_lines" in text
    # prepare-direct-official arms the detach latch, so it must run while the
    # Bridge is alive; the backup restore must run only after the stop.
    assert text.index('"$MANAGER" prepare-direct-official') < text.index('"$MANAGER" stop')
    assert text.index("restore_earliest_clean_backup; then") > text.index('"$MANAGER" stop')


def test_macos_uninstall_dialog_states_the_codex_config_outcome():
    text = MACOS_LAUNCHER.read_text(encoding="utf-8")
    assert "restored to the pre-install state or switched back to the direct Official route" in text
    assert "恢复到安装前状态，或切回 Official 直连" in text


def test_macos_uninstall_does_not_mistake_cc_switch_for_the_bridge():
    text = MACOS_UNINSTALL.read_text(encoding="utf-8")
    marker = re.search(r"BRIDGE_MARKER_RE='([^']+)'", text).group(1)

    def route(port: int) -> str:
        return f'base_url = "http://127.0.0.1:{port}/v1"'

    # CC Switch's own upstream port sits directly below the Bridge's managed
    # range. Matching it would rewrite the config of a CC Switch-only user who
    # never routed Codex through the Bridge at all.
    assert not re.search(marker, route(15721))
    # The managed range the manager itself uses: default port .. default + 199.
    for port in (15722, 15723, 15730, 15799, 15800, 15919, 15920, 15921):
        assert re.search(marker, route(port)), port
    for port in (15721, 15922, 16000, 8080):
        assert not re.search(marker, route(port)), port
    # The bundled catalog is the other fingerprint, for installs whose Bridge
    # was started on a port outside the managed range.
    assert re.search(marker, 'model_catalog_json = "/home/u/.codex/cpb-bundled-model-catalog.json"')
    assert re.search(marker, 'base_url = "http://localhost:15722/v1"')
