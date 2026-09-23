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
LAUNCHER_APP="$APP_ROOT/CodexBridge.app"

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
  cp -f "$ROOT/scripts/unix/codex_bridge_uninstall.sh" "$APP_ROOT/codex_bridge_uninstall.sh"
  chmod +x "$APP_ROOT/codex_bridge_manager.sh" "$APP_ROOT/codex_bridge_watcher.sh" "$APP_ROOT/codex_bridge_uninstall.sh"
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
  # Publish the portable runtime to its stable home inside the state directory
  # first (idempotent). The extracted ZIP folder is disposable - deleting it
  # after setup is a normal thing to do - so nothing may keep depending on it.
  # ditto preserves the symlinks inside the Python distribution and merges
  # into an existing destination, so a re-run also migrates older installs.
  if [[ -x "$ROOT/runtime/python/bin/python3" ]] && ! python_ok "$PY_ROOT/bin/python3"; then
    echo "[CodexBridge] Installing the private Python runtime into $PY_ROOT ..." >&2
    mkdir -p "$RUNTIME_ROOT"
    rm -rf -- "$PY_ROOT"
    /usr/bin/ditto "$ROOT/runtime/python" "$PY_ROOT" || true
  fi
  if python_ok "$PY_ROOT/bin/python3"; then
    ln -sfn "$PY_ROOT/bin/python3" "$APP_ROOT/python3"
    printf '%s\n' "$APP_ROOT/python3"
    return 0
  fi

  # Older installs may already carry a working shim (for example to a system
  # Python or to a uv-managed interpreter); keep it when it verifies.
  if [[ -L "$APP_ROOT/python3" || -x "$APP_ROOT/python3" ]] && python_ok "$APP_ROOT/python3"; then
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

ensure_local_signature() {
  # Gatekeeper reports a bundle as "damaged" - a state with no user escape -
  # when its inner executable carries a signature but the outer bundle has none
  # (or was invalidated in transit). A bundle that already verifies (including
  # future Developer ID-signed builds) is left untouched; an unverifiable one
  # gets a local ad-hoc signature, so Gatekeeper shows its normal
  # unverified-developer flow instead. No Apple account is involved and no
  # Gatekeeper or system security setting is changed.
  if ! /usr/bin/codesign --verify --deep --strict "$LAUNCHER_APP" >/dev/null 2>&1; then
    /usr/bin/codesign --force --deep --sign - "$LAUNCHER_APP" >/dev/null 2>&1 || true
  fi
}

repair_gatekeeper_block() {
  # Explicitly consented repair: only reachable after the user clicks the repair
  # button in the failure dialog. It touches CodexBridge.app only - a local
  # re-sign when the bundle does not verify, plus removal of this app's
  # quarantine flag. System security settings and Gatekeeper are never touched.
  if ! /usr/bin/codesign --verify --deep --strict "$LAUNCHER_APP" >/dev/null 2>&1; then
    /usr/bin/codesign --force --deep --sign - "$LAUNCHER_APP" >/dev/null 2>&1 || true
  fi
  /usr/bin/xattr -cr "$LAUNCHER_APP" >/dev/null 2>&1 || true
}

install_launcher_app() {
  local version source_app app_binary plist_template
  source_app="$ROOT/CodexBridge.app"
  app_binary="$LAUNCHER_APP/Contents/MacOS/CodexBridge"
  plist_template="$ROOT/src/launcher-macos/Info.plist.in"
  if [[ -d "$source_app" ]]; then
    rm -rf -- "$LAUNCHER_APP"
    # ditto is Apple's recommended bundle copy; it preserves the metadata and
    # code signature that a plain recursive cp does not guarantee.
    /usr/bin/ditto "$source_app" "$LAUNCHER_APP"
    chmod +x "$app_binary"
    ensure_local_signature
    return 0
  fi
  if [[ -f "$ROOT/src/launcher-macos/CodexBridgeLauncher.swift" ]] && command -v swiftc >/dev/null 2>&1; then
    version="$(tr -d '[:space:]' < "$ROOT/VERSION")"
    rm -rf -- "$LAUNCHER_APP"
    mkdir -p "$LAUNCHER_APP/Contents/MacOS"
    swiftc -O "$ROOT/src/launcher-macos/CodexBridgeLauncher.swift" -o "$app_binary"
    sed "s/@VERSION@/$version/g" "$plist_template" > "$LAUNCHER_APP/Contents/Info.plist"
    chmod +x "$app_binary"
    ensure_local_signature
    return 0
  fi
  echo "[CodexBridge] Menu bar app bundle was not included and swiftc is unavailable; backend watcher will continue without UI." >&2
  return 1
}

copy_runtime_files
PYTHON_PATH="$(ensure_python)"
python_ok "$PYTHON_PATH" || { echo "[CodexBridge] Python runtime setup failed. See: $LOG"; read -r -p "Press Enter to close..." _ || true; exit 1; }
install_launch_agent
if install_launcher_app; then
  # Remove the legacy full-app login agent; login must start only the watcher.
  /bin/launchctl bootout "gui/$UID" "$HOME/Library/LaunchAgents/com.strengw.codexbridge.launcher.plist" >/dev/null 2>&1 || true
  rm -f -- "$HOME/Library/LaunchAgents/com.strengw.codexbridge.launcher.plist"
fi

# Start immediately even if launchctl has not scheduled the agent yet.
if [[ -f "$STATE_ROOT/macos-watcher.pid" ]] && kill -0 "$(cat "$STATE_ROOT/macos-watcher.pid" 2>/dev/null || echo 0)" 2>/dev/null; then
  :
else
  nohup /bin/bash "$APP_ROOT/codex_bridge_watcher.sh" >>"$STATE_ROOT/macos-watcher.log" 2>&1 </dev/null &
fi

# Opening CodexBridge.app below is an explicit user action; the watcher itself
# never starts CC Switch and login continues to start only the watcher agent.
APP_BIN="$LAUNCHER_APP/Contents/MacOS/CodexBridge"

launcher_running() {
  /usr/bin/pgrep -f "$APP_BIN" >/dev/null 2>&1
}

if [[ ! -x "$APP_BIN" ]]; then
  # No menu bar app could be installed (no bundled .app and no swiftc). The
  # backend watcher still runs headless, so be honest that there is no UI here.
  echo "[CodexBridge] Runtime and watcher installed; the menu bar app is unavailable on this machine."
  echo "Runtime: $APP_ROOT"
  echo "Logs: $STATE_ROOT"
  echo "You can close this Terminal window."
  sleep 2
  exit 0
fi

/usr/bin/open "$LAUNCHER_APP" >/dev/null 2>&1 || true
# `open` returns 0 even when Gatekeeper later refuses the unsigned, quarantined
# app, so success must be proven by the running menu bar process, never assumed.
launcher_started=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if launcher_running; then launcher_started=1; break; fi
  sleep 0.5
done

if [[ "$launcher_started" -eq 1 ]]; then
  /usr/bin/osascript -e 'display notification "Codex Bridge is ready and will stay available even when CC Switch is closed." with title "Codex Bridge"' >/dev/null 2>&1 || true
  echo "[CodexBridge] Ready."
  echo "Menu bar launcher: running"
  if /usr/bin/nc -z 127.0.0.1 15722 >/dev/null 2>&1; then
    echo "Bridge: running"
  else
    echo "Bridge: starting (the menu bar app ensures it on launch)"
  fi
  echo "Runtime: $APP_ROOT"
  echo "Logs: $STATE_ROOT"
  echo "You can close this Terminal window."
else
  # Never report Ready when the menu bar process did not actually come up.
  echo "[CodexBridge] Launcher failed to start." >&2
  if /usr/bin/xattr -p com.apple.quarantine "$LAUNCHER_APP" >/dev/null 2>&1; then
    echo "[CodexBridge] CodexBridge.app was blocked by macOS Gatekeeper." >&2
  fi
  if ! /usr/bin/codesign --verify --deep --strict "$LAUNCHER_APP" >/dev/null 2>&1; then
    echo "[CodexBridge] CodexBridge.app has no valid bundle signature (this is what makes macOS report it as damaged)." >&2
  fi
  echo "[CodexBridge] The runtime was installed, but the menu bar launcher did not start." >&2
  # Give a normal-user action instead of expecting them to know xattr/Gatekeeper.
  /usr/bin/open "$APP_ROOT" >/dev/null 2>&1 || true
  # macOS 15 Sequoia removed the Right-click -> Open bypass for unsigned apps, so
  # pick the guidance that matches the running system, in the user's language.
  # Nothing is stripped from the app unless the user clicks the repair button
  # (repair_gatekeeper_block); system security settings are never touched.
  macos_major="$(/usr/bin/sw_vers -productVersion 2>/dev/null | cut -d. -f1 || true)"
  case "$macos_major" in
    ''|*[!0-9]*) macos_major=0 ;;
  esac
  system_locale="$(/usr/bin/defaults read -g AppleLocale 2>/dev/null || true)"
  case "$system_locale" in
    zh*) user_lang=zh ;;
    *) user_lang=en ;;
  esac
  if [[ "$user_lang" == "zh" ]]; then
    btn_dismiss="我知道了"
    btn_repair="帮我修复"
  else
    btn_dismiss="OK"
    btn_repair="Repair"
  fi
  if [[ "$macos_major" -ge 15 ]]; then
    if [[ "$user_lang" == "zh" ]]; then
      echo "[CodexBridge] macOS 15 Sequoia 及以上：打开 系统设置 > 隐私与安全性，点底部的“仍要打开”，然后重新双击 Start CodexBridge.command。" >&2
      dialog_body="CodexBridge 未能自动打开菜单栏 App：它没有 Apple 开发者签名，被 macOS 拦截。请打开 系统设置 > 隐私与安全性，点底部的“仍要打开”，然后重新双击 Start CodexBridge.command。不要把 CodexBridge 移到废纸篓，也不要关闭 Gatekeeper。若仍打不开，点“帮我修复”。"
    else
      echo "[CodexBridge] macOS 15 Sequoia or later: open System Settings -> Privacy & Security, click 'Open Anyway' near the bottom, then reopen." >&2
      dialog_body="CodexBridge could not open its menu bar app: it is not signed by an Apple developer and macOS blocked it. Open System Settings > Privacy & Security, click Open Anyway near the bottom, then open Start CodexBridge.command again. Do not move it to the Trash and do not disable Gatekeeper. If it still fails, click Repair."
    fi
  else
    if [[ "$user_lang" == "zh" ]]; then
      echo "[CodexBridge] 在刚打开的文件夹里，右键 CodexBridge.app，选择“打开”，再点一次“打开”。" >&2
      dialog_body="CodexBridge 未能自动打开菜单栏 App（可能被 macOS Gatekeeper 拦截）。在刚打开的文件夹里，右键 CodexBridge.app，选择“打开”，再点一次“打开”。若仍打不开，点“帮我修复”。"
    else
      echo "[CodexBridge] In the folder that just opened, right-click CodexBridge.app, choose Open, then click Open again." >&2
      dialog_body="CodexBridge could not open its menu bar app automatically (macOS Gatekeeper may have blocked it). In the folder that just opened, right-click CodexBridge.app, choose Open, then click Open again. If it still fails, click Repair."
    fi
  fi
  choice="$(/usr/bin/osascript <<OSA 2>/dev/null || true
button returned of (display dialog "$dialog_body" with title "Codex Bridge" buttons {"$btn_dismiss", "$btn_repair"} default button "$btn_dismiss" with icon caution)
OSA
)"
  if [[ "$choice" == "$btn_repair" ]]; then
    repair_gatekeeper_block
    if [[ "$user_lang" == "zh" ]]; then
      echo "[CodexBridge] 已修复 CodexBridge.app，正在重新打开..." >&2
    else
      echo "[CodexBridge] Repaired CodexBridge.app; reopening it now..." >&2
    fi
    /usr/bin/open "$LAUNCHER_APP" >/dev/null 2>&1 || true
    launcher_started=0
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      if launcher_running; then launcher_started=1; break; fi
      sleep 0.5
    done
    if [[ "$launcher_started" -eq 1 ]]; then
      echo "[CodexBridge] Ready."
      echo "Menu bar launcher: running"
      if /usr/bin/nc -z 127.0.0.1 15722 >/dev/null 2>&1; then
        echo "Bridge: running"
      else
        echo "Bridge: starting (the menu bar app ensures it on launch)"
      fi
      echo "Runtime: $APP_ROOT"
      echo "Logs: $STATE_ROOT"
      echo "You can close this Terminal window."
      sleep 2
      exit 0
    fi
    if [[ "$user_lang" == "zh" ]]; then
      echo "[CodexBridge] 修复后仍未启动。请重启电脑后再试，或重新下载最新的 Release。" >&2
    else
      echo "[CodexBridge] Still not running after the repair. Reboot and try again, or re-download the latest Release." >&2
    fi
  fi
  echo "Logs: $STATE_ROOT" >&2
fi
sleep 2
