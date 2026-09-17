from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "src" / "setup" / "CodexBridgeSetup.cs"

VALID_ESCAPE_STARTERS = set("'\"\\0abfnrtvuxU")


def _invalid_normal_string_escapes(text: str):
    bad = []
    i = 0
    while i < len(text):
        if text[i] == '"' and (i == 0 or text[i - 1] != '@'):
            i += 1
            while i < len(text):
                ch = text[i]
                if ch == '\\':
                    if i + 1 >= len(text):
                        break
                    nxt = text[i + 1]
                    if nxt not in VALID_ESCAPE_STARTERS:
                        bad.append((text.count("\n", 0, i) + 1, "\\" + nxt))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                if ch == '\n':
                    break
                i += 1
            continue
        i += 1
    return bad


def test_setup_has_no_invalid_normal_csharp_string_escapes():
    text = SETUP.read_text(encoding="utf-8-sig")
    assert _invalid_normal_string_escapes(text) == []


def test_named_kernel_objects_use_verbatim_strings():
    text = SETUP.read_text(encoding="utf-8-sig")
    assert 'WatcherStopEventName = @"Local\\CodexProviderBridgeCcSwitchWatcherStop";' in text
    assert 'SetupMutexName = @"Local\\CodexBridgeSetup";' in text
