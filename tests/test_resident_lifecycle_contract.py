from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"
MANAGER = ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1"
BRIDGE = ROOT / "src" / "bridge" / "codex_provider_bridge.py"


def _normalized_sha256(path: Path) -> str:
    # Git may check PowerShell files out as CRLF on Windows. Normalize only
    # line endings so this guard still detects substantive core changes.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _method_body(text: str, signature: str, next_signature: str) -> str:
    start = text.index(signature)
    end = text.index(next_signature, start)
    return text[start:end]


def test_exit_everything_warns_then_stops_bridge_ccswitch_and_launcher_without_native_handoff():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void ExitLauncher()", "private void Log(string message)")
    assert 'MessageBox.Show(' in body
    assert 'MessageBoxButtons.YesNo' in body
    assert 'MessageBoxDefaultButton.Button2' in body
    assert 'if (answer != DialogResult.Yes)' in body
    assert 'exiting = true;' in body
    assert 'pollTimer.Stop()' in body
    assert 'Program.StopCcSwitchWatcher()' not in body
    assert 'CancelInFlightBridgeEnsure();' in body
    assert 'ThreadPool.QueueUserWorkItem(delegate { PerformExitShutdown(); });' in body
    assert 'StopBridgeForUpdate();' not in body
    assert 'StopCcSwitchForExit();' not in body
    assert 'Application.ExitThread();' not in body
    assert 'PrepareDirectOfficialHandoff()' not in body
    assert 'RestartCodex(' not in body


def test_exit_menu_is_explicit_full_shutdown_not_hidden_tray():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    assert 'new ToolStripMenuItem(ui.T("Exit Everything..."))' in text
    assert 'new ToolStripMenuItem("Hide Tray")' not in text


def test_exit_does_not_delete_or_rewrite_codex_config():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void ExitLauncher()", "private void Log(string message)")
    assert 'config.toml and Codex will be left untouched' in body
    assert 'PrepareDirectOfficialHandoff()' not in body
    assert 'RestartCodex(' not in body


def test_windows_login_starts_resident_launcher_not_ccswitch_trigger_only():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    register = _method_body(text, "private static void RegisterStableAutostart", "private static void CopyRuntimeFile")
    assert '--autostart' in register
    assert '--watch-ccswitch' not in register


def test_third_party_proxy_recovery_does_not_restart_codex():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void SuperviseThirdPartyProxy", "private bool StartCcSwitchFromRememberedTarget")
    assert 'EnsureCcSwitchProxyRunning();' in body
    assert 'RestartCodex(' not in body


def test_bridge_rebind_removes_stale_proxy_managed_bearer_placeholder():
    text = MANAGER.read_text(encoding="utf-8-sig")
    assert "Remove-SectionTomlKey -Lines $lines -HeaderPattern $providerPattern -Key 'experimental_bearer_token'" in text



def test_launcher_ensures_ccswitch_trigger_watcher_and_exit_leaves_it_armed():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    ctor = _method_body(text, "public LauncherContext(Mutex singleInstanceMutex)", "private static Icon LoadLauncherIcon")
    exit_body = _method_body(text, "private void ExitLauncher()", "private void Log(string message)")
    assert 'Program.EnsureCcSwitchWatcherRunning(Application.ExecutablePath);' in ctor
    assert 'CC Switch trigger watcher remains armed' in exit_body
    assert 'Program.StopCcSwitchWatcher()' not in exit_body
    assert 'ThreadPool.QueueUserWorkItem(delegate { PerformExitShutdown(); });' in exit_body
    shutdown = _method_body(text, "private void PerformExitShutdown()", "private void FinalizeExitOnUiThread()")
    assert 'StopBridgeForUpdate();' in shutdown
    assert 'StopCcSwitchForExit();' in shutdown


def test_ccswitch_trigger_watcher_relaunches_full_launcher_after_explicit_exit():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    watcher = _method_body(text, "private static void RunCcSwitchWatcher()", "private static bool SourceIsNewerThanExe")
    assert 'if (!IsCcSwitchRunning()) continue;' in watcher
    assert 'if (IsFullLauncherRunning()) continue;' in watcher
    assert 'LaunchFullLauncherFromWatcher(exePath);' in watcher

def test_conversation_bridge_core_matches_compatibility_firewall_baseline():
    # The strict tool-adjacency compatibility fix intentionally changes only the guarded
    # portability retry after an upstream 400/422; launcher/manager lifecycle behavior stays frozen.
    digest = _normalized_sha256(BRIDGE)
    assert digest == "2f43640afbfa83a687201ed53a9d812d3235e9446c72b9e18d75418ba5d94fab"


def test_exit_serializes_against_inflight_bridge_ensure_and_blocks_stale_restart():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    ensure = _method_body(text, "private void EnsureBridgeRunning()", "private void SuperviseThirdPartyProxy")
    stop = _method_body(text, "private void StopBridgeForUpdate()", "private void PrepareDirectOfficialHandoff()")
    restart = _method_body(text, "private void RestartCodex(string reason)", "private List<Process> FindCcSwitchProcesses()")
    assert "lock (bridgeLifecycleSync)" in ensure
    assert "if (exiting)" in ensure
    assert "skipping post-ensure Codex restart" in ensure
    assert "lock (bridgeLifecycleSync)" in stop
    assert "if (exiting)" in restart
    assert "Skipping Codex restart because Exit Everything is in progress" in restart


def test_exit_race_patch_does_not_modify_manager_or_bridge_firewall_baseline():
    manager_digest = _normalized_sha256(MANAGER)
    bridge_digest = _normalized_sha256(BRIDGE)
    assert manager_digest == "b3f4befd2c3e0b48f034235bd248bddcd02b8d4991a402f34eed6d46a9475480"
    assert bridge_digest == "2f43640afbfa83a687201ed53a9d812d3235e9446c72b9e18d75418ba5d94fab"


def test_exit_is_nonblocking_closes_tray_immediately_and_cancels_inflight_start():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    exit_body = _method_body(text, "private void ExitLauncher()", "private void Log(string message)")
    cancel = _method_body(text, "private void CancelInFlightBridgeEnsure()", "private void PerformExitShutdown()")
    ensure = _method_body(text, "private void EnsureBridgeRunning()", "private void SuperviseThirdPartyProxy")
    assert 'tray.ContextMenuStrip.Close();' in exit_body
    assert 'tray.Visible = false;' in exit_body
    assert 'CancelInFlightBridgeEnsure();' in exit_body
    assert 'ThreadPool.QueueUserWorkItem(delegate { PerformExitShutdown(); });' in exit_body
    assert 'p.Kill();' in cancel
    assert 'bridgeEnsureProcess = p;' in ensure
    assert 'Bridge manager startup finished/cancelled during Exit Everything; ignoring its result.' in ensure


def test_exit_worker_finishes_on_ui_thread_after_shutdown_attempts():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    shutdown = _method_body(text, "private void PerformExitShutdown()", "private void FinalizeExitOnUiThread()")
    finalize = _method_body(text, "private void FinalizeExitOnUiThread()", "private void ExitLauncher()")
    assert shutdown.index('StopBridgeForUpdate();') < shutdown.index('StopCcSwitchForExit();')
    assert 'FinalizeExitOnUiThread();' in shutdown
    assert 'menu.BeginInvoke(new Action(FinalizeExitOnUiThread));' in finalize
    assert 'Application.ExitThread();' in finalize
