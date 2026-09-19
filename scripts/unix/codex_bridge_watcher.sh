#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)"
MANAGER="${CPB_MANAGER:-$SCRIPT_DIR/codex_bridge_manager.sh}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
ROUTE_STATE="$CODEX_HOME/cpb-active-model-catalog.json.source.json"
STATE_ROOT="${CPB_WATCH_STATE_DIR:-$HOME/Library/Application Support/CodexProviderBridge}"
LOG="$STATE_ROOT/macos-watcher.log"
PID_FILE="$STATE_ROOT/macos-watcher.pid"
POLL_SECONDS="${CPB_WATCH_POLL_SECONDS:-0.8}"

mkdir -p "$STATE_ROOT"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

is_pid_alive() {
  [[ "${1:-}" =~ ^[0-9]+$ ]] && kill -0 "$1" 2>/dev/null
}

single_instance() {
  if [[ -f "$PID_FILE" ]]; then
    local old
    old="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old"; then
      log "Watcher already running pid=$old"
      exit 0
    fi
  fi
  echo $$ >"$PID_FILE"
  trap 'rm -f -- "$PID_FILE"' EXIT INT TERM
}

cc_switch_running() {
  pgrep -if '(^|/|[[:space:]])CC[ _-]*Switch([[:space:]]|$)|(^|/|[[:space:]])CCSwitch([[:space:]]|$)' >/dev/null 2>&1
}

json_string() {
  local key="$1" file="$2"
  [[ -f "$file" ]] || return 0
  # Sidecar values are simple strings written by our own bridge. This avoids jq/Python.
  sed -nE 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"([^"\\]*(\\.[^"\\]*)*)".*/\1/p' "$file" | head -n 1
}

route_key() {
  local kind model
  kind="$(json_string route_kind "$ROUTE_STATE")"
  model="$(json_string route_model "$ROUTE_STATE")"
  case "$kind" in
    official) printf 'official|%s\n' "$model" ;;
    third-party) printf 'third-party|%s\n' "$model" ;;
    *) printf 'unknown|%s\n' "$model" ;;
  esac
}

wait_port() {
  local port="$1" max="${2:-40}" i
  for ((i=0;i<max;i++)); do
    if /usr/bin/nc -z 127.0.0.1 "$port" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  return 1
}

find_cc_switch_app() {
  local app=""
  for candidate in "/Applications/CC Switch.app" "$HOME/Applications/CC Switch.app" "/Applications/CCSwitch.app" "$HOME/Applications/CCSwitch.app"; do
    [[ -d "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  if command -v mdfind >/dev/null 2>&1; then
    app="$(mdfind 'kMDItemContentType == "com.apple.application-bundle" && (kMDItemFSName == "CC Switch.app"c || kMDItemFSName == "CCSwitch.app"c)' 2>/dev/null | head -n 1 || true)"
    [[ -n "$app" ]] && printf '%s\n' "$app"
  fi
}

restart_cc_switch() {
  local app
  app="$(find_cc_switch_app || true)"
  if [[ -z "$app" ]]; then
    log "CC Switch app not found; leaving current process untouched."
    return 0
  fi
  log "Restarting CC Switch: $app"
  /usr/bin/osascript -e 'tell application "CC Switch" to quit' >/dev/null 2>&1 || true
  pkill -if 'CC[ _-]*Switch|CCSwitch' >/dev/null 2>&1 || true
  sleep 0.7
  /usr/bin/open "$app" >/dev/null 2>&1 || { log "Failed to relaunch CC Switch"; return 1; }
  if wait_port 15721 40; then log "CC Switch proxy :15721 ready"; else log "WARNING CC Switch :15721 not ready after restart"; fi
}

restart_codex() {
  log "Restarting Codex backend"
  # Match the backend itself rather than killing VS Code/Cursor, preserving editor windows.
  pkill -TERM -f '(^|/|[[:space:]])codex([[:space:]]|$)|OpenAI/Codex' >/dev/null 2>&1 || true
  sleep 0.8
  log "Codex backend terminated; VS Code/Cursor/Codex host will recreate it on next interaction."
}

ensure_bridge_started() {
  "$MANAGER" start --background >>"$LOG" 2>&1 || {
    log "ERROR bridge manager start failed"
    return 1
  }
  log "CC Switch detected; Bridge is running."
}

main() {
  [[ "$(uname -s)" == "Darwin" ]] || { echo 'This watcher is for macOS.' >&2; exit 2; }
  [[ -x "$MANAGER" ]] || chmod +x "$MANAGER" 2>/dev/null || true
  single_instance
  log "Lightweight CC Switch watcher starting from portable root: $PROJECT_ROOT"

  local activated=0
  local last="unknown|" current kind
  local last_proxy_recovery=0 now

  # The Bridge is the resident compatibility layer and must not depend on
  # CC Switch being open. This keeps Official conversations available after
  # login/restart even when CC Switch is closed.
  if ensure_bridge_started; then
    activated=1
    last="$(route_key)"
    log "Initial resident route: $last"
  fi

  while :; do
    if (( activated == 0 )); then
      if ensure_bridge_started; then
        activated=1
        last="$(route_key)"
        log "Resident Bridge recovered; route: $last"
      else
        sleep "$POLL_SECONDS"
        continue
      fi
    fi

    current="$(route_key)"
    if [[ "$current" != "$last" ]]; then
      log "Route changed: $last -> $current"
      kind="${current%%|*}"
      if [[ "$kind" == "third-party" ]]; then
        restart_cc_switch || true
        restart_codex || true
      elif [[ "$kind" == "official" ]]; then
        restart_codex || true
      else
        log "Route unknown; no process restart performed."
      fi
      last="$current"
    fi

    # If CC Switch is manually closed while a third-party route remains active,
    # restore only its local proxy. Do not restart Codex just because the proxy
    # disappeared; the provider/model did not change. Official routes do nothing.
    kind="${current%%|*}"
    if [[ "$kind" == "third-party" ]] && ! /usr/bin/nc -z 127.0.0.1 15721 >/dev/null 2>&1; then
      now="$(date +%s)"
      if (( now - last_proxy_recovery >= 3 )); then
        last_proxy_recovery="$now"
        log "Third-party route active but CC Switch proxy :15721 is unavailable; restoring proxy without restarting Codex."
        restart_cc_switch || true
      fi
    fi

    sleep "$POLL_SECONDS"
  done
}

case "${1:-}" in
  restart-codex)
    restart_codex
    exit 0
    ;;
  restart-cc-switch)
    restart_cc_switch
    exit $?
    ;;
esac

main "$@"
