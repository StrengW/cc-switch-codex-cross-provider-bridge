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
    assert "CC\\\\s*Switch" not in text


def test_ccswitch_identity_requires_name_or_executable_path_match():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    name_body = _method_body(text, "private static bool IsCcSwitchName", "private static bool IsCcSwitchExecutablePath")
    path_body = _method_body(text, "private static bool IsCcSwitchExecutablePath", "private static bool IsRememberedCcSwitchExeValid")

    assert '^cc[-_ ]?switch$' in name_body
    assert "Path.GetFileNameWithoutExtension" in path_body
    assert "Path.GetDirectoryName" in path_body
    assert "IsCcSwitchName(fileName)" in path_body
    assert "IsCcSwitchName(directoryName)" in path_body


def test_remembered_ccswitch_path_is_validated_before_launch_and_kill():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    start_body = _method_body(text, "private bool StartCcSwitchFromRememberedTarget()", "private bool WaitForCcSwitchProxy")
    remember_body = _method_body(text, "private void RememberCcSwitch", "private static string SafeProcessPath")

    assert "IsRememberedCcSwitchExeValid(exe)" in start_body
    assert "Discarding remembered CC Switch path" in start_body
    assert "IsRememberedCcSwitchExeValid(path)" in remember_body
    assert "IsRememberedCcSwitchExeValid(resolved)" in remember_body


def test_ccswitch_launch_falls_back_to_shortcut_target():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    start_body = _method_body(text, "private bool StartCcSwitchFromRememberedTarget()", "private bool WaitForCcSwitchProxy")

    assert "ResolveShortcutTarget(shortcut)" in start_body
    assert "StartShell(shortcut)" in start_body
    assert "DiscoverShortcut(\"*CC*Switch*.lnk\")" in start_body


def test_ccswitch_discovery_probes_portable_fixed_drive_installs():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _method_body(text, "private string DiscoverCcSwitchExe()", "private static string DiscoverShortcut")

    assert "DriveInfo.GetDrives()" in body
    assert "DriveType.Fixed" in body
    assert '"CCSwitch", "cc-switch.exe"' in body
