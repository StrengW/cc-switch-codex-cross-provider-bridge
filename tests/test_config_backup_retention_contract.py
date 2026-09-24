"""Retention limit for the config.toml backups the managers write.

Every time a manager rewrites ``~/.codex/config.toml`` it leaves a timestamped
backup beside it, and until now nothing removed those backups except a full
uninstall. Eight days of ordinary use put 36 of them in one user's ``.codex``
directory, in three families (``bridge-backup``, ``bridge-detach-backup``,
``bridge-direct-official-backup``). The volume is trivial. The problem is that
we kept adding files to a directory that is not ours and never took any back.

Each family is pruned separately rather than by a shared total, because they
back different recovery paths: a plain rewrite, a detach, and a switch to the
direct Official route. Capping the total would let the most frequent family
crowd out the last copy of a rarer one.

These tests lock the properties that make pruning safe, not the shape of the
code. Pruning deletes files in a user directory we do not own, so the match has
to be anchored to the config file name and to the exact timestamp format, both
platforms have to keep the same number, and a failed prune must never break the
config rewrite that triggered it.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "scripts" / "windows" / "codex_bridge_manager.ps1"
MACOS_MANAGER = ROOT / "scripts" / "unix" / "codex_bridge_manager.sh"

# Kept per family. Small enough that ordinary use stops accumulating, large
# enough that a user can still walk back several provider switches.
KEPT_BACKUPS = 3

# yyyyMMdd-HHmmss-fff - the stamp both managers already write.
STAMP_PATTERN = r"\d{8}-\d{6}-\d{3}"


def _powershell_function(text: str, name: str) -> str:
    start = text.index(f"function {name}")
    rest = text[start:]
    match = re.search(r"\nfunction ", rest[1:])
    return rest[: match.start() + 1] if match else rest


def _python_function(text: str, name: str) -> str:
    start = text.index(f"def {name}")
    rest = text[start:]
    match = re.search(r"\ndef ", rest[1:])
    return rest[: match.start() + 1] if match else rest


def test_windows_manager_prunes_after_creating_a_backup():
    text = MANAGER.read_text(encoding="utf-8-sig")
    assert "function Remove-StaleBridgeBackups" in text
    # Defined is not the same as called: the prune has to run on the ordinary
    # rewrite path, which is the one that accumulates.
    assert "Remove-StaleBridgeBackups -ConfigPath $CodexConfig" in text


def test_windows_prune_matches_only_bridge_stamped_backups():
    body = _powershell_function(
        MANAGER.read_text(encoding="utf-8-sig"), "Remove-StaleBridgeBackups"
    )
    # Anchored to the Bridge's own infix and to the exact stamp, so nothing else
    # in the directory can be selected. A bare "*backup*" glob would match
    # whatever the user or another tool happened to leave there.
    assert ".bridge-" in body
    assert STAMP_PATTERN in body


def test_windows_prune_keeps_the_newest_of_each_family():
    body = _powershell_function(
        MANAGER.read_text(encoding="utf-8-sig"), "Remove-StaleBridgeBackups"
    )
    assert f"[int]$Keep = {KEPT_BACKUPS}" in body
    # Newest must survive: skipping from the wrong end would delete the backup
    # the user is most likely to need and keep the oldest ones.
    assert "Select-Object -Skip $Keep" in body


def test_retention_orders_by_the_stamp_in_the_name_not_by_mtime():
    # Neither backup carries its own creation time. The unix manager copies with
    # shutil.copy2, and Windows hands the original to [IO.File]::Replace as the
    # backup destination; both preserve the source mtime, so every backup's
    # LastWriteTime is the config's rather than the moment it was taken. On a
    # real machine a backup stamped 221656 in its own name had a LastWriteTime
    # of 22:16:43 - thirteen seconds earlier. Sorting by mtime would keep an
    # arbitrary subset and could drop the newest backup of all.
    windows = _powershell_function(
        MANAGER.read_text(encoding="utf-8-sig"), "Remove-StaleBridgeBackups"
    )
    macos = _python_function(
        MACOS_MANAGER.read_text(encoding="utf-8"), "prune_stale_backups"
    )
    assert "LastWriteTime" not in windows
    assert "st_mtime" not in macos
    # The stamp is fixed width and zero filled, so name order is time order.
    assert "Sort-Object Name -Descending" in windows
    assert "key=lambda item: item.name" in macos
    assert "reverse=True" in macos


def test_windows_prune_cannot_select_the_live_config():
    body = _powershell_function(
        MANAGER.read_text(encoding="utf-8-sig"), "Remove-StaleBridgeBackups"
    )
    # The live config is the one file in that directory we must never remove.
    assert "-Filter" in body or "-include" in body.lower()
    assert "$leaf" in body
    assert "config.toml" not in body.replace("$leaf", "")


def test_windows_prune_failure_does_not_break_the_rewrite():
    body = _powershell_function(
        MANAGER.read_text(encoding="utf-8-sig"), "Remove-StaleBridgeBackups"
    )
    # Retention is housekeeping. A locked or vanished file must not fail the
    # config update the user actually asked for.
    assert "try" in body
    assert "catch" in body
    assert "-ErrorAction" in body or "SilentlyContinue" in body


def test_macos_manager_prunes_with_the_same_limit():
    text = MACOS_MANAGER.read_text(encoding="utf-8")
    assert "def prune_stale_backups" in text
    # Same rule as above: it has to be called on the rewrite path.
    assert "prune_stale_backups(path)" in text
    body = _python_function(text, "prune_stale_backups")
    assert f"keep={KEPT_BACKUPS}" in body or f"keep: int = {KEPT_BACKUPS}" in body


def test_macos_prune_matches_only_bridge_stamped_backups():
    body = _python_function(
        MACOS_MANAGER.read_text(encoding="utf-8"), "prune_stale_backups"
    )
    assert ".bridge-" in body
    assert STAMP_PATTERN in body
    # Anchored, not a substring search: a user file that merely contains
    # "backup" must not be eligible.
    assert "re.escape" in body
    assert "fullmatch" in body


def test_macos_prune_groups_by_family_and_keeps_the_newest():
    body = _python_function(
        MACOS_MANAGER.read_text(encoding="utf-8"), "prune_stale_backups"
    )
    # Per-family grouping is what stops the frequent family from crowding out
    # the last copy of a rarer one.
    assert "family" in body
    assert "[keep:]" in body


def test_macos_prune_failure_does_not_break_the_rewrite():
    body = _python_function(
        MACOS_MANAGER.read_text(encoding="utf-8"), "prune_stale_backups"
    )
    assert "except OSError" in body


def test_both_embedded_interpreters_get_an_identical_prune():
    text = MACOS_MANAGER.read_text(encoding="utf-8")
    # Each heredoc is its own Python process and cannot see the other's
    # definitions, so the function has to appear twice - once on the ordinary
    # rewrite path and once on the direct-Official path. _python_function only
    # ever reads the first copy, so the second is checked here by requiring the
    # load-bearing lines to appear exactly twice. Removing the duplication
    # properly means lifting this logic out of the shell, which is tracked
    # separately.
    assert text.count("def prune_stale_backups(path, keep=3):") == 2
    for needle in (
        "match = pattern.fullmatch(entry.name)",
        "family.sort(key=lambda item: item.name, reverse=True)",
        "for stale in family[keep:]:",
        "prune_stale_backups(path)",
    ):
        assert text.count(needle) == 2, needle


def test_every_unix_python_block_still_parses():
    # A syntax error inside a heredoc only surfaces when that path runs on
    # macOS, and there is no Mac in CI for the unix manager. Compile each block
    # here instead, so a bad edit fails on every platform.
    text = MACOS_MANAGER.read_text(encoding="utf-8")
    lines = text.split("\n")
    blocks = []
    start = None
    for index, line in enumerate(lines):
        if start is None:
            if re.search(r"<<'PY'\s*$", line):
                start = index
        elif line == "PY":
            blocks.append((start + 2, "\n".join(lines[start + 1 : index])))
            start = None
    assert start is None, f"unterminated heredoc starting at line {start + 1}"
    assert len(blocks) >= 8, f"expected the usual heredocs, found {len(blocks)}"
    for first_line, source in blocks:
        try:
            compile(source, f"<manager.sh:{first_line}>", "exec")
        except SyntaxError as exc:  # pragma: no cover - failure path
            raise AssertionError(
                f"embedded Python at line {first_line} does not parse: {exc}"
            ) from exc


def test_both_platforms_agree_on_how_many_backups_survive():
    windows = MANAGER.read_text(encoding="utf-8-sig")
    macos = MACOS_MANAGER.read_text(encoding="utf-8")
    # A split limit would make the two platforms silently disagree about what
    # the user's .codex directory looks like after the same amount of use.
    assert f"[int]$Keep = {KEPT_BACKUPS}" in windows
    assert f"keep={KEPT_BACKUPS}" in macos or f"keep: int = {KEPT_BACKUPS}" in macos
