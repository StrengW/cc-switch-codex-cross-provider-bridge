from pathlib import Path


def test_exit_dialog_follows_windows_ui_culture():
    src = Path("src/launcher/CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    assert "CultureInfo.CurrentUICulture.Name" in src
    assert "警告：彻底退出 CodexBridge？" in src
    assert "警告：徹底退出 CodexBridge？" in src
    assert "Warning: Exit CodexBridge completely?" in src
    assert "重新打开 CC Switch 后，CodexBridge 会自动启动。" in src
    assert "重新開啟 CC Switch 後，CodexBridge 會自動啟動。" in src
    assert "MessageBoxIcon.Warning" in src
    assert "MessageBoxButtons.YesNo" in src
    assert "MessageBoxDefaultButton.Button2" in src


def test_localization_change_does_not_touch_bridge_core_contract():
    src = Path("src/launcher/CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    assert 'private const string LauncherVersion = "' in src
