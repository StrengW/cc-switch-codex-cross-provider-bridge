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
    # Every current Codex form is a headless "app-server" backend owned by a GUI host
    # (VS Code/Cursor, or the ChatGPT desktop app). codex.exe never owns a top-level
    # window, so during normal operation the backend is never terminated: killing it
    # leaves the host on a "click to restart" page and, because route switches repeat,
    # CodexBridge would keep killing the respawning backend and make that page flicker
    # between the restart, restarting and login states. Instead the user is asked to
    # restart Codex so the host owns its own lifecycle.
    assert "if (!exiting)" in body
    assert "host-owned app-server backend" in body
    assert 'ui.T("Restart Codex to apply")' in body
    # The Exit handoff (exiting == true) still cycles the backend and waits for the
    # host to respawn it, so that path is unchanged.
    assert "KillProcessTree" in body
    assert "Codex backend respawned by its host." in body


def test_dead_standalone_gui_restart_code_is_removed():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    # codex.exe is always a headless app-server backend (it never owns a top-level
    # window), so the old "remember the GUI exe, then kill and relaunch it" machinery
    # could never fire: the hadGui flag was permanently false and the relaunch branch
    # was unreachable. It is removed entirely so the code no longer advertises an
    # auto-restart path that does not exist; the restart decision now keys only on
    # exiting (normal switch = remind the user, Exit handoff = cycle the backend).
    assert "hadGui" not in text
    assert "RememberLaunchTargets" not in text
    assert "codex_gui_exe" not in text
    assert "Codex GUI relaunched" not in text
    assert "Codex GUI was closed" not in text
    # RestartCodex no longer probes the process window handle to pick the restart path.
    # Match the probe expression, not the bare word: the explanatory comment still says
    # "MainWindowHandle is always 0", and the CC Switch stop path calls CloseMainWindow().
    body = _method_body(text, "private void RestartCodex(string reason", "private bool RestartCodexForRouteSwitch")
    assert "processes[i].MainWindowHandle" not in body


def test_editor_hosted_restart_reminder_is_durable_not_only_a_transient_balloon():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void RestartCodex(string reason", "private bool RestartCodexForRouteSwitch")
    # Runtime evidence: a Win32 tray balloon is delivered and then cleared about seven
    # seconds later, and never reaches the notification store, so a balloon alone is far
    # too easy to miss and leaves no trace. The editor-hosted branch must therefore also
    # raise a durable tray reminder before it notifies.
    assert "RaisePendingCodexRestart(reason, processes)" in body
    assert body.index("RaisePendingCodexRestart(reason, processes)") < body.index('ui.T("Restart Codex to apply")')
    # The path that really cycles Codex withdraws any outstanding reminder.
    assert "ClearPendingCodexRestart();" in body

    raise_body = _method_body(text, "private void RaisePendingCodexRestart", "private void ClearPendingCodexRestart()")
    assert "badgedTrayIcon" in raise_body
    assert "SetTrayTooltip" in raise_body
    assert "pendingRestartItem.Visible = true" in raise_body
    # The reminder is keyed on the Codex process identity captured at raise time.
    assert "ProcessSignature(codexProcesses)" in raise_body
    # NotifyIcon.Text throws past 63 characters, so the tooltip is clamped instead.
    assert "text.Length > 63" in text

    # Withdrawn only when the Codex process identity actually changed (user reloaded).
    clear_body = _method_body(text, "private void ClearPendingCodexRestartIfApplied", "private void CheckForUpdates")
    assert "CurrentCodexProcessSignature()" in clear_body
    assert "current == pendingCodexProcessSig" in clear_body
    assert "ClearPendingCodexRestart();" in clear_body
    # Throttled: the poll timer ticks every 400ms, so process enumeration is rate limited.
    assert "lastPendingCodexCheckUtc" in clear_body

    # The poll tick withdraws the reminder even while automatic restarts are paused.
    head = text.index("private void PollTimerTick")
    poll_head = text[head:head + 600]
    assert poll_head.index("ClearPendingCodexRestartIfApplied()") < poll_head.index("if (paused) return;")

    # Every new user-visible string is localized (simplified and traditional).
    ui_text = (ROOT / "src" / "launcher" / "LauncherUiText.cs").read_text(encoding="utf-8-sig")
    for key in (
        "Restart Codex in your editor to apply the new provider",
        "CodexBridge: restart Codex to apply the new provider",
        "Waiting for you to restart Codex",
    ):
        assert 'case "' + key + '"' in ui_text


def test_editor_hosted_switch_raises_a_modal_restart_dialog():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private void RestartCodex(string reason", "private bool RestartCodexForRouteSwitch")
    # A tray badge is passive and a balloon is transient: neither interrupts a user who
    # never looks at the tray, so a switch that only takes effect after reloading Codex
    # could silently stay unapplied. The macOS launcher already raises a modal alert, so
    # the editor-hosted branch must match it and interrupt actively.
    assert "ShowRestartCodexDialog();" in body
    assert body.index("RaisePendingCodexRestart(reason, processes)") < body.index("ShowRestartCodexDialog();")
    # Only the editor-hosted branch interrupts: the GUI path cycles Codex itself.
    assert body.index("ShowRestartCodexDialog();") < body.index("ClearPendingCodexRestart();")

    dialog = _method_body(text, "private void ShowRestartCodexDialog()", "private void ClearPendingCodexRestart()")
    # The alert must be a topmost window, not MessageBox: an ownerless MessageBox is an
    # ordinary top-level window, and the Windows foreground lock forbids a background
    # process (this tray launcher) from activating it, so runtime evidence showed the
    # dialog opening BEHIND the maximized editor the user was working in. A WS_EX_TOPMOST
    # window stays above every non-topmost window regardless of activation.
    assert "dialog.TopMost = true;" in dialog
    assert "ShowDialog();" in dialog
    assert "SystemIcons.Warning.ToBitmap()" in dialog
    assert "MessageBox.Show(" not in dialog
    assert 'ui.T("Restart Codex to apply")' in dialog
    # One dialog at a time: the guard runs on the UI thread inside the callback, so
    # switches arriving while a dialog is already waiting cannot stack a second dialog.
    assert "private bool restartDialogOpen;" in text
    assert "if (exiting || restartDialogOpen) return;" in dialog
    assert "restartDialogOpen = false;" in dialog
    # Topmost is re-asserted after the dialog is shown and once a second while it waits,
    # without stealing focus: the Z order must not depend on activation. A dialog created
    # on the UI (STA) thread is required for any of this to hold; the tray menu cannot
    # act as the dispatcher because its handle is created lazily and
    # ToolStrip.InvokeRequired then reports FALSE on worker threads -- which is how the
    # switch handler (thread pool) once ran the modal dialog on a pool thread with no UI
    # message pump and no foreground rights, leaving it behind the maximized editor.
    assert "ReassertTopMost(dialog)" in dialog
    assert "SetWindowPos(dialog.Handle, HwndTopMost" in text
    assert "SwpNoActivate" in text
    assert "private readonly Control uiDispatcher;" in text
    assert "uiDispatcher.Handle.ToString();" in text
    runner = _method_body(text, "private void RunOnUiThread", "private void StopBridgeForUpdate")
    assert "uiDispatcher.InvokeRequired" in runner
    assert "menu.BeginInvoke" not in runner
    # The dialog body is localized alongside every other reminder string, and so is the
    # confirm button (a plain MessageBox would have localized it for us).
    ui_text = (ROOT / "src" / "launcher" / "LauncherUiText.cs").read_text(encoding="utf-8-sig")
    assert 'case "Codex keeps the previous provider until it is reloaded.' in ui_text
    assert 'case "OK":' in ui_text


def test_route_switch_edge_is_keyed_on_route_model_not_constant_source_path():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    snap = _method_body(text, "private RouteSnapshot ReadRouteSnapshot()", "private bool IsCustomDirectOfficialRoute()")
    # Runtime evidence (the Route snapshot diagnostic) proved the sidecar's source_path is
    # CONSTANT across every provider -- CC Switch writes all providers into one
    # cc-switch-model-catalog.json -- so the switch edge must be keyed on route_model, which
    # is what actually changes on a real provider switch (Official -> third-party and
    # third-party -> third-party). Keying on source_path made every third-party provider
    # share one key, so a third-party -> third-party switch produced no edge at all.
    assert 'r.Key = kind == "official" ? "official" : "third-party|" + r.Model;' in snap
    # The source_path-based identity was the wrong discriminator and must be gone.
    assert "string identity = r.Source.Length > 0 ? r.Source : r.Model;" not in snap
    assert '"third-party|" + identity' not in snap
    # A route-snapshot diagnostic lets a switch that fails to trigger be traced to the
    # exact fields the bridge wrote into the sidecar.
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert "Route snapshot: kind=" in poll
    assert "lastLoggedRouteSig" in poll


def test_failed_ccswitch_repair_is_terminal_and_never_reconciles_into_a_loop():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    # A failed CC Switch repair must be TERMINAL for the edge: it notifies once and returns
    # WITHOUT deferring to reconciliation. Setting pendingRouteReconcileKey on a failed
    # repair re-fires the same edge, re-arms the one-shot latch, and kills/relaunches CC
    # Switch forever -- the infinite restart loop observed at runtime (27 kills in ~4 min).
    fail_branch = poll.split("else if (IsThirdPartyAuthRepairNeeded(route))", 1)[1].split("else", 1)[0]
    assert "Not reconciling: a failed repair must not retry in a loop." in fail_branch
    assert "pendingRouteReconcileKey = route.Key" not in fail_branch
    assert "return;" in fail_branch


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


def test_bridge_reinfers_route_when_selected_model_is_foreign():
    # Runtime evidence (40ms sampling of a live switch): CC Switch now persists a
    # Codex config template that already points at the bridge, so a provider switch
    # writes model_provider/base_url unchanged and only swaps the selected model and
    # the catalog reference. The guard must treat a selected model outside the
    # current route models as a switch edge, because a real in-picker change always
    # stays inside the models this route published.
    text = BRIDGE.read_text(encoding="utf-8-sig")
    guard = _method_body(text, "    def guard_once(self) -> None:", "    def _run(self) -> None:")
    assert "known_route_models = set(self.route_models)" in guard
    assert "selected_model not in known_route_models" in guard
    assert "if not known_route or foreign_model:" in guard
    assert "is not offered by the current route" in guard


def test_conversation_bridge_core_remains_unchanged():
    # Re-baselined for the sanctioned diagnostic-log sanitizer layer only
    # (_sanitize_log_text/_log plus wrapped print sites), and again for the
    # sanctioned route-edge inference fix in CatalogConfigGuard.guard_once (a
    # selected model outside the known route models is a provider switch edge).
    # Re-baselined again for the Official-route HTTP fix: _handle resolves the
    # route once and sends Official /responses to the ChatGPT backend rather than
    # to CC Switch, the guard re-asserts its own config keys every pass so
    # supports_websockets cannot stay stale, config reads retry through a
    # transient lock, and the unreferenced _set_config_catalog is removed.
    # The conversation continuation core (resp_/msg_ mapping, provider
    # continuation, resident-WS, portable replay, compatibility firewall, strict
    # tool repair, CompHash) is unchanged.
    assert _normalized_sha256(BRIDGE) == "11bda5ae3300aecac9202c4e0885c5f68e7181b89d3ddb51284bd968d9a87a5f"


def test_manager_core_remains_unchanged():
    # Re-baselined for the sanctioned backup-retention change: the manager now
    # caps the config.toml backups it writes beside the user's own config,
    # keeping the newest three of each family instead of adding one per rewrite
    # until a full uninstall removes them. The lifecycle logic it drives (start,
    # repair, switch detection, stop) is unchanged.
    assert _normalized_sha256(MANAGER) == "260c8ff75e9c139d62233838f7b6701acd6f279cb903d6949c55bb31a69ee052"
