#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
STATE_ROOT="$HOME/Library/Application Support/CodexProviderBridge"
APP_ROOT="$STATE_ROOT/app"
RUNTIME_ROOT="$STATE_ROOT/runtime"
UV_ROOT="$RUNTIME_ROOT/uv"
PY_ROOT="$RUNTIME_ROOT/python"
LOG="$STATE_ROOT/start.log"
PLIST="$HOME/Library/LaunchAgents/com.strengw.codexbridge.watcher.plist"

mkdir -p "$STATE_ROOT" "$APP_ROOT" "$RUNTIME_ROOT" "$(dirname -- "$PLIST")"
exec > >(tee -a "$LOG") 2>&1

echo "[CodexBridge] Starting portable macOS setup..."
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This launcher is for macOS. On Windows double-click Start CodexBridge.cmd."
  read -r -p "Press Enter to close..." _ || true
  exit 2
fi

copy_runtime_files() {
  cp -f "$ROOT/src/bridge/codex_provider_bridge.py" "$APP_ROOT/codex_provider_bridge.py"
  cp -f "$ROOT/scripts/unix/codex_bridge_manager.sh" "$APP_ROOT/codex_bridge_manager.sh"
  cp -f "$ROOT/scripts/unix/codex_bridge_watcher.sh" "$APP_ROOT/codex_bridge_watcher.sh"
  chmod +x "$APP_ROOT/codex_bridge_manager.sh" "$APP_ROOT/codex_bridge_watcher.sh"
}

python_ok() {
  local py="$1"
  [[ -x "$py" ]] || return 1
  "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)' >/dev/null 2>&1
}

find_system_python() {
  local p
  for p in "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    [[ -n "$p" ]] || continue
    if python_ok "$p"; then printf '%s\n' "$p"; return 0; fi
  done
  return 1
}

ensure_python() {
  local existing uv py
  if [[ -L "$APP_ROOT/python3" || -x "$APP_ROOT/python3" ]] && python_ok "$APP_ROOT/python3"; then
    printf '%s\n' "$APP_ROOT/python3"
    return 0
  fi

  # CI/self-contained packages may already include a portable runtime.
  if python_ok "$ROOT/runtime/python/bin/python3"; then
    ln -sfn "$ROOT/runtime/python/bin/python3" "$APP_ROOT/python3"
    printf '%s\n' "$APP_ROOT/python3"
    return 0
  fi

  existing="$(find_system_python || true)"
  if [[ -n "$existing" ]]; then
    ln -sfn "$existing" "$APP_ROOT/python3"
    printf '%s\n' "$APP_ROOT/python3"
    return 0
  fi

  uv="$UV_ROOT/uv"
  if [[ ! -x "$uv" ]]; then
    echo "[CodexBridge] Python is not installed. Downloading a private runtime helper (first run only)..." >&2
    command -v curl >/dev/null 2>&1 || { echo "curl is required for first-run setup." >&2; return 1; }
    mkdir -p "$UV_ROOT"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$UV_ROOT" sh >&2
  fi
  [[ -x "$uv" ]] || { echo "Could not install the runtime helper." >&2; return 1; }

  echo "[CodexBridge] Downloading private Python 3.12 runtime (first run only)..." >&2
  mkdir -p "$PY_ROOT"
  UV_PYTHON_INSTALL_DIR="$PY_ROOT" "$uv" python install 3.12 --managed-python >/dev/null
  py="$(UV_PYTHON_INSTALL_DIR="$PY_ROOT" "$uv" python find 3.12 --managed-python 2>/dev/null | head -n 1 || true)"
  [[ -n "$py" ]] && python_ok "$py" || { echo "Could not prepare Python 3.12 automatically." >&2; return 1; }
  ln -sfn "$py" "$APP_ROOT/python3"
  printf '%s\n' "$APP_ROOT/python3"
}

install_launch_agent() {
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.strengw.codexbridge.watcher</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$APP_ROOT/codex_bridge_watcher.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$STATE_ROOT/launchagent.out.log</string>
  <key>StandardErrorPath</key><string>$STATE_ROOT/launchagent.err.log</string>
</dict>
</plist>
EOF

  /bin/launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
  if ! /bin/launchctl bootstrap "gui/$UID" "$PLIST" >/dev/null 2>&1; then
    /bin/launchctl load -w "$PLIST" >/dev/null 2>&1 || true
  fi
}

copy_runtime_files
PYTHON_PATH="$(ensure_python)"
python_ok "$PYTHON_PATH" || { echo "[CodexBridge] Python runtime setup failed. See: $LOG"; read -r -p "Press Enter to close..." _ || true; exit 1; }
install_launch_agent

# Start immediately even if launchctl has not scheduled the agent yet.
if [[ -f "$STATE_ROOT/macos-watcher.pid" ]] && kill -0 "$(cat "$STATE_ROOT/macos-watcher.pid" 2>/dev/null || echo 0)" 2>/dev/null; then
  :
else
  nohup /bin/bash "$APP_ROOT/codex_bridge_watcher.sh" >>"$STATE_ROOT/macos-watcher.log" 2>&1 </dev/null &
fi

# Convenience only: first run tries to open CC Switch if it is installed.
if ! pgrep -if 'CC[ _-]*Switch|CCSwitch' >/dev/null 2>&1; then
  /usr/bin/open -a "CC Switch" >/dev/null 2>&1 || /usr/bin/open -a "CCSwitch" >/dev/null 2>&1 || true
fi

/usr/bin/osascript -e 'display notification "Codex Bridge is ready and will stay available even when CC Switch is closed." with title "Codex Bridge"' >/dev/null 2>&1 || true
echo "[CodexBridge] Ready."
echo "Runtime: $APP_ROOT"
echo "Logs: $STATE_ROOT"
echo "You can close this Terminal window."
sleep 2
