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


def test_provider_switch_repair_restart_is_bounded_bound_and_one_shot():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert "RestartCodex(\"third-party route " in poll
    # Edge-triggered repair: EVERY genuine third-party switch edge restarts the bound
    # CC Switch once, gated ONLY by the one-shot per-key latch (if ccSwitchRepairDoneKey
    # != route.Key). It is never gated by a point-in-time credential read, which raced
    # with CC Switch's own auth.json write and silently skipped the repair on a repeat
    # switch to the SAME provider (Official -> DeepSeek -> Official -> DeepSeek).
    # IsThirdPartyAuthRepairNeeded now survives only as the fallback that decides
    # whether reloading Codex is safe when CC Switch could not be repaired.
    assert "if (ccSwitchRepairDoneKey != route.Key)" in poll
    assert "IsThirdPartyAuthRepairNeeded(route) && ccSwitchRepairDoneKey" not in poll
    assert "else if (IsThirdPartyAuthRepairNeeded(route))" in poll
    assert "ccSwitchRepairDoneKey != route.Key" in poll
    assert "ccSwitchRepairDoneKey = route.Key" in poll
    assert "ccSwitchRepairInProgress = true" in poll
    assert "ccSwitchRepairInProgress = false" in poll
    assert "TryBindLiveCcSwitchExecutablePath(out boundPath)" in poll
    assert "RestartBoundCcSwitchInstanceOnce(boundPath)" in poll
    # On failure the Codex restart is skipped so the user is not pushed to login.
    assert "skipping Codex restart to avoid the login screen" in poll
    # Discovery / remembered-path / auto-revive helpers must never appear here.
    for token in ("DiscoverCcSwitchExe", "StartCcSwitchFromRememberedTarget", "EnsureCcSwitchProxyRunning", "RestartCcSwitch"):
        assert token not in poll


def test_route_switch_restart_has_flap_circuit_breaker():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    # Storm-guard state + tunables.
    assert "private bool routeFlapCircuitOpen;" in text
    assert "RouteRestartCooldownSeconds" in text
    assert "RouteFlapThreshold" in text
    assert "RouteFlapSettleSeconds" in text
    # A dedicated rate-limited helper restarts Codex for BOTH switch branches.
    assert "private bool RestartCodexForRouteSwitch(string reason, string routeKey)" in text
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert 'RestartCodexForRouteSwitch("Official route / ChatGPT account reload", route.Key)' in poll
    assert 'RestartCodexForRouteSwitch("third-party route " + route.Model, route.Key)' in poll
    # While the circuit is open the whole switch handler (repair included) is paused.
    assert "route-switch handling paused: flap circuit is open" in poll
    # Every genuine switch edge re-arms the one-shot repair latch (repeat-switch fix),
    # and the re-arm MUST precede the flap-circuit gate so a re-switch to the SAME
    # third-party provider is never blocked by a stale latch while the circuit is open.
    assert 'ccSwitchRepairDoneKey = "";' in poll
    assert poll.find('ccSwitchRepairDoneKey = "";') < poll.find(
        "route-switch handling paused: flap circuit is open"
    )
    # A third-party edge settles before reading auth.json to avoid a credential race
    # (a just-left Official credential would otherwise mask the repair need).
    assert "Thread.Sleep(800)" in poll
    # Deferred reconciliation: a switch suppressed by the cooldown/circuit is
    # remembered and re-applied once the route settles, so a rate-limited switch
    # (e.g. Official with no Codex restart, then several third-parties) is never
    # silently dropped leaving Codex stale / CC Switch unrepaired.
    assert "private string pendingRouteReconcileKey" in text
    assert "Reconciling settled route after a suppressed switch" in poll
    assert "lastHandledKey = ReconcileSentinelKey;" in poll
    assert "pendingRouteReconcileKey = route.Key;" in poll
    # The circuit re-arms only after the route stays stable.
    assert "Route flap circuit re-armed after the route stayed stable." in text
    helper = _method_body(text, "private bool RestartCodexForRouteSwitch", "private void RestartCodexForExit")
    assert "suppressedRouteRestartCount++" in helper
    assert "routeFlapCircuitOpen = true" in helper
    assert "RestartCodex(reason);" in helper


def test_restart_codex_never_terminates_an_editor_hosted_backend():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void RestartCodex(string reason", "private bool RestartCodexForRouteSwitch")
    # A headless Codex (no GUI window) is an editor-hosted backend (VS Code/Cursor).
    # During normal operation it is never terminated: killing it leaves the editor on a
    # "click to restart" page and, because route switches repeat, CodexBridge would keep
    # killing the respawning backend and make that page flicker between the restart,
    # restarting and login states. Instead the user is asked to restart Codex so the
    # editor owns its own lifecycle.
    assert "MainWindowHandle" in body
    assert "if (!hadGui && !exiting)" in body
    assert "editor-hosted backend" in body
    assert 'ui.T("Restart Codex to apply")' in body
    # The GUI path still cycles the process, and the Exit handoff (exiting) is unchanged.
    assert "KillProcessTree" in body


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


def test_watcher_baselines_existing_ccswitch_without_treating_login_as_new_edge():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    watcher = _method_body(text, "private static void RunCcSwitchWatcher()", "private static bool SourceIsNewerThanExe")
    assert "bool previousCcSwitchRunning = IsCcSwitchRunning();" in watcher
    assert "bool previousCcSwitchRunning = false;" not in watcher


def test_conversation_bridge_core_remains_unchanged():
    # Re-baselined for the sanctioned diagnostic-log sanitizer layer only
    # (_sanitize_log_text/_log plus wrapped print sites). The conversation
    # continuation core (resp_/msg_ mapping, provider continuation, resident-WS,
    # portable replay, compatibility firewall, strict tool repair, CompHash) is
    # unchanged.
    assert _normalized_sha256(BRIDGE) == "5d418498317fca43e6f8da9cbcef12f6ca4cbea737e98829845943effadfc351"


def test_manager_core_remains_unchanged():
    assert _normalized_sha256(MANAGER) == "b3f4befd2c3e0b48f034235bd248bddcd02b8d4991a402f34eed6d46a9475480"
