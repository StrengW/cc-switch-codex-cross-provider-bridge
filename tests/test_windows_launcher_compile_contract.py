from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"


def _program_body(text: str) -> str:
    marker = "internal static class Program"
    start = text.index(marker)
    return text[start:]


def test_powershell_exe_path_is_defined_on_program_where_callers_expect_it():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    program = _program_body(text)
    assert "internal static string PowerShellExePath()" in program
    assert text.count("Program.PowerShellExePath()") >= 4


def test_launcher_compile_fix_version_is_present():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    assert 'LauncherVersion = "1.7.9-standard-uninstall"' in text


def test_removed_ccswitch_trigger_flag_is_not_referenced():
    text = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "ccSwitchAutoStartEnabled" not in text
