from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readmes_link_windows_macos_ci_and_releases():
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "build-windows-release.yml" in text
        assert "build-macos-release.yml" in text
        assert "../../actions/workflows/build-windows-release.yml" in text
        assert "../../actions/workflows/build-macos-release.yml" in text
        assert "../../releases" in text
        assert "https://github.com/StrengW/cc-switch-codex-cross-provider-bridge" not in text
        assert "CodexBridge-macOS-AppleSilicon.zip" in text
        assert "CodexBridge-macOS-Intel.zip" in text
