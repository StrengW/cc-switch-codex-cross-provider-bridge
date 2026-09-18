from pathlib import Path
import os
import stat
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacOSPortabilityContractTests(unittest.TestCase):
    def test_manager_supports_repo_and_installed_sibling_runtime(self):
        text = (ROOT / "scripts" / "unix" / "codex_bridge_manager.sh").read_text(encoding="utf-8-sig")
        self.assertIn('CPB_PROJECT_ROOT=', text)
        self.assertIn('$CPB_SCRIPT_DIR/codex_provider_bridge.py', text)
        self.assertIn('$CPB_SCRIPT_DIR/python3', text)
        self.assertIn('$CPB_PROJECT_ROOT/src/bridge/codex_provider_bridge.py', text)
        self.assertIn('CPB_VERSION=', text)

    def test_double_click_macos_entrypoint_is_location_independent(self):
        path = ROOT / "Start CodexBridge.command"
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn('dirname -- "$0"', text)
        self.assertIn('Library/Application Support/CodexProviderBridge', text)
        self.assertIn('codex_bridge_watcher.sh', text)
        self.assertNotIn('/Users/', text)
        if os.name != "nt":
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR, "macOS launcher must be executable in Git")

    def test_macos_quickstart_bootstraps_runtime_and_launchagent(self):
        text = (ROOT / "Start CodexBridge.command").read_text(encoding="utf-8-sig")
        self.assertIn('UV_UNMANAGED_INSTALL', text)
        self.assertIn('python install 3.12', text)
        self.assertIn('com.strengw.codexbridge.watcher.plist', text)
        self.assertIn('launchctl bootstrap', text)
        self.assertIn('RunAtLoad', text)

    def test_macos_workflow_still_covers_arm_and_intel(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn('macos-15-intel', text)
        self.assertIn('macos-15', text)
        self.assertIn('aarch64-apple-darwin', text)
        self.assertIn('x86_64-apple-darwin', text)

    def test_macos_workflow_runs_on_main_push_and_tags(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("push:\n    branches:\n      - main\n    tags:\n      - 'v*'", text)


    def test_macos_workflow_validates_public_version_metadata(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn("Validate public version metadata", text)
        self.assertIn("does not match VERSION", text)
        self.assertIn("tr -d '[:space:]' < VERSION", text)

    def test_macos_workflow_uses_isolated_venv_for_pytest(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn('python3 -m venv "$RUNNER_TEMP/codexbridge-ci-venv"', text)
        self.assertIn('"$RUNNER_TEMP/codexbridge-ci-venv/bin/python" -m pip install --disable-pip-version-check pytest', text)
        self.assertIn('"$RUNNER_TEMP/codexbridge-ci-venv/bin/python" -m pytest tests -v', text)
        self.assertNotIn('run: python3 -m pip install --disable-pip-version-check pytest', text)

    def test_macos_workflow_normalizes_permissions_before_tests_and_verifies_archive(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn('Normalize macOS executable permissions', text)
        self.assertIn('chmod +x "Start CodexBridge.command"', text)
        self.assertIn('stage="$stage_parent/CodexBridge"', text)
        self.assertIn('cp README.md README.en.md VERSION CHANGELOG.md SECURITY.md', text)
        self.assertIn('CodexBridge $version / ${{ github.ref_name }} / ${{ matrix.arch }}', text)
        self.assertIn('test -f "$verify/CodexBridge/VERSION"', text)
        self.assertIn('test -f "$verify/CodexBridge/BUILD.txt"', text)
        self.assertIn('/usr/bin/ditto -x -k "dist/$ASSET" "$verify"', text)
        self.assertIn('test -x "$verify/CodexBridge/Start CodexBridge.command"', text)
        self.assertNotIn('| head -n 1', text)
        self.assertIn('git ls-files --stage -- "Start CodexBridge.command"', text)
        self.assertIn('releases/latest', text)
        self.assertIn('/assets?per_page=100', text)
        self.assertIn('gh api --paginate', text)
        self.assertIn('startswith(\\\"cpython-3.12.\\\")', text)
        self.assertIn('endswith(\\\"-${TARGET}-install_only_stripped.tar.gz\\\")', text)
        self.assertNotIn('assets[].browser_download_url | select(test(', text)

    def test_tagged_macos_release_publishes_clearly_labeled_unsigned_assets_without_apple_credentials(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn("apple_signing_available: ${{ steps.apple-signing.outputs.available }}", text)
        self.assertIn("publish clearly labeled unsigned macOS Release assets", text)
        self.assertNotIn("A tagged macOS Release requires Developer ID signing and Apple notarization credentials", text)
        self.assertIn("CodexBridge-macOS-AppleSilicon-unsigned.zip", text)
        self.assertIn("CodexBridge-macOS-Intel-unsigned.zip", text)
        self.assertIn("--options runtime", text)
        self.assertIn("--timestamp", text)
        self.assertIn("xcrun notarytool submit", text)
        self.assertIn("Apple notarization did not return Accepted", text)

    def test_macos_build_job_is_read_only_and_tag_release_gets_write_permission(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("release:\n    if: startsWith(github.ref, 'refs/tags/')", text)
        self.assertIn("contents: write", text)
        self.assertIn("pattern: CodexBridge-macOS-*", text)
        self.assertIn("merge-multiple: true", text)
        self.assertIn("Wait for the GitHub Release created by Windows", text)

    def test_macos_release_commands_explicitly_target_repository(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        self.assertIn('gh release view "$tag" --repo "$GITHUB_REPOSITORY"', text)
        self.assertIn('gh release upload "$tag" "${assets[@]}"', text)
        self.assertGreaterEqual(text.count('--repo "$GITHUB_REPOSITORY"'), 2)

    def test_macos_watcher_automates_provider_switch_restart_policy(self):
        text = (ROOT / "scripts" / "unix" / "codex_bridge_watcher.sh").read_text(encoding="utf-8-sig")
        self.assertIn('route_kind', text)
        self.assertIn('restart_cc_switch', text)
        self.assertIn('restart_codex', text)
        self.assertIn('third-party', text)
        self.assertIn('official', text)
        self.assertIn('Initial resident route', text)
        self.assertIn('restoring proxy without restarting Codex', text)


if __name__ == "__main__":
    unittest.main()
