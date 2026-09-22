from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"


def _method_body(text: str, signature: str, next_signature: str) -> str:
    start = text.index(signature)
    end = text.index(next_signature, start)
    return text[start:end]


def test_ccswitch_detection_never_uses_window_titles():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private List<Process> FindCcSwitchProcesses()", "private static bool IsCcSwitchName")
    assert "MainWindowTitle" not in body
    assert "IsCcSwitchName(name)" in body
    assert "IsCcSwitchExecutablePath(path)" in body
    assert "CC\\s*Switch" not in text


def test_ccswitch_identity_requires_name_or_executable_path_match():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    name_body = _method_body(text, "private static bool IsCcSwitchName", "private static bool IsCcSwitchExecutablePath")
    path_body = _method_body(text, "private static bool IsCcSwitchExecutablePath", "private List<Process> FindCodexProcesses")
    assert "^cc[-_ ]?switch$" in name_body
    assert "Path.GetFileNameWithoutExtension" in path_body
    assert "Path.GetDirectoryName" in path_body
    assert "IsCcSwitchName(fileName)" in path_body
    assert "IsCcSwitchName(directoryName)" in path_body


def test_launcher_forbids_discovery_remembered_and_autorevive_ccswitch_helpers():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    # Discovery / remembered-path / default-path launching and proxy-drop auto-revive
    # stay forbidden. The only CC Switch (re)start path is the bounded repair below.
    for token in ("StartCcSwitchFromRememberedTarget", "EnsureCcSwitchProxyRunning", "RestartCcSwitch", "DiscoverCcSwitchExe", "ccSwitchAutoStartEnabled"):
        assert token not in text
    # The single sanctioned restart binds the live, path-verified instance only.
    assert "RestartBoundCcSwitchInstanceOnce" in text
    assert "TryBindLiveCcSwitchExecutablePath" in text
    bind = _method_body(text, "private bool TryBindLiveCcSwitchExecutablePath", "private bool RestartBoundCcSwitchInstanceOnce")
    assert "FindCcSwitchProcesses()" in bind
    assert "SafeProcessPath" in bind
    assert "IsCcSwitchExecutablePath(path)" in bind
    assert "MainWindowTitle" not in bind
    # The bound path is never persisted and never read back from state.
    assert "SaveStateValue" not in bind
    assert "GetState" not in bind


def test_ccswitch_stop_paths_are_exit_and_bounded_repair_only():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    exit_body = _method_body(text, "private void StopCcSwitchForExit()", "private static bool AnyProcessesAlive")
    assert "FindCcSwitchProcesses()" in exit_body
    assert "KillProcessTree" in exit_body

    # The repair restart is the only other stop+start path, and it is bounded.
    repair = _method_body(text, "private bool RestartBoundCcSwitchInstanceOnce", "private static bool IsTraditionalChineseUiCulture")
    assert "File.Exists(boundPath)" in repair
    assert "FindCcSwitchProcesses()" in repair
    assert "KillProcessTree" in repair
    assert 'WaitForPortClosed("CC Switch", 15721' in repair
    assert "StartDetached(boundPath" in repair
    assert 'TestTcpPort("127.0.0.1", 15721' in repair
    assert "AddSeconds(25)" in repair

    # The proxy supervisor stays observation-only: it never stops/starts CC Switch and
    # never invokes the repair, so a proxy drop or user close cannot revive it.
    supervisor = _method_body(text, "private void SuperviseThirdPartyProxy", "private void RestartCodex")
    assert "KillProcessTree" not in supervisor
    assert "FindCcSwitchProcesses" not in supervisor
    assert "RestartBoundCcSwitchInstanceOnce" not in supervisor
    assert "TryBindLiveCcSwitchExecutablePath" not in supervisor
    assert "ccSwitchRepairInProgress" in supervisor
