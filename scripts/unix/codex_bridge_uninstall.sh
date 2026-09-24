#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${1:-}" != "--confirmed" ]]; then
  printf 'This removes CodexBridge runtime, app, logs, and LaunchAgents. Codex chat history is kept. Continue? [y/N] '
  read -r answer
  [[ "$answer" =~ ^[Yy]$ ]] || exit 0
fi

STATE_ROOT="${CPB_STATE_ROOT:-$HOME/Library/Application Support/CodexProviderBridge}"
LEGACY_STATE_ROOT="$HOME/.local/state/CodexProviderBridge"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
LAUNCHER_PLIST="$HOME/Library/LaunchAgents/com.strengw.codexbridge.launcher.plist"
WATCHER_PLIST="$HOME/Library/LaunchAgents/com.strengw.codexbridge.watcher.plist"
MANAGER="$STATE_ROOT/app/codex_bridge_manager.sh"
CODEX_CONFIG="$CODEX_HOME/config.toml"

# Bridge-owned fingerprints in the Codex config: the loopback route on a port
# inside the manager's managed range (15722..15921), which deliberately excludes
# CC Switch's own upstream port 15721, plus the bundled catalog file name.
BRIDGE_MARKER_RE='(127\.0\.0\.1|localhost):15(72[2-9]|7[3-9][0-9]|8[0-9][0-9]|9[01][0-9]|92[01])/v1|cpb-bundled-model-catalog'
# Config lines only CodexBridge ever writes. Dropping them is safe on its own, so
# the legacy PROXY_MANAGED sentinel is matched here rather than in the check above.
BRIDGE_OWNED_LINE_RE='^[[:space:]]*model_catalog_json[[:space:]]*=.*cpb-|^[[:space:]]*experimental_bearer_token[[:space:]]*=[[:space:]]*"PROXY_MANAGED"'

config_points_at_bridge() {
  # A third-party or already-official config must be left untouched:
  # prepare-direct-official rewrites model_provider unconditionally.
  [[ -f "$CODEX_CONFIG" ]] || return 1
  grep -qE "$BRIDGE_MARKER_RE" "$CODEX_CONFIG"
}

restore_earliest_clean_backup() {
  # macOS keeps no dedicated pre-install snapshot, so the earliest backup
  # without Bridge markers is the closest thing to the pre-install config
  # (the same heuristic the Windows uninstaller uses for migrated installs).
  local candidate
  for candidate in "$CODEX_HOME"/config.toml.bridge-backup-*; do
    [[ -f "$candidate" ]] || continue
    if ! grep -qE "$BRIDGE_MARKER_RE" "$candidate" 2>/dev/null; then
      cp -f -- "$candidate" "$CODEX_CONFIG" && return 0
    fi
  done
  return 1
}

strip_bridge_owned_config_lines() {
  # Drop only CodexBridge-owned references that would point at files this
  # uninstaller deletes (mirrors the Windows uninstaller's last-resort pass).
  [[ -f "$CODEX_CONFIG" ]] || return 0
  # Leave a config with nothing Bridge-owned in it byte-identical: rewriting it
  # for nothing would still churn a file this uninstaller promised not to touch.
  grep -qE "$BRIDGE_OWNED_LINE_RE" "$CODEX_CONFIG" || return 0
  local tmp
  tmp="$(mktemp "$CODEX_HOME/.config.toml.bridge-tmp-XXXXXX")" || return 0
  if grep -vE "$BRIDGE_OWNED_LINE_RE" "$CODEX_CONFIG" >"$tmp" 2>/dev/null; then
    mv -f -- "$tmp" "$CODEX_CONFIG"
  else
    rm -f -- "$tmp"
  fi
}

/bin/launchctl bootout "gui/$UID" "$LAUNCHER_PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootout "gui/$UID" "$WATCHER_PLIST" >/dev/null 2>&1 || true

# Settle the Codex config while the Bridge runtime still exists:
# prepare-direct-official arms the manager's detach latch, so it must run
# before the Bridge stops; the backup restore runs after the stop so the
# Bridge's config guard cannot race it.
config_needs_handoff=0
config_handed_off=0
config_restored=0
if config_points_at_bridge; then
  config_needs_handoff=1
  if [[ -x "$MANAGER" ]] && /bin/bash "$MANAGER" prepare-direct-official >/dev/null 2>&1; then
    config_handed_off=1
  fi
fi

if [[ -x "$MANAGER" ]]; then
  /bin/bash "$MANAGER" stop >/dev/null 2>&1 || true
fi
if [[ -f "$STATE_ROOT/macos-watcher.pid" ]]; then
  pid="$(cat "$STATE_ROOT/macos-watcher.pid" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]]; then kill "$pid" 2>/dev/null || true; fi
fi

rm -f -- "$LAUNCHER_PLIST" "$WATCHER_PLIST"

# The Bridge is stopped now, so a restore cannot be raced by its config guard.
if [[ "$config_needs_handoff" -eq 1 ]] && restore_earliest_clean_backup; then
  config_restored=1
fi
strip_bridge_owned_config_lines

# Every artifact family the Bridge writes next to config.toml: both timestamped
# backup families, hidden mkstemp leftovers from an interrupted write, and the
# cpb-* payloads (catalog, sidecar, detach latch).
for residue in \
  "$CODEX_HOME"/config.toml.bridge-backup-* \
  "$CODEX_HOME"/config.toml.bridge-direct-official-backup-* \
  "$CODEX_HOME"/.*.bridge-tmp-* \
  "$CODEX_HOME"/.*.bridge-direct-official-tmp-* \
  "$CODEX_HOME"/cpb-*; do
  if [[ -e "$residue" ]]; then rm -f -- "$residue"; fi
done

rm -rf -- "$STATE_ROOT"
if [[ "$LEGACY_STATE_ROOT" != "$STATE_ROOT" ]]; then
  rm -rf -- "$LEGACY_STATE_ROOT"
fi

if [[ "$config_restored" -eq 1 ]]; then
  printf 'CodexBridge was uninstalled. Codex config was restored to its pre-install state. Chat history was kept.\n'
elif [[ "$config_handed_off" -eq 1 ]]; then
  printf 'CodexBridge was uninstalled. Codex was switched to the direct Official route. Chat history was kept.\n'
elif [[ "$config_needs_handoff" -eq 1 ]]; then
  printf 'CodexBridge was uninstalled, but the Codex config could not be switched back automatically.\n' >&2
  printf 'If Codex cannot connect, remove the local Bridge settings from %s manually. Chat history was kept.\n' "$CODEX_CONFIG" >&2
else
  printf 'CodexBridge was uninstalled. Codex chat history was kept.\n'
fi
