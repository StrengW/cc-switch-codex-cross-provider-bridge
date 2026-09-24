import pathlib
import re
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

    def test_first_run_download_cannot_hang_and_proves_where_it_came_from(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        # Windows PowerShell treats a missing -TimeoutSec as "wait forever", so a
        # filtered or blackholed python.org used to hang the first run on
        # "Preparing private Python runtime" without ever printing an error.
        self.assertIn("-TimeoutSec", text)
        self.assertIn("Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination -TimeoutSec", text)
        # python.org alone is not reachable for every user. Mirrors are only safe
        # because each download is checked against a pinned digest.
        for mirror in (
            "https://www.python.org/ftp/python/3.12.10",
            "https://mirrors.huaweicloud.com/python/3.12.10",
            "https://registry.npmmirror.com/-/binary/python/3.12.10",
        ):
            self.assertIn(mirror, text)
        self.assertIn("Get-FileHash -LiteralPath $Destination -Algorithm SHA256", text)
        self.assertIn("SHA-256 mismatch", text)
        self.assertIn("No pinned SHA-256 for Python runtime package", text)

    def test_every_selectable_runtime_package_has_a_pinned_digest(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        # A Python version bump must not be able to ship a package name that has
        # no digest: the download would then be refused at run time on every
        # machine, which is exactly the failure this guard prevents.
        selectable = set(re.findall(r"return '(python-[^']+\.zip)'", text))
        pinned = set(re.findall(r"'(python-[^']+\.zip)' = '([0-9a-f]{64})'", text))
        pinned_names = {name for name, _ in pinned}
        self.assertEqual(3, len(selectable))
        self.assertEqual(selectable, pinned_names)

    def test_first_run_failure_is_reported_in_the_user_language_and_logged(self):
        text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(
            encoding="utf-8-sig"
        )
        # Same culture detection as the uninstaller, so one user never gets a
        # Chinese dialog and an English console.
        self.assertIn("[Globalization.CultureInfo]::CurrentUICulture.Name", text)
        self.assertIn("zh-Hant*", text)
        self.assertIn("bootstrap.log", text)
        self.assertIn("首次运行需要联网获取 Python 运行时", text)
        self.assertIn("首次執行需要聯網取得 Python 執行階段", text)
        self.assertIn("The first run has to download a Python runtime", text)


if __name__ == "__main__":
    unittest.main()
