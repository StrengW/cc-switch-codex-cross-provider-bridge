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

/bin/launchctl bootout "gui/$UID" "$LAUNCHER_PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootout "gui/$UID" "$WATCHER_PLIST" >/dev/null 2>&1 || true
if [[ -x "$MANAGER" ]]; then
  /bin/bash "$MANAGER" stop >/dev/null 2>&1 || true
fi
if [[ -f "$STATE_ROOT/macos-watcher.pid" ]]; then
  pid="$(cat "$STATE_ROOT/macos-watcher.pid" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]]; then kill "$pid" 2>/dev/null || true; fi
fi

rm -f -- "$LAUNCHER_PLIST" "$WATCHER_PLIST"
for backup in "$CODEX_HOME"/config.toml.bridge-backup-* "$CODEX_HOME"/cpb-*; do
  [[ -e "$backup" ]] && rm -f -- "$backup"
done
rm -rf -- "$STATE_ROOT"
if [[ "$LEGACY_STATE_ROOT" != "$STATE_ROOT" ]]; then
  rm -rf -- "$LEGACY_STATE_ROOT"
fi
printf 'CodexBridge was uninstalled. Codex chat history was kept.\n'
