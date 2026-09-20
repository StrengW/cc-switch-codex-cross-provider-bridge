#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)"
STATE_ROOT="${CPB_WATCH_STATE_DIR:-$HOME/Library/Application Support/CodexProviderBridge}"
LAUNCHER_APP="$STATE_ROOT/app/CodexBridge.app"
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

full_launcher_running() {
  pgrep -f "$LAUNCHER_APP/Contents/MacOS/CodexBridge" >/dev/null 2>&1
}

launch_full_launcher() {
  if full_launcher_running; then
    log "CC Switch start edge observed while CodexBridge menu bar app is already running."
    return 0
  fi
  [[ -x "$LAUNCHER_APP/Contents/MacOS/CodexBridge" ]] || {
    log "WARNING CodexBridge.app is not installed; CC Switch start edge was observed but no full Launcher was launched."
    return 1
  }
  /usr/bin/open "$LAUNCHER_APP" >/dev/null 2>&1 || {
    log "WARNING failed to launch CodexBridge.app after CC Switch start edge"
    return 1
  }
  log "CC Switch detected; launched CodexBridge menu bar app."
}

main() {
  [[ "$(uname -s)" == "Darwin" ]] || { echo 'This watcher is for macOS.' >&2; exit 2; }
  single_instance
  log "Lightweight CC Switch watcher starting from portable root: $PROJECT_ROOT"

  local previous_cc_switch_running=false
  local launch_attempted_for_run=false
  log "Lightweight watcher armed; it will launch CodexBridge only on a CC Switch start edge."

  while :; do
    local current_cc_switch_running=false
    if cc_switch_running; then current_cc_switch_running=true; fi
    if [[ "$current_cc_switch_running" == false ]]; then
      launch_attempted_for_run=false
    elif [[ "$previous_cc_switch_running" == false && "$launch_attempted_for_run" == false ]]; then
      launch_attempted_for_run=true
      launch_full_launcher || true
    fi
    previous_cc_switch_running="$current_cc_switch_running"

    sleep "$POLL_SECONDS"
  done
}

main "$@"
