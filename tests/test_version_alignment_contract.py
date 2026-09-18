from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_public_version_is_semver_and_matches_windows_display_metadata():
    version = _version()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version)

    launcher = (ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs").read_text(encoding="utf-8-sig")
    setup = (ROOT / "src" / "setup" / "CodexBridgeSetup.cs").read_text(encoding="utf-8-sig")
    assert f'private const string ProductVersion = "{version}";' in launcher
    assert f'private const string ProductVersion = "{version}";' in setup


def test_internal_component_revisions_are_not_used_as_public_release_source():
    versioning = (ROOT / "docs" / "VERSIONING.md").read_text(encoding="utf-8")
    assert "Internal component revisions" in versioning
    assert "not" in versioning.lower()
    assert "public SemVer" in versioning


def test_release_workflows_bind_tag_to_version_file():
    for path in (
        ROOT / ".github" / "workflows" / "build-windows-release.yml",
        ROOT / ".github" / "workflows" / "build-macos-release.yml",
    ):
        text = path.read_text(encoding="utf-8")
        assert "VERSION" in text
        assert "does not match VERSION" in text


def test_release_docs_are_present_and_linked():
    for path in (
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "VERSIONING.md",
        ROOT / "docs" / "COMPATIBILITY.md",
        ROOT / "docs" / "PROJECT_OVERVIEW.zh-CN.md",
    ):
        assert path.is_file()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/COMPATIBILITY.md" in readme
    assert "docs/PROJECT_OVERVIEW.zh-CN.md" in readme
    assert "docs/VERSIONING.md" in readme
    assert "CHANGELOG.md" in readme
