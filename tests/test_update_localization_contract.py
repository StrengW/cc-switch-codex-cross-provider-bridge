from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_launcher_has_non_blocking_release_update_check_and_localized_tray_surface():
    launcher = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    checker = (ROOT / "src" / "launcher" / "ReleaseUpdateChecker.cs").read_text(encoding="utf-8-sig")
    localization = (ROOT / "src" / "launcher" / "LauncherUiText.cs").read_text(encoding="utf-8-sig")

    assert "CheckForUpdates" in launcher
    assert "Check for Updates" in launcher
    assert "releases/latest" in checker
    assert "ThreadPool.QueueUserWorkItem" in checker
    assert "HttpWebRequest" in checker
    assert "CurrentUICulture.Name" in localization
    assert "InstalledUICulture.Name" in localization
    assert "Restart Codex" in localization
    assert 'new ToolStripMenuItem("Restart Codex")' not in launcher


def test_windows_update_prompt_can_open_release_page_without_auto_replacing_runtime():
    launcher = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    checker = (ROOT / "src" / "launcher" / "ReleaseUpdateChecker.cs").read_text(encoding="utf-8-sig")

    assert "OpenReleasePage" in launcher
    assert "UseShellExecute = true" in launcher
    assert "https://github.com/StrengW/cc-switch-codex-cross-provider-bridge/releases" in checker
    assert "File.Copy" not in checker
    assert "InstallAndRelaunchIfNeeded" not in checker


def test_windows_update_checker_enables_tls12_for_github():
    checker = (ROOT / "src" / "launcher" / "ReleaseUpdateChecker.cs").read_text(encoding="utf-8-sig")

    assert "EnsureModernTls" in checker
    assert "ServicePointManager.SecurityProtocol" in checker
    assert "SecurityProtocolType.Tls12" in checker
    assert checker.index("EnsureModernTls();") < checker.index("WebRequest.Create(ApiUrl)")


def test_windows_update_checker_falls_back_to_releases_latest_redirect():
    checker = (ROOT / "src" / "launcher" / "ReleaseUpdateChecker.cs").read_text(encoding="utf-8-sig")

    assert "LatestTagFromRedirect" in checker
    assert 'ReleaseUrl + "/latest"' in checker
    assert "AllowAutoRedirect = false" in checker
    assert "TagFromLocation" in checker
    assert checker.index("LatestTagFromRedirect(currentVersion)") < checker.index("return Failed(apiError)")


def test_update_check_outcomes_are_written_to_launcher_log():
    launcher = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    localization = (ROOT / "src" / "launcher" / "LauncherUiText.cs").read_text(encoding="utf-8-sig")

    assert 'Log("Update check failed: "' in launcher
    assert 'Log("Update check: version "' in launcher
    assert "ShowUpdateFailure" in launcher
    assert "proxy or firewall is usually blocking api.github.com" in launcher
    assert "代理或防火墙拦截了 api.github.com" in localization


def test_windows_source_release_package_contains_launcher_support_files():
    package = (ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1").read_text(encoding="utf-8-sig")

    assert "src\\launcher\\LauncherUiText.cs" in package
    assert "src\\launcher\\ReleaseUpdateChecker.cs" in package


def test_macos_launcher_checks_latest_release_and_uses_system_language_fallback():
    source = (ROOT / "src" / "launcher-macos" / "CodexBridgeLauncher.swift").read_text(encoding="utf-8")

    assert "releases/latest" in source
    assert "URLSession" in source
    assert "UserDefaults" in source
    assert "Locale.current.languageCode" in source
    assert "Check for Updates" in source
    assert "Open Latest Release" in source
