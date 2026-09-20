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


def test_launcher_has_no_automatic_ccswitch_start_or_restart_helpers():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    for token in ("StartCcSwitchFromRememberedTarget", "EnsureCcSwitchProxyRunning", "RestartCcSwitch", "DiscoverCcSwitchExe"):
        assert token not in text


def test_explicit_exit_is_the_only_ccswitch_stop_path_in_launcher():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    exit_body = _method_body(text, "private void StopCcSwitchForExit()", "private static bool IsTraditionalChineseUiCulture")
    assert "FindCcSwitchProcesses()" in exit_body
    assert "KillProcessTree" in exit_body
    supervisor = _method_body(text, "private void SuperviseThirdPartyProxy", "private void RestartCodex")
    assert "KillProcessTree" not in supervisor
    assert "FindCcSwitchProcesses" not in supervisor
