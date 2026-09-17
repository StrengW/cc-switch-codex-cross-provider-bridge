import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
START_WIN = ROOT / "Start CodexBridge.cmd"
START_MAC = ROOT / "Start CodexBridge.command"
INSTALL_WIN = ROOT / "Install CodexBridge.cmd"
INSTALL_MAC = ROOT / "Install CodexBridge.command"


def test_repo_uses_single_start_entrypoint_instead_of_duplicate_install_wrappers():
    assert START_WIN.is_file()
    assert START_MAC.is_file()
    assert not INSTALL_WIN.exists()
    assert not INSTALL_MAC.exists()


def test_readmes_expose_start_entrypoints_for_source_zip_users():
    zh = README_ZH.read_text(encoding="utf-8")
    en = README_EN.read_text(encoding="utf-8")
    assert "Start CodexBridge.cmd" in zh
    assert "Start CodexBridge.command" in zh
    assert "Start CodexBridge.cmd" in en
    assert "Start CodexBridge.command" in en
    assert "Install CodexBridge.cmd" not in zh
    assert "Install CodexBridge.command" not in zh
    assert "Install CodexBridge.cmd" not in en
    assert "Install CodexBridge.command" not in en


@pytest.mark.skipif(os.name == "nt", reason="Windows checkout does not expose POSIX executable permission bits; macOS CI validates this contract.")
def test_macos_start_entrypoint_is_executable_in_repository_package():
    assert START_MAC.stat().st_mode & 0o111
