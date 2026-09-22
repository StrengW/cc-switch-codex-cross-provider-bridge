from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"
UI = ROOT / "src" / "launcher" / "LauncherUiText.cs"


FORBIDDEN = (
    "DiscoverCcSwitchExe",
    "StartCcSwitchFromRememberedTarget",
    "EnsureCcSwitchProxyRunning",
    "RestartCcSwitch",
    "ccSwitchAutoStartEnabled",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _method_body(text: str, signature: str, next_signature: str) -> str:
    start = text.index(signature)
    end = text.index(next_signature, start)
    return text[start:end]


def test_forbidden_discovery_and_autorevive_helpers_are_absent():
    text = _read(LAUNCHER)
    for token in FORBIDDEN:
        assert token not in text


def test_repair_detection_is_read_only_and_never_writes_auth_json():
    text = _read(LAUNCHER)
    detect = _method_body(text, "private bool IsThirdPartyAuthRepairNeeded", "private bool HasLiveChatGptCredential")
    cred = _method_body(text, "private bool HasLiveChatGptCredential", "private void EnsureBridgeRunning")
    # Provable condition: third-party route + requires_openai_auth=true + no live cred.
    assert '"third-party"' in detect
    assert "requires_openai_auth" in detect
    assert "live_chatgpt_cred=" in detect
    # Logs only a structural boolean, never a token value.
    assert '(liveCred ? "true" : "false")' in detect
    assert "access_token" in cred
    assert "refresh_token" in cred
    for body in (detect, cred):
        assert "WriteAllText" not in body
        assert "File.WriteAll" not in body
        assert "SaveStateValue" not in body
        assert "Delete" not in body


def test_repair_binds_only_the_live_verified_instance_and_never_persists_it():
    text = _read(LAUNCHER)
    bind = _method_body(text, "private bool TryBindLiveCcSwitchExecutablePath", "private bool RestartBoundCcSwitchInstanceOnce")
    assert "FindCcSwitchProcesses()" in bind
    assert "SafeProcessPath" in bind
    assert "IsCcSwitchExecutablePath(path)" in bind
    assert "MainWindowTitle" not in bind
    assert "SaveStateValue" not in bind
    assert "GetState" not in bind


def test_repair_restart_is_bounded_and_relaunches_the_same_bound_path():
    text = _read(LAUNCHER)
    repair = _method_body(text, "private bool RestartBoundCcSwitchInstanceOnce", "private static bool IsTraditionalChineseUiCulture")
    assert "File.Exists(boundPath)" in repair
    assert "AddSeconds(25)" in repair
    assert 'WaitForPortClosed("CC Switch", 15721' in repair
    assert "StartDetached(boundPath" in repair
    assert 'TestTcpPort("127.0.0.1", 15721' in repair
    # Never discovers or persists a path; only relaunches the bound one.
    assert "SaveStateValue" not in repair
    for token in FORBIDDEN:
        assert token not in repair


def test_repair_is_one_shot_latched_and_suppresses_the_supervisor():
    text = _read(LAUNCHER)
    assert "private volatile bool ccSwitchRepairInProgress;" in text
    assert 'private string ccSwitchRepairDoneKey = "";' in text
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert "ccSwitchRepairDoneKey != route.Key" in poll
    assert "ccSwitchRepairDoneKey = route.Key" in poll
    assert "ccSwitchRepairInProgress = true" in poll
    assert "ccSwitchRepairInProgress = false" in poll
    supervisor = _method_body(text, "private void SuperviseThirdPartyProxy", "private void RestartCodex")
    assert "if (ccSwitchRepairInProgress) return;" in supervisor


def test_repair_runs_only_on_a_provider_switch_edge_never_on_a_proxy_drop():
    text = _read(LAUNCHER)
    poll = _method_body(text, "private void PollTimerTick", "private string FriendlyRoute")
    assert "RestartBoundCcSwitchInstanceOnce(boundPath)" in poll
    # The supervisor (proxy-drop path) must never invoke the repair.
    supervisor = _method_body(text, "private void SuperviseThirdPartyProxy", "private void RestartCodex")
    assert "RestartBoundCcSwitchInstanceOnce" not in supervisor
    assert "TryBindLiveCcSwitchExecutablePath" not in supervisor
    # On repair failure the Codex restart is skipped to avoid the login screen.
    assert "skipping Codex restart to avoid the login screen" in poll


def test_repair_localization_keys_exist_and_no_manual_restart_menu():
    ui_text = _read(UI)
    assert "Repairing provider switch (restarting CC Switch once)..." in ui_text
    assert "Provider switch repair" in ui_text
    assert "Repair failed: please reopen CC Switch, then switch the provider again." in ui_text
    # No manual "Restart CC Switch" tray menu is introduced (trigger is automatic).
    assert 'ui.T("Restart CC Switch")' not in _read(LAUNCHER)
