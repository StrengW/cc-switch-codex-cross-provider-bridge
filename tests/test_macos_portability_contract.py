from pathlib import Path
import os
import stat
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacOSPortabilityContractTests(unittest.TestCase):
    def test_macos_launcher_source_and_bundle_template_exist(self):
        source = ROOT / "src" / "launcher-macos" / "CodexBridgeLauncher.swift"
        plist = ROOT / "src" / "launcher-macos" / "Info.plist.in"
        self.assertTrue(source.is_file())
        self.assertTrue(plist.is_file())
        source_text = source.read_text(encoding="utf-8")
        plist_text = plist.read_text(encoding="utf-8")
        for token in ("import AppKit", "NSStatusItem", "NSMenu", "Process", "Unknown", "Exit CodexBridge", "Uninstall CodexBridge"):
            self.assertIn(token, source_text)
        self.assertIn("com.strengw.codexbridge.launcher", plist_text)
        self.assertIn("LSUIElement", plist_text)
        self.assertIn("@VERSION@", plist_text)

    def test_macos_launcher_has_safe_localized_lifecycle_and_uninstall_contract(self):
        source = (ROOT / "src" / "launcher-macos" / "CodexBridgeLauncher.swift").read_text(encoding="utf-8")
        uninstall = ROOT / "scripts" / "unix" / "codex_bridge_uninstall.sh"
        self.assertTrue(uninstall.is_file())
        uninstall_text = uninstall.read_text(encoding="utf-8")
        for token in ("Locale.preferredLanguages", "setActivationPolicy(.accessory)", "messageText", "configureNoAsDefaultButton", "com.strengw.codexbridge.launcher", "com.strengw.codexbridge.watcher"):
            self.assertIn(token, source)
        for token in ("launchctl", "codex_bridge_manager.sh", "com.strengw.codexbridge.launcher", "com.strengw.codexbridge.watcher", "Application Support/CodexProviderBridge"):
            self.assertIn(token, uninstall_text)
        self.assertNotIn("/Users/", source)
        self.assertNotIn("/Users/", uninstall_text)

    def test_manager_supports_repo_and_installed_sibling_runtime(self):
        text = (ROOT / "scripts" / "unix" / "codex_bridge_manager.sh").read_text(encoding="utf-8-sig")
        self.assertIn('CPB_PROJECT_ROOT=', text)
        self.assertIn('$CPB_SCRIPT_DIR/codex_provider_bridge.py', text)
        self.assertIn('$CPB_SCRIPT_DIR/python3', text)
        self.assertIn('$CPB_PROJECT_ROOT/src/bridge/codex_provider_bridge.py', text)
        self.assertIn('CPB_VERSION=', text)
        self.assertIn('restart) stop_bridge', text)
        self.assertIn('restart-codex)', text)
        self.assertNotIn('restart-cc-switch)', text)
        self.assertIn('Library/Application Support/CodexProviderBridge', text)

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

    def test_macos_workflow_builds_and_verifies_architecture_matched_app_bundle(self):
        text = (ROOT / ".github" / "workflows" / "build-macos-release.yml").read_text(encoding="utf-8")
        for token in ("swiftc", "src/launcher-macos/CodexBridgeLauncher.swift", "Info.plist.in", "CodexBridge.app", "CFBundleShortVersionString", "LSUIElement", "file -b", "executable"):
            self.assertIn(token, text)
        self.assertIn("arm64", text)
        self.assertIn("x86_64", text)

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
        self.assertIn('test -x "$verify/CodexBridge/CodexBridge.app/Contents/MacOS/CodexBridge"', text)
        self.assertIn('test -f "$verify/CodexBridge/CodexBridge.app/Contents/Info.plist"', text)

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
        self.assertIn('find "$stage/CodexBridge.app"', text)
        self.assertIn('codesign --verify --deep', text)

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

    def test_macos_watcher_only_triggers_full_app_on_ccswitch_edge(self):
        text = (ROOT / "scripts" / "unix" / "codex_bridge_watcher.sh").read_text(encoding="utf-8-sig")
        self.assertIn('launch_full_launcher', text)
        self.assertIn('previous_cc_switch_running', text)
        self.assertIn('launch_attempted_for_run', text)
        self.assertIn('CC Switch start edge', text)
        self.assertNotIn('ensure_bridge_started', text)
        self.assertNotIn('restart_cc_switch', text)
        self.assertNotIn('restart_codex', text)
        manager = (ROOT / "scripts" / "unix" / "codex_bridge_manager.sh").read_text(encoding="utf-8-sig")
        self.assertIn('restart_codex()', manager)

    def test_macos_bootstrap_installs_launcher_without_replacing_watcher(self):
        start = (ROOT / "Start CodexBridge.command").read_text(encoding="utf-8-sig")
        self.assertIn("CodexBridge.app", start)
        self.assertIn("com.strengw.codexbridge.watcher.plist", start)
        self.assertIn("legacy full-app login agent", start)
        self.assertIn("open", start)
        self.assertIn("codex_bridge_uninstall.sh", start)


if __name__ == "__main__":
    unittest.main()
