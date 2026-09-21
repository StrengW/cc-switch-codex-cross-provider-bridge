import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class QuickStartPathContractTests(unittest.TestCase):
    def test_cmd_is_location_independent_and_invokes_source_bootstrap(self):
        text = (ROOT / "Start CodexBridge.cmd").read_text(encoding="utf-8-sig")
        self.assertIn('pushd "%~dp0"', text)
        self.assertIn('StartCodexBridge.ps1"', text)
        self.assertNotIn('releases/latest', text.lower())
        self.assertNotIn('api.github.com', text.lower())

    def test_powershell_derives_root_and_sanitizes_stray_quotes(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("Resolve-CodexBridgeFullPath", text)
        self.assertIn("Trim([char]34)", text)
        self.assertIn("Join-Path $PSScriptRoot '..\\..'", text)

    def test_normal_user_path_bootstraps_private_python_without_release(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("Ensure-PortablePython", text)
        self.assertIn("www.python.org/ftp/python/3.12.10", text)
        self.assertIn("CodexProviderBridge", text)
        self.assertIn("source-bootstrap", text)
        self.assertNotIn("api.github.com/repos", text)
        self.assertNotIn("releases/latest", text.lower())

    def test_source_quickstart_replaces_stale_packaged_bridge_runtime(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$installedAppDir = Join-Path $stateRoot 'app'", text)
        self.assertIn("Get-Process -Name 'CodexBridgeLauncher'", text)
        self.assertIn("$installedManager stop", text)
        self.assertIn("$staleStandaloneBridge = Join-Path $installedAppDir 'codex_provider_bridge.exe'", text)
        self.assertIn("Remove-Item -LiteralPath $staleStandaloneBridge -Force", text)

    def test_source_quickstart_waits_for_old_launcher_roles_before_relaunch(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("Stop-InstalledLauncherProcesses", text)
        self.assertIn("Wait-Process", text)
        self.assertIn("Stop-InstalledLauncherProcesses -InstallRoot $installedAppDir", text)

    def test_windows_manager_can_find_bootstrapped_private_python(self):
        text = (ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("CodexProviderBridge\\runtime\\python\\python.exe", text)
        self.assertIn("$env:CPB_PYTHON", text)

    def test_launcher_registers_only_ccswitch_watcher_at_windows_login(self):
        text = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("--watch-ccswitch", text)
        self.assertIn("RegisterWatcherAutostart", text)
        self.assertNotIn('key.SetValue(StartupValueName, "\\\"" + exePath + "\\\" --autostart"', text)
        self.assertIn('private const string LauncherVersion = "', text)


if __name__ == "__main__":
    unittest.main()
