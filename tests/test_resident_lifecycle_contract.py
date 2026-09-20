from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"
MANAGER = ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1"
BRIDGE = ROOT / "src" / "bridge" / "codex_provider_bridge.py"


def _normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _method_body(text: str, signature: str, next_signature: str) -> str:
    start = text.index(signature)
    end = text.index(next_signature, start)
    return text[start:end]


def test_exit_codexbridge_uses_explicit_dialog_and_preserves_watcher():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void ExitLauncher()", "private void Log(string message)")
    assert 'new ToolStripMenuItem(ui.T("Exit CodexBridge..."))' in text
    assert "MessageBoxButtons.YesNo" in body
    assert "MessageBoxDefaultButton.Button2" in body
    assert "exiting = true;" in body
    assert "pollTimer.Stop()" in body
    assert "CancelInFlightBridgeEnsure();" in body
    assert "Program.StopCcSwitchWatcher()" not in body
    assert "ThreadPool.QueueUserWorkItem(delegate { PerformExitShutdown(); });" in body
    assert "Exit Everything" not in text


def test_windows_login_registration_is_watcher_only_and_migrates_legacy_value():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    register = _method_body(text, "private static void RegisterWatcherAutostart", "private static string StableStateRoot")
    assert "--watch-ccswitch" in register
    assert "--autostart" not in register
    assert "MigrateLegacyStartupRegistration" in text
    assert "--autostart" in _method_body(text, "private static void MigrateLegacyStartupRegistration", "private static string StableStateRoot")


def test_full_launcher_does_not_own_watcher_lifecycle():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    ctor = _method_body(text, "public LauncherContext(Mutex singleInstanceMutex)", "private static Icon LoadLauncherIcon")
    assert "EnsureCcSwitchWatcherRunning" not in ctor
    assert "Start CodexBridge with Windows" not in text
    assert 'ui.T("Restart CC Switch")' not in text


def test_third_party_supervisor_only_observes_proxy_transition():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void SuperviseThirdPartyProxy", "private void RestartCodex")
    assert "thirdPartyProxyUnavailable" in body
    assert "available" in body.lower()
    assert "EnsureCcSwitchProxyRunning" not in body
    assert "StartCcSwitchFromRememberedTarget" not in body
    assert "RestartCcSwitch" not in body
    assert "KillProcessTree" not in body


def test_provider_switch_never_restarts_ccswitch():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert "RestartCodex(\"third-party route " in poll
    assert "RestartCcSwitch" not in poll


def test_exit_worker_has_bounded_independent_stop_path_and_continues_after_warnings():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    stop = _method_body(text, "private void StopBridgeForExit", "private void PrepareDirectOfficialHandoff")
    shutdown = _method_body(text, "private void PerformExitShutdown()", "private void FinalizeExitOnUiThread()")
    assert "bridgeLifecycleSync" not in stop
    assert "WaitForExit(12000)" in stop or "WaitForExit(15000)" in stop
    assert "KillResidualBridgeProcesses" in stop
    assert "TestTcpPort(\"127.0.0.1\", 15722" in stop
    assert "StopBridgeForExit();" in shutdown
    assert "StopCcSwitchForExit();" in shutdown
    assert shutdown.index("StopBridgeForExit();") < shutdown.index("StopCcSwitchForExit();")
    assert "FinalizeExitOnUiThread();" in shutdown


def test_official_exit_handoff_verifies_config_before_bridge_stop():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    shutdown = _method_body(text, "private void PerformExitShutdown()", "private void FinalizeExitOnUiThread()")
    assert "IsCustomDirectOfficialRoute()" in shutdown
    assert "PrepareDirectOfficialHandoff();" in shutdown
    assert "RestartCodexForExit" in shutdown
    assert "handoff" in shutdown.lower()


def test_watcher_uses_ccswitch_false_to_true_edge_and_full_launcher_mutex():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    watcher = _method_body(text, "private static void RunCcSwitchWatcher()", "private static bool SourceIsNewerThanExe")
    assert "previousCcSwitchRunning" in watcher
    assert "launchAttemptedForRun" in watcher
    assert "currentCcSwitchRunning &&" in watcher
    assert "!launchAttemptedForRun" in watcher
    assert "previousCcSwitchRunning = currentCcSwitchRunning" in watcher
    assert "!IsFullLauncherRunning()" in watcher
    assert "LaunchFullLauncherFromWatcher(exePath);" in watcher


def test_conversation_bridge_core_remains_unchanged():
    assert _normalized_sha256(BRIDGE) == "2f43640afbfa83a687201ed53a9d812d3235e9446c72b9e18d75418ba5d94fab"


def test_manager_core_remains_unchanged():
    assert _normalized_sha256(MANAGER) == "b3f4befd2c3e0b48f034235bd248bddcd02b8d4991a402f34eed6d46a9475480"
