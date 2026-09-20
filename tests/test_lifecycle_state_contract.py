from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_setup_always_registers_watcher_and_starts_both_explicitly():
    setup = (ROOT / "src/setup/CodexBridgeSetup.cs").read_text(encoding="utf-8-sig")
    assert 'key.SetValue(StartupValueName, "\\\"" + launcherExe + "\\\" --watch-ccswitch"' in setup
    assert 'watcher.Arguments = "--watch-ccswitch"' in setup
    assert 'launcher.Arguments = "--installed"' in setup
    assert "restore it automatically" not in setup


def test_windows_uninstall_stops_watcher_and_removes_run_registration():
    text = (ROOT / "scripts/windows/UninstallCodexBridge.ps1").read_text(encoding="utf-8-sig")
    assert "Signal-WatcherStop" in text
    assert "Remove-ItemProperty -Path $startupKey -Name $startupValue" in text
    assert "Stop-InstalledLaunchers" in text


def test_macos_watcher_only_launches_full_app_on_ccswitch_edge():
    text = (ROOT / "scripts/unix/codex_bridge_watcher.sh").read_text(encoding="utf-8-sig")
    assert "CC Switch detected" in text
    assert "CodexBridge.app" in text
    assert "ensure_bridge_started" not in text
    assert "restart_cc_switch" not in text
    assert "restart_codex" not in text
    assert 'osascript -e \'tell application "CC Switch" to quit\'' not in text


def test_macos_full_app_ensures_bridge_but_has_no_ccswitch_lifecycle_menu():
    text = (ROOT / "src/launcher-macos/CodexBridgeLauncher.swift").read_text(encoding="utf-8")
    assert "controller.ensureBridge()" in text
    assert "prepare-direct-official" in text
    assert "stopAll() -> Bool" in text
    assert "clearDirectOfficialLatch" in text
    assert "Official handoff failed" in text
    assert "Restart CC Switch" not in text
    assert "Launch at Login" not in text
    assert "Exit CodexBridge" in text
    assert "watcherPlist" in text


def test_macos_commands_are_bounded_and_official_exit_handoff_precedes_stop():
    launcher = (ROOT / "src/launcher-macos/CodexBridgeLauncher.swift").read_text(encoding="utf-8")
    manager = (ROOT / "scripts/unix/codex_bridge_manager.sh").read_text(encoding="utf-8-sig")
    assert "timeout: TimeInterval" in launcher
    assert "process.terminate()" in launcher
    assert "restart-codex" in launcher
    assert launcher.index('"prepare-direct-official"') < launcher.index('"stop"')
    assert "prepare-direct-official" in manager
    assert "chatgpt.com/backend-api/codex" in manager
    assert "model_provider" in manager


def test_macos_exit_has_bounded_ccswitch_force_fallback_and_port_check():
    launcher = (ROOT / "src/launcher-macos/CodexBridgeLauncher.swift").read_text(encoding="utf-8")
    assert "pkill" in launcher
    assert "15721" in launcher
    assert "waitForCcSwitchStopped" in launcher


def test_macos_bootstrap_does_not_create_full_launcher_login_agent_or_open_ccswitch():
    text = (ROOT / "Start CodexBridge.command").read_text(encoding="utf-8-sig")
    assert "com.strengw.codexbridge.watcher.plist" in text
    assert "install_launcher_agent" not in text
    assert "LAUNCHER_PLIST" not in text
    assert 'open -a "CC Switch"' not in text
    assert 'open -a "CCSwitch"' not in text
