from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleasePortabilityContractTests(unittest.TestCase):
    def test_release_payload_requires_standalone_bridge(self):
        text = (ROOT / "scripts" / "build" / "BuildCodexBridgeSetup.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("codex_provider_bridge.exe'; Required = $true", text)
        self.assertIn("End-user releases must not depend on Python", text)

    def test_setup_requires_standalone_bridge(self):
        text = (ROOT / "src" / "setup" / "CodexBridgeSetup.cs").read_text(encoding="utf-8-sig")
        self.assertIn("standalone codex_provider_bridge.exe runtime", text)
        self.assertIn("--silent", text)
        self.assertIn("--root", text)
        self.assertIn("Environment.Is64BitOperatingSystem", text)

    def test_launcher_prefers_standalone_bridge_and_resolves_system_powershell(self):
        text = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
        self.assertIn('codex_provider_bridge.exe', text)
        self.assertIn('System32\\WindowsPowerShell\\v1.0\\powershell.exe', text)
        self.assertNotIn('psi.FileName = "powershell.exe";', text)

    def test_ci_smoke_tests_unicode_install_path_and_setup_checksum(self):
        text = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("Unicode path", text)
        self.assertIn("测试 with spaces", text)
        self.assertIn("CodexBridge-Setup.exe.sha256", text)


if __name__ == "__main__":
    unittest.main()


def test_windows_workflow_installs_pyinstaller_and_runs_all_pytest_contracts():
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    assert "python -m pip install --disable-pip-version-check pytest pyinstaller" in workflow
    assert "python -m pytest tests -v" in workflow
    assert "python -m unittest discover -s tests -v" not in workflow
