"""Every doc the READMEs link to has to ship inside both Release packages.

A Release ZIP is offline documentation: its README is the only entry point a
user who did not clone the repository has. Which files land in that ZIP is
decided by two hard-coded lists that nothing else cross-checks - a PowerShell
array in the Windows packaging script and a ``cp`` line in the macOS workflow.
A doc written and linked but missing from either list becomes a dead link for
every user who downloaded a package, and the build still succeeds.

These tests parse the two lists rather than grep for a path, so a doc mentioned
only in a comment does not count as shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_BUILD = ROOT / "scripts" / "build" / "BuildWindowsReleasePackage.ps1"
MACOS_WORKFLOW = ROOT / ".github" / "workflows" / "build-macos-release.yml"
DOCS = ROOT / "docs"
READMES = (ROOT / "README.md", ROOT / "README.en.md")


def _repo_docs() -> list[str]:
    # Top level only. docs/superpowers/ holds planning notes that are neither
    # tracked nor shipped, and a recursive glob would drag them in.
    return sorted(path.name for path in DOCS.glob("*.md"))


def _windows_package_files() -> set[str]:
    text = WINDOWS_BUILD.read_text(encoding="utf-8-sig")
    start = text.index("$files = @(")
    block = text[start:]
    block = block[: block.index(")")]
    return set(re.findall(r"'([^']+)'", block))


def _macos_package_docs() -> set[str]:
    text = MACOS_WORKFLOW.read_text(encoding="utf-8")
    staging = [line for line in text.splitlines() if line.strip().startswith("cp docs/")]
    assert staging, "the macOS workflow no longer stages docs/ with a cp line"
    staged: set[str] = set()
    for line in staging:
        staged.update(
            token for token in line.split() if token.startswith("docs/") and token.endswith(".md")
        )
    return staged


def _readme_doc_links(readme: Path) -> set[str]:
    text = readme.read_text(encoding="utf-8")
    return {
        target.split("#", 1)[0]
        for target in re.findall(r"\]\(((?:\.\./)*docs/[^)\s]+)\)", text)
    }


def test_windows_release_package_ships_every_doc():
    packaged = _windows_package_files()
    missing = [name for name in _repo_docs() if f"docs\\{name}" not in packaged]
    assert not missing, f"Windows Release ZIP would omit docs the README links to: {missing}"


def test_macos_release_package_ships_every_doc():
    staged = _macos_package_docs()
    missing = [name for name in _repo_docs() if f"docs/{name}" not in staged]
    assert not missing, f"macOS Release ZIP would omit docs the README links to: {missing}"


def test_both_release_packages_ship_the_same_doc_set():
    # The two lists are maintained by hand on different platforms. Drift means
    # one audience silently loses a document the other one has.
    windows = {Path(entry).name for entry in _windows_package_files() if entry.startswith("docs\\")}
    macos = {Path(entry).name for entry in _macos_package_docs()}
    assert windows == macos, f"the release packages disagree on docs: {windows ^ macos}"


def test_macos_package_verification_covers_the_docs_it_ships():
    # Staging alone is not enough: the workflow reopens the built archive and
    # asserts on its contents, and that check is what would catch a cp that
    # silently stopped matching.
    text = MACOS_WORKFLOW.read_text(encoding="utf-8")
    verified = set(re.findall(r'test -f "\$verify/CodexBridge/docs/([^"]+)"', text))
    assert verified, "the macOS workflow stopped verifying staged docs"
    staged = {Path(entry).name for entry in _macos_package_docs()}
    unverified = sorted(staged - verified)
    assert not unverified, f"macOS stages docs it never verifies in the archive: {unverified}"


def test_every_docs_link_in_the_readmes_resolves():
    for readme in READMES:
        for target in _readme_doc_links(readme):
            assert (ROOT / target).is_file(), f"{readme.name} links to {target}, which does not exist"


def test_every_shipped_doc_is_reachable_from_a_readme():
    # The other direction: a doc nobody links to is invisible to the users who
    # most need it, and is the usual shape of documentation left behind by a
    # refactor that moved content out of the README.
    linked: set[str] = set()
    for readme in READMES:
        linked.update(Path(target).name for target in _readme_doc_links(readme))
    orphans = [name for name in _repo_docs() if name not in linked]
    assert not orphans, f"docs shipped in the release packages but linked from no README: {orphans}"
