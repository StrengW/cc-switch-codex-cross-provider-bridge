from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleasePortabilityContractTests(unittest.TestCase):
    def test_formal_windows_release_uses_source_bootstrap_archive(self):
        text = (ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("CodexBridge-Windows.zip", text)
        self.assertIn("must not accidentally regress", text)
        self.assertIn("*.exe", text)
        self.assertIn("Start CodexBridge.cmd", text)
        self.assertIn("'VERSION'", text)
        self.assertIn("'CHANGELOG.md'", text)
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
        self.assertIn("Release package VERSION mismatch", text)

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


def test_windows_workflow_runs_on_main_and_tags_and_validates_version():
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    assert "push:\n    branches:\n      - main\n    tags:\n      - 'v*'" in workflow
    assert "Validate public version metadata" in workflow
    assert 'does not match VERSION' in workflow


def test_windows_release_bundles_the_official_runtime_without_shipping_executables():
    build = (ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1").read_text(encoding="utf-8-sig")
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    # The runtime travels as the untouched upstream archive, so the "no .exe"
    # guard stays exactly as strict as it was instead of being relaxed to let a
    # python.exe through. Re-packing upstream bytes would also make the pinned
    # digest unverifiable against python.org by a user who wants to check.
    assert "Safe Windows release package must not contain prebuilt .exe files" in workflow
    assert "-BundledRuntimeDir" in build
    assert 'BundledRuntimeDir "$PWD\\.build\\bundled-runtime"' in workflow
    assert "Bundled Python runtime digest mismatch" in build
    assert "runtime\\python-3.12.10-embed-amd64.zip" in workflow
    assert "must not fall back to a network download" in workflow


def test_pinned_runtime_digest_agrees_everywhere_it_appears():
    start = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(encoding="utf-8-sig")
    build = (ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1").read_text(encoding="utf-8-sig")
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    amd64 = re.search(r"'python-3\.12\.10-embed-amd64\.zip' = '([0-9a-f]{64})'", start).group(1)
    # Three copies of one value are only safe if a test fails the moment they
    # drift. A stale digest here would brick first run for every Windows user.
    assert {amd64} == set(re.findall(r"\b[0-9a-f]{64}\b", build))
    assert {amd64} == set(re.findall(r"\b[0-9a-f]{64}\b", workflow))


def test_bundled_runtime_is_tried_before_any_download():
    text = (ROOT / "scripts" / "windows" / "StartCodexBridge.ps1").read_text(encoding="utf-8-sig")
    workflow = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(encoding="utf-8")
    body = text[text.index("function Ensure-PortablePython"):]
    # Bundled first, then the mirrors, then a Python the user already installed.
    # Anything else would leave the common case depending on python.org again.
    assert body.index('Join-Path $ProjectRoot "runtime\\$package"') < body.index("Get-PythonRuntimePackage -Package")
    assert "Install-PythonRuntimeFromZip" in text
    assert "[switch]$PrepareRuntimeOnly" in text
    assert "[string]$StateRootOverride" in text
    # The diagnostic exit has to happen before the script starts stopping
    # processes or rewriting the installed copy.
    assert text.index("if ($PrepareRuntimeOnly)") < text.index("Stop-InstalledLauncherProcesses -InstallRoot")
    # CI is the only caller of that diagnostic mode, so pin the invocation here.
    assert "-StateRootOverride $coldRoot -PrepareRuntimeOnly" in workflow
