from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleasePortabilityContractTests(unittest.TestCase):
    def test_formal_windows_release_uses_source_bootstrap_archive(self):
        text = (ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("CodexBridge-Windows.zip", text)
        self.assertIn("must not accidentally regress", text)
        self.assertIn("*.exe", text)
        self.assertIn("Start CodexBridge.cmd", text)
        self.assertIn("codex_provider_bridge.py", text)
        self.assertNotIn("BuildStandaloneBridge.ps1", text)
        self.assertNotIn("BuildCodexBridgeSetup.ps1", text)

    def test_legacy_setup_source_remains_available_but_is_not_formal_release_path(self):
        self.assertTrue((ROOT / "src" / "setup" / "CodexBridgeSetup.cs").is_file())
        self.assertTrue((ROOT / "scripts" / "build" / "BuildCodexBridgeSetup.ps1").is_file())
        workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
        self.assertNotIn("BuildCodexBridgeSetup.ps1", workflow)
        self.assertNotIn("BuildStandaloneBridge.ps1", workflow)
        self.assertNotIn("pyinstaller", workflow.lower())
        self.assertNotIn("CodexBridge-Setup.exe", workflow)

    def test_launcher_runtime_contract_is_unchanged(self):
        text = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
        self.assertIn("codex_provider_bridge.exe", text)
        self.assertIn('System32\\WindowsPowerShell\\v1.0\\powershell.exe', text)
        self.assertNotIn('psi.FileName = "powershell.exe";', text)

    def test_ci_smoke_tests_unicode_release_path_and_zip_checksum(self):
        text = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("Unicode path", text)
        self.assertIn("测试 with spaces", text)
        self.assertIn("CodexBridge-Windows.zip.sha256", text)
        self.assertIn("Safe Windows release package must not contain prebuilt .exe files", text)

    def test_build_job_is_read_only_and_tag_release_gets_write_permission(self):
        text = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("release:\n    if: startsWith(github.ref, 'refs/tags/')", text)
        self.assertIn("contents: write", text)

    def test_windows_release_commands_explicitly_target_repository(self):
        text = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
        self.assertIn('gh release view "$tag" --repo "$GITHUB_REPOSITORY"', text)
        self.assertGreaterEqual(text.count('--repo "$GITHUB_REPOSITORY"'), 3)


if __name__ == "__main__":
    unittest.main()


def test_windows_workflow_pins_pytest_and_runs_all_pytest_contracts():
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    assert "pytest==9.0.2" in workflow
    assert "python -m pytest tests -v" in workflow
    assert "pyinstaller" not in workflow.lower()
