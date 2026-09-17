#!/usr/bin/env bash
set -Eeuo pipefail

# Codex Cross-Provider Bridge manager for Linux/macOS/WSL Bash.
# The script manages only the bridge process and Codex's user-level config.
# It deliberately does not restart or modify CC Switch.

CPB_VERSION="2.15.2-resident-lifecycle-fix"
CPB_COMMAND="auto"
CPB_SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CPB_PROJECT_ROOT="$(CDPATH= cd -- "$CPB_SCRIPT_DIR/../.." && pwd -P)"
if [[ -f "$CPB_SCRIPT_DIR/codex_provider_bridge.py" ]]; then
    CPB_DEFAULT_BRIDGE_SCRIPT="$CPB_SCRIPT_DIR/codex_provider_bridge.py"
else
    CPB_DEFAULT_BRIDGE_SCRIPT="$CPB_PROJECT_ROOT/src/bridge/codex_provider_bridge.py"
fi
if [[ -x "$CPB_SCRIPT_DIR/python3" ]]; then
    CPB_DEFAULT_BUNDLED_PYTHON="$CPB_SCRIPT_DIR/python3"
else
    CPB_DEFAULT_BUNDLED_PYTHON="$CPB_PROJECT_ROOT/runtime/python/bin/python3"
fi
CPB_BRIDGE_SCRIPT="${CPB_BRIDGE_SCRIPT:-$CPB_DEFAULT_BRIDGE_SCRIPT}"
CPB_BUNDLED_PYTHON="${CPB_BUNDLED_PYTHON:-$CPB_DEFAULT_BUNDLED_PYTHON}"
CPB_CODEX_CONFIG="${CPB_CODEX_CONFIG:-${CODEX_HOME:-$HOME/.codex}/config.toml}"
CPB_CODEX_EXECUTABLE="${CPB_CODEX_EXECUTABLE:-}"
CPB_BRIDGE_MODEL_CATALOG=""
CPB_LISTEN_ADDRESS="127.0.0.1"
CPB_BRIDGE_PORT=15722
CPB_UPSTREAM_URL="http://127.0.0.1:15721"
CPB_RESPONSES_WS_UPSTREAM_URL="${CPB_RESPONSES_WS_UPSTREAM_URL:-https://chatgpt.com/backend-api/codex}"
CPB_PROVIDER_ID="custom"
CPB_PROVIDER_NAME="OpenAI"
CPB_OFFICIAL_PROVIDER_ID="cc-switch-official"
CPB_MODEL=""
CPB_FOREGROUND=1
CPB_FIXED_PORT=0
CPB_PRESERVE_COMP_HASH=0
CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION=0
CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION=0
CPB_DISABLE_SWITCH_REPLAY_COMPACTION=0
CPB_ENABLE_SWITCH_REPLAY_COMPACTION=0
CPB_DISABLE_PROVIDER_CONTINUATION=0
CPB_SWITCH_REPLAY_THRESHOLD_BYTES=65536
CPB_SWITCH_REPLAY_RECENT_USER_TURNS=1
CPB_CATALOG_GUARD_GENERATION="provider-scoped-catalog-v1"
# Realtime voice is split from the custom Responses route. ChatGPT-auth call
# creation uses the ChatGPT backend; the realtime sideband WebSocket uses the
# native OpenAI endpoint.
CPB_REALTIME_WS_BASE_URL="${CPB_REALTIME_WS_BASE_URL:-https://api.openai.com/v1}"
CPB_REALTIME_WEBRTC_CALL_BASE_URL="${CPB_REALTIME_WEBRTC_CALL_BASE_URL:-https://chatgpt.com/backend-api/codex}"

usage() {
    cat <<'EOF'
Usage:
  codex_bridge_manager.sh [auto|start|repair|status|doctor|stop] [options]

Commands:
  auto      Start only for the official/bridge Codex config (default)
  start     Start or reuse the bridge and apply bridge config
  repair    Apply bridge config without selecting a CC Switch provider
  status    Show bridge, upstream, config, and process status
  doctor    Check prerequisites and machine-specific paths without changing them
  stop      Stop only the bridge process managed by this script

Options:
  --bridge-script PATH       Path to codex_provider_bridge.py
  --codex-config PATH        Path to Codex config.toml
  --codex-executable PATH    Codex binary used to export the hash-neutral bundled catalog
  --bridge-port PORT         Preferred local bridge port (default: 15722)
  --upstream-url URL         Local CC Switch URL (default: http://127.0.0.1:15721)
  --responses-ws-upstream URL Direct official Responses WS fallback base
                              (default: https://chatgpt.com/backend-api/codex)
  --provider-id ID           Codex provider table ID (default: custom)
  --provider-name NAME       Display name written to the provider table
  --official-provider-id ID  Provider ID that activates auto mode
  --model MODEL              Official model to write and force for bridged
                              /responses replays (for example gpt-5.6-sol)
  --foreground               Compatibility alias; foreground is already the default
  --background               Detach the bridge; later use stop to close it
  --fixed-port               Fail if the preferred bridge port is occupied
  --preserve-comp-hash       Disable the v2.4 cross-provider CompHashChanged guard
  --enable-prompt-cache-optimization
                              Opt in to legacy explicit GPT-5.6 cache markers
  --disable-prompt-cache-optimization
                              Compatibility alias; explicit markers are off by default
  --enable-switch-replay-compaction
                              Opt in to conservative replay pruning
  --disable-switch-replay-compaction
                              Compatibility alias; pruning is off by default
  --disable-provider-continuation
                              Disable durable per-provider catch-up continuation
  --switch-replay-threshold-bytes N
                              Compaction threshold in serialized input bytes (default: 65536)
  --switch-replay-recent-user-turns N
                              Preserve tool records for N latest user turns (default: 1)
  -h, --help                 Show this help
EOF
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

is_uint() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

validate_port() {
    local port="$1"
    is_uint "$port" || die "Invalid port: $port"
    (( port >= 1 && port <= 65535 )) || die "Port must be between 1 and 65535: $port"
}

validate_config() {
    [[ "$CPB_LISTEN_ADDRESS" == "127.0.0.1" || "$CPB_LISTEN_ADDRESS" == "localhost" ]] ||
        die 'For safety, the listen address must be 127.0.0.1 or localhost.'
    [[ "$CPB_PROVIDER_ID" =~ ^[A-Za-z0-9_-]+$ ]] ||
        die 'Provider ID may contain only letters, digits, underscores, and hyphens.'
    [[ "$CPB_OFFICIAL_PROVIDER_ID" =~ ^[A-Za-z0-9_-]+$ ]] ||
        die 'Official provider ID may contain only letters, digits, underscores, and hyphens.'
    [[ "$CPB_UPSTREAM_URL" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]+)?(/.*)?$ ]] ||
        die 'For safety, upstream URL must be a local http:// URL.'
    [[ "$CPB_RESPONSES_WS_UPSTREAM_URL" =~ ^https://chatgpt\.com(/[^[:space:]]*)?$ ]] ||
        die 'For safety, Responses WebSocket upstream must stay on https://chatgpt.com/... because Codex auth headers are forwarded there.'
    validate_port "$CPB_BRIDGE_PORT"
    (( CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION == 0 || CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION == 0 )) || die 'Cannot both enable and disable prompt-cache optimization.'
    (( CPB_ENABLE_SWITCH_REPLAY_COMPACTION == 0 || CPB_DISABLE_SWITCH_REPLAY_COMPACTION == 0 )) || die 'Cannot both enable and disable switch replay compaction.'
    is_uint "$CPB_SWITCH_REPLAY_THRESHOLD_BYTES" || die 'Switch replay threshold must be a non-negative integer.'
    is_uint "$CPB_SWITCH_REPLAY_RECENT_USER_TURNS" || die 'Recent user turns must be a positive integer.'
    (( CPB_SWITCH_REPLAY_RECENT_USER_TURNS >= 1 )) || die 'Recent user turns must be at least 1.'
}

CPB_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/CodexProviderBridge"
CPB_STATE_FILE="$CPB_STATE_DIR/bridge-state.env"
CPB_STDOUT_LOG="$CPB_STATE_DIR/bridge-stdout.log"
CPB_STDERR_LOG="$CPB_STATE_DIR/bridge-stderr.log"
CPB_RUNTIME_CWD="$CPB_STATE_DIR/runtime-cwd"

parse_args() {
    if (($# > 0)) && [[ "$1" != -* ]]; then
        CPB_COMMAND="$1"
        shift
    fi

    while (($# > 0)); do
        case "$1" in
            --bridge-script)
                (($# >= 2)) || die 'Missing value for --bridge-script.'
                CPB_BRIDGE_SCRIPT="$2"; shift 2 ;;
            --codex-config)
                (($# >= 2)) || die 'Missing value for --codex-config.'
                CPB_CODEX_CONFIG="$2"; shift 2 ;;
            --codex-executable)
                (($# >= 2)) || die 'Missing value for --codex-executable.'
                CPB_CODEX_EXECUTABLE="$2"; shift 2 ;;
            --bridge-port)
                (($# >= 2)) || die 'Missing value for --bridge-port.'
                CPB_BRIDGE_PORT="$2"; shift 2 ;;
            --upstream-url)
                (($# >= 2)) || die 'Missing value for --upstream-url.'
                CPB_UPSTREAM_URL="$2"; shift 2 ;;
            --responses-ws-upstream)
                (($# >= 2)) || die 'Missing value for --responses-ws-upstream.'
                CPB_RESPONSES_WS_UPSTREAM_URL="$2"; shift 2 ;;
            --provider-id)
                (($# >= 2)) || die 'Missing value for --provider-id.'
                CPB_PROVIDER_ID="$2"; shift 2 ;;
            --provider-name)
                (($# >= 2)) || die 'Missing value for --provider-name.'
                CPB_PROVIDER_NAME="$2"; shift 2 ;;
            --official-provider-id)
                (($# >= 2)) || die 'Missing value for --official-provider-id.'
                CPB_OFFICIAL_PROVIDER_ID="$2"; shift 2 ;;
            --model)
                (($# >= 2)) || die 'Missing value for --model.'
                CPB_MODEL="$2"; shift 2 ;;
            --foreground)
                CPB_FOREGROUND=1; shift ;;
            --background)
                CPB_FOREGROUND=0; shift ;;
            --fixed-port)
                CPB_FIXED_PORT=1; shift ;;
            --preserve-comp-hash)
                CPB_PRESERVE_COMP_HASH=1; shift ;;
            --enable-prompt-cache-optimization)
                CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION=1; shift ;;
            --disable-prompt-cache-optimization)
                CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION=1; shift ;;
            --enable-switch-replay-compaction)
                CPB_ENABLE_SWITCH_REPLAY_COMPACTION=1; shift ;;
            --disable-switch-replay-compaction)
                CPB_DISABLE_SWITCH_REPLAY_COMPACTION=1; shift ;;
            --disable-provider-continuation)
                CPB_DISABLE_PROVIDER_CONTINUATION=1; shift ;;
            --switch-replay-threshold-bytes)
                (($# >= 2)) || die 'Missing value for --switch-replay-threshold-bytes.'
                CPB_SWITCH_REPLAY_THRESHOLD_BYTES="$2"; shift 2 ;;
            --switch-replay-recent-user-turns)
                (($# >= 2)) || die 'Missing value for --switch-replay-recent-user-turns.'
                CPB_SWITCH_REPLAY_RECENT_USER_TURNS="$2"; shift 2 ;;
            -h|--help)
                usage; exit 0 ;;
            *)
                die "Unknown argument: $1" ;;
        esac
    done

    case "$CPB_COMMAND" in
        auto|start|repair|status|doctor|stop) ;;
        *) die "Unknown command: $CPB_COMMAND" ;;
    esac
    validate_config
}

resolve_python() {
    if [[ -n "${CPB_PYTHON:-}" && -x "$CPB_PYTHON" ]]; then
        :
    elif [[ -x "$CPB_BUNDLED_PYTHON" ]]; then
        CPB_PYTHON="$CPB_BUNDLED_PYTHON"
    elif command -v python3 >/dev/null 2>&1; then
        CPB_PYTHON="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        CPB_PYTHON="$(command -v python)"
    else
        die 'Python 3.10 or newer was not found. Re-run Start CodexBridge.command once to repair the private runtime.'
    fi
    local version_ok
    version_ok="$($CPB_PYTHON -c 'import sys; print(int(sys.version_info >= (3, 10)))' 2>/dev/null || true)"
    [[ "$version_ok" == "1" ]] || die 'Python 3.10 or newer is required.'
}

configured_model() {
    [[ -f "$CPB_CODEX_CONFIG" ]] || return 0
    sed -n '
/^[[:space:]]*\[/q
s/^[[:space:]]*model[[:space:]]*=[[:space:]]*"\([^"]*\)".*$/\1/p
' "$CPB_CODEX_CONFIG" | head -n 1
}

state_value() {
    local key="$1"
    [[ -f "$CPB_STATE_FILE" ]] || return 0
    awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "$CPB_STATE_FILE"
}

managed_pid() {
    local pid command_line expected
    pid="$(state_value pid || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    # The state stores the canonical absolute path used to launch Python.
    # Comparing against a caller-supplied relative path breaks status/stop as
    # soon as the manager is invoked from another working directory.
    expected="$(state_value bridge_script || true)"
    [[ -n "$expected" ]] || expected="$CPB_BRIDGE_SCRIPT"
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    [[ "$command_line" == *"$expected"* ]] || return 1
    printf '%s\n' "$pid"
}

port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnH 2>/dev/null | awk -v needle=":$port" '$4 ~ needle "$" { found=1 } END { exit(found ? 0 : 1) }'
        return $?
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
        return $?
    fi
    resolve_python
    "$CPB_PYTHON" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)
try:
    sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
finally:
    sock.close()
PY
}

find_available_port() {
    local candidate="$1" attempt
    for ((attempt = 0; attempt < 200; attempt++)); do
        ((candidate <= 65535)) || break
        if ! port_in_use "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
        ((candidate++))
    done
    die "No free local TCP port found near $1."
}

rewrite_codex_config() {
    local port="$1"
    mkdir -p "$(dirname -- "$CPB_CODEX_CONFIG")"
    CPB_CONFIG="$CPB_CODEX_CONFIG" \
    CPB_PORT="$port" \
    CPB_LISTEN="$CPB_LISTEN_ADDRESS" \
    CPB_PROVIDER="$CPB_PROVIDER_ID" \
    CPB_PROVIDER_NAME="$CPB_PROVIDER_NAME" \
    CPB_MODEL="$CPB_MODEL" \
    CPB_MODEL_CATALOG="$CPB_BRIDGE_MODEL_CATALOG" \
    CPB_PRESERVE_COMP_HASH="$CPB_PRESERVE_COMP_HASH" \
    CPB_OWN_MODEL_CATALOG="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-bundled-model-catalog.json" \
    CPB_ACTIVE_MODEL_CATALOG="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-active-model-catalog.json" \
    CPB_ACTIVE_MODEL_CATALOG_SIDECAR="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-active-model-catalog.json.source.json" \
    CPB_REALTIME_WS_BASE_URL="$CPB_REALTIME_WS_BASE_URL" \
    CPB_REALTIME_WEBRTC_CALL_BASE_URL="$CPB_REALTIME_WEBRTC_CALL_BASE_URL" \
    "$CPB_PYTHON" - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

path = Path(os.environ["CPB_CONFIG"])
port = int(os.environ["CPB_PORT"])
listen = os.environ["CPB_LISTEN"]
provider = os.environ["CPB_PROVIDER"]
provider_name = os.environ["CPB_PROVIDER_NAME"]
model = os.environ.get("CPB_MODEL", "")
model_catalog = os.environ.get("CPB_MODEL_CATALOG", "")
preserve_comp_hash = os.environ.get("CPB_PRESERVE_COMP_HASH", "0") == "1"
own_model_catalog = os.environ.get("CPB_OWN_MODEL_CATALOG", "")
active_model_catalog = os.environ.get("CPB_ACTIVE_MODEL_CATALOG", "")
active_model_catalog_sidecar = os.environ.get("CPB_ACTIVE_MODEL_CATALOG_SIDECAR", "")
realtime_ws_base_url = os.environ["CPB_REALTIME_WS_BASE_URL"]
realtime_webrtc_call_base_url = os.environ["CPB_REALTIME_WEBRTC_CALL_BASE_URL"]
exists = path.exists()
original = path.read_text(encoding="utf-8") if exists else ""
newline = "\r\n" if "\r\n" in original else "\n"
had_final_newline = original.endswith(("\n", "\r"))
lines = original.splitlines()

def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

def first_section_index(items: list[str]) -> int:
    for index, line in enumerate(items):
        if re.match(r"^\s*\[", line):
            return index
    return len(items)

def set_top_level(items: list[str], key: str, value: str) -> None:
    end = first_section_index(items)
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    for index in range(end):
        if pattern.search(items[index]):
            items[index] = f"{key} = {value}"
            return
    items.insert(end, f"{key} = {value}")

def remove_top_level(items: list[str], key: str) -> None:
    end = first_section_index(items)
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    items[:end] = [line for line in items[:end] if not pattern.search(line)]

def section_bounds(items: list[str], header: re.Pattern[str]):
    start = None
    for index, line in enumerate(items):
        if header.match(line):
            start = index
            break
    if start is None:
        return None
    end = len(items)
    for index in range(start + 1, len(items)):
        if re.match(r"^\s*\[", items[index]):
            end = index
            break
    return start, end

def set_section_key(items: list[str], header_pattern: re.Pattern[str], new_header: str,
                    key: str, value: str) -> None:
    bounds = section_bounds(items, header_pattern)
    if bounds is None:
        if items and items[-1].strip():
            items.append("")
        items.extend([new_header, f"{key} = {value}"])
        return
    start, end = bounds
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    for index in range(start + 1, end):
        if pattern.search(items[index]):
            items[index] = f"{key} = {value}"
            return
    items.insert(end, f"{key} = {value}")

escaped = re.escape(provider)
provider_header = re.compile(
    r"^\s*\[model_providers\.(?:" + escaped + r'|"' + escaped + r'")\]\s*$'
)
features_header = re.compile(r"^\s*\[features\]\s*$")

set_top_level(lines, "model_provider", quote(provider))
# v2.3 no longer forces stateless HTTP-only replay. Remove the bridge-owned
# override from older versions so Codex can use its native WebSocket chain.
remove_top_level(lines, "disable_response_storage")
# Realtime voice is deliberately split from the custom Responses provider.
# These overrides affect only the realtime websocket/WebRTC transports.
set_top_level(lines, "experimental_realtime_ws_base_url", quote(realtime_ws_base_url))
set_top_level(lines, "experimental_realtime_webrtc_call_base_url", quote(realtime_webrtc_call_base_url))
if model.strip():
    set_top_level(lines, "model", quote(model))
if preserve_comp_hash and own_model_catalog:
    # Remove only the bridge-owned catalog override; never delete a user catalog.
    current = None
    for line in lines[:first_section_index(lines)]:
        m = re.match(r'^\s*model_catalog_json\s*=\s*"((?:\\.|[^"\\])*)"', line)
        if m:
            try: current = json.loads('"' + m.group(1) + '"')
            except json.JSONDecodeError: current = m.group(1).replace('\\\\', '\\').replace('\\"', '"')
            break
    if current:
        current_abs = os.path.abspath(current)
        if active_model_catalog and current_abs == os.path.abspath(active_model_catalog):
            restored = None
            try:
                state = json.loads(Path(active_model_catalog_sidecar).read_text(encoding="utf-8"))
                candidate = state.get("source_path")
                if isinstance(candidate, str) and candidate and Path(candidate).is_file():
                    restored = candidate
            except Exception:
                restored = None
            if restored:
                set_top_level(lines, "model_catalog_json", quote(restored))
            else:
                remove_top_level(lines, "model_catalog_json")
        elif own_model_catalog and current_abs == os.path.abspath(own_model_catalog):
            remove_top_level(lines, "model_catalog_json")
elif model_catalog.strip():
    set_top_level(lines, "model_catalog_json", quote(model_catalog))
set_section_key(lines, provider_header, f"[model_providers.{provider}]", "name", quote(provider_name))
set_section_key(lines, provider_header, f"[model_providers.{provider}]", "base_url", quote(f"http://{listen}:{port}/v1"))
set_section_key(lines, provider_header, f"[model_providers.{provider}]", "wire_api", quote("responses"))
set_section_key(lines, provider_header, f"[model_providers.{provider}]", "requires_openai_auth", "true")
# Prefer Responses-over-WebSocket. v2.3 preserves Codex's native token policy:
# a turn may start with full canonical history (eligible for prompt-cache reuse),
# while same-turn follow-ups may use trusted previous_response_id + input delta.
# The bridge does not invent cross-turn response chains. HTTP remains fallback.
websocket_value = "true" if re.match(r"(?i)^(gpt-|o[0-9]|codex)", model or "") else "false"
set_section_key(lines, provider_header, f"[model_providers.{provider}]", "supports_websockets", websocket_value)
set_section_key(lines, features_header, "[features]", "enable_request_compression", "false")

updated = newline.join(lines)
if had_final_newline:
    updated += newline
if updated == original:
    print(f"Codex config is already correct: {path}")
    raise SystemExit(0)

backup = None
if exists:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    backup = path.with_name(path.name + ".bridge-backup-" + stamp)
    shutil.copy2(path, backup)

path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".bridge-tmp-", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    os.replace(temporary_name, path)
except Exception:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
    raise

print(f"Updated Codex config: {path}")
if backup:
    print(f"Backup created: {backup}")
PY
}

detect_config_mode() {
    [[ -f "$CPB_CODEX_CONFIG" ]] || { printf 'third_party\n'; return; }
    CPB_CONFIG="$CPB_CODEX_CONFIG" \
    CPB_PROVIDER="$CPB_PROVIDER_ID" \
    CPB_OFFICIAL_PROVIDER="$CPB_OFFICIAL_PROVIDER_ID" \
    CPB_DEFAULT_PORT="$CPB_BRIDGE_PORT" \
    CPB_UPSTREAM_URL="$CPB_UPSTREAM_URL" \
    CPB_STATE_PORT="$(state_value port || true)" \
    "$CPB_PYTHON" - <<'PY'
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

path = os.environ["CPB_CONFIG"]
provider_id = os.environ["CPB_PROVIDER"]
official_id = os.environ["CPB_OFFICIAL_PROVIDER"]
ports = {int(os.environ["CPB_DEFAULT_PORT"])}
upstream_url = os.environ["CPB_UPSTREAM_URL"]
state_port = os.environ.get("CPB_STATE_PORT", "")
if state_port.isdigit():
    ports.add(int(state_port))
try:
    upstream_port = urlsplit(upstream_url).port or 80
except ValueError:
    upstream_port = 15721
lines = open(path, encoding="utf-8").read().splitlines()

active = None
model = None
for line in lines:
    if re.match(r"^\s*\[", line):
        break
    match = re.match(r'^\s*model_provider\s*=\s*"((?:\\.|[^"\\])*)"', line)
    if match:
        active = match.group(1).replace('\\"', '"').replace('\\\\', '\\')
        continue
    match = re.match(r'^\s*model\s*=\s*"((?:\\.|[^"\\])*)"', line)
    if match:
        model = match.group(1).replace('\\"', '"').replace('\\\\', '\\')

if active == official_id:
    print("official")
    raise SystemExit(0)
if active is None and isinstance(model, str) and re.match(r"(?i)^(gpt-|o[0-9]|codex)", model):
    print("official")
    raise SystemExit(0)
if active != provider_id:
    print("third_party")
    raise SystemExit(0)

escaped = re.escape(provider_id)
header = re.compile(r'^\s*\[model_providers\.(?:' + escaped + r'|"' + escaped + r'")\]\s*$')
inside = False
base_url = None
for line in lines:
    if re.match(r"^\s*\[", line):
        inside = bool(header.match(line))
        continue
    if inside:
        match = re.match(r'^\s*base_url\s*=\s*"((?:\\.|[^"\\])*)"', line)
        if match:
            base_url = match.group(1).replace('\\"', '"').replace('\\\\', '\\')

if base_url:
    try:
        uri = urlsplit(base_url)
        port = uri.port or 80
        managed_range = range(int(os.environ["CPB_DEFAULT_PORT"]), min(65536, int(os.environ["CPB_DEFAULT_PORT"]) + 200))
        if uri.scheme == "http" and uri.hostname in {"127.0.0.1", "localhost"} \
                and uri.path.rstrip("/") == "/v1" \
                and (port in ports or (port in managed_range and port != upstream_port)):
            print("bridge")
            raise SystemExit(0)
    except ValueError:
        pass
print("third_party")
PY
}

write_state() {
    local pid="$1" port="$2" resolved_script="$3"
    mkdir -p "$CPB_STATE_DIR"
    local temporary="$CPB_STATE_FILE.tmp.$$"
    {
        printf 'bridge_version=%s\n' "$CPB_VERSION"
        printf 'pid=%s\n' "$pid"
        printf 'port=%s\n' "$port"
        printf 'listen_address=%s\n' "$CPB_LISTEN_ADDRESS"
        printf 'upstream_url=%s\n' "$CPB_UPSTREAM_URL"
        printf 'responses_ws_upstream_url=%s\n' "$CPB_RESPONSES_WS_UPSTREAM_URL"
        printf 'bridge_script=%s\n' "$resolved_script"
        printf 'model_override=%s\n' "$CPB_MODEL"
        printf 'preserve_comp_hash=%s\n' "$CPB_PRESERVE_COMP_HASH"
        printf 'prompt_cache_optimization=%s\n' "$([[ $CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION -eq 1 && $CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION -eq 0 ]] && echo explicit-opt-in || echo native-only)"
        printf 'switch_replay_compaction=%s\n' "$([[ $CPB_ENABLE_SWITCH_REPLAY_COMPACTION -eq 1 && $CPB_DISABLE_SWITCH_REPLAY_COMPACTION -eq 0 ]] && echo conservative-opt-in || echo disabled)"
        printf 'provider_continuation=%s\n' "$([[ $CPB_DISABLE_PROVIDER_CONTINUATION -eq 1 ]] && echo disabled || echo durable-auto)"
        printf 'switch_replay_threshold_bytes=%s\n' "$CPB_SWITCH_REPLAY_THRESHOLD_BYTES"
        printf 'switch_replay_recent_user_turns=%s\n' "$CPB_SWITCH_REPLAY_RECENT_USER_TURNS"
        printf 'catalog_guard=%s\n' "$([[ $CPB_PRESERVE_COMP_HASH -eq 1 ]] && echo disabled || echo "$CPB_CATALOG_GUARD_GENERATION")"
        printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } >"$temporary"
    mv -f -- "$temporary" "$CPB_STATE_FILE"
}

stop_bridge() {
    local pid candidate stopped=0
    pid="$(managed_pid || true)"
    if [[ -n "$pid" ]]; then
        kill "$pid" 2>/dev/null || true
        for _ in {1..20}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
        printf 'Stopped managed bridge process %s.\n' "$pid"
        stopped=1
    fi
    # Clean up orphan bridge interpreters whose state file/PID went stale.
    while IFS= read -r candidate; do
        [[ "$candidate" =~ ^[0-9]+$ ]] || continue
        [[ -n "$pid" && "$candidate" == "$pid" ]] && continue
        kill "$candidate" 2>/dev/null || true
        sleep 0.05
        kill -KILL "$candidate" 2>/dev/null || true
        printf 'Stopped residual bridge process %s.\n' "$candidate"
        stopped=1
    done < <(ps -eo pid=,args= 2>/dev/null | awk '/codex_provider_bridge\.py/ && !/awk/ {print $1}')
    rm -f -- "$CPB_STATE_FILE"
    ((stopped)) || printf 'No resident bridge process was found.\n'
}


codex_executable_version() {
    local candidate="$1"
    "$candidate" --version 2>/dev/null | head -n 1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+([^ ]*)?' | head -n 1 || true
}

resolve_codex_executable() {
    local preferred="${1:-}" candidate version resolved
    if [[ -n "$CPB_CODEX_EXECUTABLE" ]]; then
        if [[ -x "$CPB_CODEX_EXECUTABLE" ]]; then printf '%s\n' "$CPB_CODEX_EXECUTABLE"; return 0; fi
        if command -v "$CPB_CODEX_EXECUTABLE" >/dev/null 2>&1; then command -v "$CPB_CODEX_EXECUTABLE"; return 0; fi
        die "Codex executable was not found: $CPB_CODEX_EXECUTABLE"
    fi

    # On Linux, prefer an already-running Codex binary when possible. The shared
    # models_cache.json may have been rewritten by a different installed Codex
    # version, so client_version is only a selection hint, not an authority.
    if [[ -d /proc ]]; then
        for candidate in /proc/[0-9]*/exe; do
            [[ -e "$candidate" ]] || continue
            resolved="$(readlink "$candidate" 2>/dev/null || true)"
            [[ -n "$resolved" && -x "$resolved" ]] || continue
            case "$(basename -- "$resolved")" in
                codex|codex.exe)
                    if [[ -n "$preferred" ]]; then
                        version="$(codex_executable_version "$resolved")"
                        if [[ "$version" == "$preferred" ]]; then
                            printf '%s\n' "$resolved"
                            return 0
                        fi
                    fi
                    ;;
            esac
        done
    fi

    if command -v codex >/dev/null 2>&1; then
        command -v codex
        return 0
    fi
    die 'Codex CLI was not found from a running process or PATH. Pass --codex-executable explicitly.'
}

configured_model_catalog_path() {
    [[ -f "$CPB_CODEX_CONFIG" ]] || return 0
    CPB_CONFIG="$CPB_CODEX_CONFIG" "$CPB_PYTHON" - <<'PY'
import json, os, re
from pathlib import Path
p=Path(os.environ['CPB_CONFIG'])
try: text=p.read_text(encoding='utf-8')
except OSError: raise SystemExit(0)
for line in text.splitlines():
    if re.match(r'^\s*\[', line): break
    m=re.match(r'^\s*model_catalog_json\s*=\s*"((?:\\.|[^"\\])*)"', line)
    if m:
        try: v=json.loads('"'+m.group(1)+'"')
        except Exception: v=m.group(1).replace('\\\\','\\').replace('\\"','"')
        q=Path(v)
        if not q.is_absolute(): q=p.parent/q
        print(q.resolve()); break
    m=re.match(r"^\s*model_catalog_json\s*=\s*'([^']+)'", line)
    if m:
        q=Path(m.group(1))
        if not q.is_absolute(): q=p.parent/q
        print(q.resolve()); break
PY
}

export_hash_neutral_bundled_catalog() {
    ((CPB_PRESERVE_COMP_HASH)) && { CPB_BRIDGE_MODEL_CATALOG=""; return 0; }
    resolve_python
    local own configured codex raw_tmp err_tmp cache_version cli_version own_abs
    own="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-bundled-model-catalog.json"
    configured="$(configured_model_catalog_path || true)"
    own_abs="$(cd -- "$(dirname -- "$own")" && pwd -P)/$(basename -- "$own")"
    cache_version=""
    if [[ -f "$(dirname -- "$CPB_CODEX_CONFIG")/models_cache.json" ]]; then
        cache_version="$($CPB_PYTHON - "$(dirname -- "$CPB_CODEX_CONFIG")/models_cache.json" <<'PY'
import json,sys
try:
    v=json.load(open(sys.argv[1],encoding='utf-8')).get('client_version','')
    print(v if isinstance(v,str) else '')
except Exception: pass
PY
)"
    fi
    codex="$(resolve_codex_executable "$cache_version")"
    cli_version="$(codex_executable_version "$codex")"
    [[ -n "$cli_version" ]] || die "Could not determine the Codex version for '$codex'. Pass --codex-executable explicitly if this is not the client binary."
    if [[ -n "$cache_version" && "$cache_version" != "$cli_version" ]]; then
        printf "Warning: models_cache.json client_version is %s but the selected Codex binary is %s at '%s'. The cache is shared/regenerable and may have been written by another installed Codex version; continuing with the selected binary.\n" "$cache_version" "$cli_version" "$codex" >&2
    fi
    mkdir -p "$(dirname -- "$own")"
    raw_tmp="$own.raw.$$"; err_tmp="$own.err.$$"
    if ! "$codex" debug models --bundled >"$raw_tmp" 2>"$err_tmp"; then
        local tail=''; [[ -f "$err_tmp" ]] && tail="$(tail -n 8 "$err_tmp" || true)"
        rm -f -- "$raw_tmp" "$err_tmp"
        die "'codex debug models --bundled' failed.${tail:+ $tail}"
    fi
    CPB_RAW_CATALOG="$raw_tmp" CPB_OUT_CATALOG="$own" CPB_CODEX_VERSION="$cli_version" "$CPB_PYTHON" - <<'PY'
import json, os, tempfile
from pathlib import Path
src=Path(os.environ['CPB_RAW_CATALOG']); dst=Path(os.environ['CPB_OUT_CATALOG'])
payload=json.loads(src.read_text(encoding='utf-8'))
removed=0
def walk(v):
    global removed
    if isinstance(v,dict):
        if 'comp_hash' in v: v.pop('comp_hash',None); removed+=1
        for x in v.values(): walk(x)
    elif isinstance(v,list):
        for x in v: walk(x)
walk(payload)
fd,tmp=tempfile.mkstemp(prefix='.'+dst.name+'.bridge-tmp-',dir=dst.parent)
try:
    with os.fdopen(fd,'w',encoding='utf-8',newline='') as f: json.dump(payload,f,ensure_ascii=False,separators=(',',':'))
    os.replace(tmp,dst)
except Exception:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
print(f"CompHash bundled-catalog guard: exported Codex {os.environ.get('CPB_CODEX_VERSION','')} catalog and removed comp_hash from {removed} model entries: {dst}")
PY
    rm -f -- "$raw_tmp" "$err_tmp"
    if [[ -z "$CPB_BRIDGE_MODEL_CATALOG" ]]; then
        CPB_BRIDGE_MODEL_CATALOG="$own"
    fi
    printf 'CompHash bundled-catalog guard: resident mirror guard will keep provider-switch config rewrites hash-neutral while the Bridge is running.\n'
}

neutralize_configured_model_catalog_comp_hash() {
    resolve_python
    [[ -f "$CPB_CODEX_CONFIG" ]] || return 0
    local source active bundled scoped sidecar result
    source="$(configured_model_catalog_path || true)"
    [[ -n "$source" ]] || return 0
    active="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-active-model-catalog.json"
    bundled="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-bundled-model-catalog.json"
    scoped="$(dirname -- "$CPB_CODEX_CONFIG")/cpb-provider-model-catalog.json"
    sidecar="${active}.source.json"

    if ((CPB_PRESERVE_COMP_HASH)); then
        return 0
    fi
    if [[ "$source" == "$bundled" ]]; then
        CPB_BRIDGE_MODEL_CATALOG="$bundled"
        return 0
    fi
    if [[ "$source" == "$active" ]]; then
        CPB_BRIDGE_MODEL_CATALOG="$active"
        return 0
    fi
    local source_dir source_name scoped_dir scoped_base scoped_ext
    source_dir="$(dirname -- "$source")"
    source_name="$(basename -- "$source")"
    scoped_dir="$(dirname -- "$scoped")"
    scoped_base="$(basename -- "$scoped" .json)"
    scoped_ext=".json"
    if [[ "$source_dir" == "$scoped_dir" && ( "$source" == "$scoped" || "$source_name" =~ ^${scoped_base}\.snapshot-[0-9a-fA-F]{8,}${scoped_ext}$ ) ]]; then
        # Already a Bridge-published current-provider-only snapshot. Do not copy it
        # back into the private learned catalog during manager startup.
        CPB_BRIDGE_MODEL_CATALOG="$source"
        return 0
    fi
    if [[ ! -f "$source" ]]; then
        printf 'Warning: CompHash static-catalog guard: model_catalog_json points to a missing file: %s\n' "$source" >&2
        return 0
    fi

    result="$({ CPB_SOURCE_CATALOG="$source" CPB_ACTIVE_CATALOG="$active" CPB_ACTIVE_SIDECAR="$sidecar" "$CPB_PYTHON" - <<'PYCODE'
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
src=Path(os.environ['CPB_SOURCE_CATALOG']).resolve()
dst=Path(os.environ['CPB_ACTIVE_CATALOG']).resolve()
sidecar=Path(os.environ['CPB_ACTIVE_SIDECAR']).resolve()
payload=json.loads(src.read_text(encoding='utf-8'))
removed=0
def walk(v):
    global removed
    if isinstance(v,dict):
        if 'comp_hash' in v:
            v.pop('comp_hash',None); removed+=1
        for x in v.values(): walk(x)
    elif isinstance(v,list):
        for x in v: walk(x)
walk(payload)
dst.parent.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.'+dst.name+'.bridge-tmp-',dir=dst.parent)
try:
    with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
        json.dump(payload,f,ensure_ascii=False,separators=(',',':'))
    os.replace(tmp,dst)
except Exception:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
st=src.stat()
state={'source_path':str(src),'source_signature':[st.st_mtime_ns,st.st_size]}
fd,tmp=tempfile.mkstemp(prefix='.'+sidecar.name+'.tmp-',dir=sidecar.parent)
try:
    with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
        json.dump(state,f,ensure_ascii=False,separators=(',',':'))
    os.replace(tmp,sidecar)
except Exception:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
print(removed)
PYCODE
} 2>&1)" || {
        printf 'Warning: CompHash static-catalog guard could not mirror %s: %s\n' "$source" "$result" >&2
        return 0
    }
    CPB_BRIDGE_MODEL_CATALOG="$active"
    printf 'CompHash static-catalog guard: copied provider catalog to bridge-owned neutral mirror; removed %s comp_hash fields: %s\n' "$result" "$active"
}

neutralize_models_cache_comp_hash() {
    resolve_python
    local cache_path
    cache_path="$(dirname -- "$CPB_CODEX_CONFIG")/models_cache.json"
    if ((CPB_PRESERVE_COMP_HASH)); then
        if [[ -f "$cache_path" ]]; then
            rm -f -- "$cache_path"
            printf 'CompHash cache guard: preserve requested; removed %s so Codex can refetch unmodified model metadata.\n' "$cache_path"
        fi
        return 0
    fi
    [[ -f "$cache_path" ]] || return 0

    CPB_MODELS_CACHE="$cache_path" "$CPB_PYTHON" - <<'PY'
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

path = Path(os.environ["CPB_MODELS_CACHE"])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    print(f"Warning: CompHash cache guard could not parse {path}: {exc}")
    raise SystemExit(0)

removed = 0
def walk(value):
    global removed
    if isinstance(value, dict):
        if "comp_hash" in value:
            value.pop("comp_hash", None)
            removed += 1
        for nested in value.values():
            walk(nested)
    elif isinstance(value, list):
        for nested in value:
            walk(nested)
walk(payload)
if not removed:
    raise SystemExit(0)

path.parent.mkdir(parents=True, exist_ok=True)
fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".bridge-tmp-", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_name, path)
except Exception:
    try:
        os.unlink(temp_name)
    except FileNotFoundError:
        pass
    raise
print(f"CompHash cache guard: removed comp_hash from {removed} cached model entries in {path}")
PY
}

start_bridge() {
    [[ -f "$CPB_BRIDGE_SCRIPT" ]] || die "Bridge script not found: $CPB_BRIDGE_SCRIPT"
    resolve_python
    mkdir -p "$CPB_STATE_DIR"

    local existing_pid existing_port existing_model existing_version existing_upstream existing_ws_upstream existing_preserve_comp_hash existing_catalog_guard existing_switch_compaction existing_switch_threshold existing_switch_recent existing_provider_continuation requested_switch_compaction requested_provider_continuation requested_model selected_port resolved_script automatic_model
    # Do not freeze the Official model seen at bridge startup. CC Switch/Codex can
    # legitimately move between Luna/Sol while this bridge stays resident. A model
    # override is now used only when the user explicitly passed --model.
    existing_pid="$(managed_pid || true)"
    existing_port="$(state_value port || true)"
    existing_model="$(state_value model_override || true)"
    existing_version="$(state_value bridge_version || true)"
    existing_upstream="$(state_value upstream_url || true)"
    existing_ws_upstream="$(state_value responses_ws_upstream_url || true)"
    existing_preserve_comp_hash="$(state_value preserve_comp_hash || true)"
    [[ "$existing_preserve_comp_hash" == "1" ]] || existing_preserve_comp_hash=0
    existing_catalog_guard="$(state_value catalog_guard || true)"
    existing_switch_compaction="$(state_value switch_replay_compaction || true)"
    existing_switch_threshold="$(state_value switch_replay_threshold_bytes || true)"
    existing_switch_recent="$(state_value switch_replay_recent_user_turns || true)"
    existing_provider_continuation="$(state_value provider_continuation || true)"
    requested_switch_compaction="$([[ $CPB_ENABLE_SWITCH_REPLAY_COMPACTION -eq 1 && $CPB_DISABLE_SWITCH_REPLAY_COMPACTION -eq 0 ]] && echo conservative-opt-in || echo disabled)"
    requested_provider_continuation="$([[ $CPB_DISABLE_PROVIDER_CONTINUATION -eq 1 ]] && echo disabled || echo durable-auto)"
    requested_model="$CPB_MODEL"
    if [[ -z "$requested_model" && -n "$existing_model" ]]; then
        requested_model="$existing_model"
        CPB_MODEL="$existing_model"
    fi

    # CC Switch commonly configures model_catalog_json. Mirror external provider
    # catalogs into a private learned copy instead of editing them in place; the
    # resident bridge guard publishes a current-provider-only picker snapshot.
    neutralize_configured_model_catalog_comp_hash
    export_hash_neutral_bundled_catalog
    neutralize_models_cache_comp_hash

    if [[ -n "$existing_pid" && "$existing_port" =~ ^[0-9]+$ ]] && port_in_use "$existing_port"; then
        if ((CPB_FOREGROUND)); then
            printf 'Restarting the existing managed bridge in foreground mode.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_version" != "$CPB_VERSION" ]]; then
            printf 'Bridge version changed (%s -> %s); restarting it.\n' "${existing_version:--}" "$CPB_VERSION"
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_upstream" != "$CPB_UPSTREAM_URL" || "$existing_ws_upstream" != "$CPB_RESPONSES_WS_UPSTREAM_URL" ]]; then
            printf 'Bridge upstream configuration changed; restarting it.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_model" != "$requested_model" ]]; then
            printf 'Bridge model override changed (%s -> %s); restarting it.\n' "${existing_model:--}" "${requested_model:--}"
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_preserve_comp_hash" != "$CPB_PRESERVE_COMP_HASH" ]]; then
            printf 'Bridge CompHash policy changed; restarting it.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        elif (( ! CPB_PRESERVE_COMP_HASH )) && [[ "$existing_catalog_guard" != "$CPB_CATALOG_GUARD_GENERATION" ]]; then
            printf 'Bridge resident catalog guard changed; restarting it.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_switch_compaction" != "$requested_switch_compaction" \
                || "$existing_switch_threshold" != "$CPB_SWITCH_REPLAY_THRESHOLD_BYTES" \
                || "$existing_switch_recent" != "$CPB_SWITCH_REPLAY_RECENT_USER_TURNS" ]]; then
            printf 'Bridge switch-replay policy changed; restarting it.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        elif [[ "$existing_provider_continuation" != "$requested_provider_continuation" ]]; then
            printf 'Bridge provider-continuation policy changed; restarting it.\n'
            stop_bridge
            existing_pid=''
            existing_port=''
        else
            printf 'Bridge is already running on http://%s:%s\n' "$CPB_LISTEN_ADDRESS" "$existing_port"
            rewrite_codex_config "$existing_port"
            return 0
        fi
    fi
    if [[ -f "$CPB_STATE_FILE" && -z "$existing_pid" ]]; then
        rm -f -- "$CPB_STATE_FILE"
    fi

    selected_port="$CPB_BRIDGE_PORT"
    if port_in_use "$selected_port"; then
        if ((CPB_FIXED_PORT)); then
            die "Port $selected_port is already in use. Stop that process or choose another --bridge-port."
        fi
        selected_port="$(find_available_port "$((CPB_BRIDGE_PORT + 1))")"
        printf 'Warning: port %s is occupied; using %s instead.\n' "$CPB_BRIDGE_PORT" "$selected_port" >&2
    fi
    resolved_script="$(CDPATH= cd -- "$(dirname -- "$CPB_BRIDGE_SCRIPT")" && pwd -P)/$(basename -- "$CPB_BRIDGE_SCRIPT")"
    local bridge_args=(
        --listen "$CPB_LISTEN_ADDRESS:$selected_port"
        --upstream "$CPB_UPSTREAM_URL"
        --responses-ws-upstream "$CPB_RESPONSES_WS_UPSTREAM_URL"
        --codex-config "$CPB_CODEX_CONFIG"
        --bundled-neutral-catalog "$(dirname -- "$CPB_CODEX_CONFIG")/cpb-bundled-model-catalog.json"
        --active-neutral-catalog "$(dirname -- "$CPB_CODEX_CONFIG")/cpb-active-model-catalog.json"
        --official-provider-id "$CPB_OFFICIAL_PROVIDER_ID"
        --bridge-provider-id "$CPB_PROVIDER_ID"
        --bridge-provider-name "$CPB_PROVIDER_NAME"
        --bridge-base-url "http://$CPB_LISTEN_ADDRESS:$selected_port/v1"
        --realtime-ws-base-url "$CPB_REALTIME_WS_BASE_URL"
        --realtime-webrtc-call-base-url "$CPB_REALTIME_WEBRTC_CALL_BASE_URL"
    )
    bridge_args+=(--switch-replay-threshold-bytes "$CPB_SWITCH_REPLAY_THRESHOLD_BYTES")
    bridge_args+=(--switch-replay-recent-user-turns "$CPB_SWITCH_REPLAY_RECENT_USER_TURNS")
    if ((CPB_ENABLE_SWITCH_REPLAY_COMPACTION)); then
        bridge_args+=(--enable-switch-replay-compaction)
    elif ((CPB_DISABLE_SWITCH_REPLAY_COMPACTION)); then
        bridge_args+=(--disable-switch-replay-compaction)
    fi
    if [[ -n "$CPB_MODEL" ]]; then
        bridge_args+=(--model-override "$CPB_MODEL")
    fi
    if ((CPB_PRESERVE_COMP_HASH)); then
        bridge_args+=(--preserve-comp-hash)
    fi
    if ((CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION)); then
        bridge_args+=(--enable-prompt-cache-optimization)
    elif ((CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION)); then
        bridge_args+=(--disable-prompt-cache-optimization)
    fi
    if ((CPB_DISABLE_PROVIDER_CONTINUATION)); then
        bridge_args+=(--disable-provider-continuation)
    fi
    mkdir -p "$CPB_RUNTIME_CWD"
    if ((CPB_FOREGROUND)); then
        (cd "$CPB_RUNTIME_CWD" && exec "$CPB_PYTHON" -u "$resolved_script" "${bridge_args[@]}") &
    else
        (cd "$CPB_RUNTIME_CWD" && exec nohup "$CPB_PYTHON" -u "$resolved_script" "${bridge_args[@]}" \
            >"$CPB_STDOUT_LOG" 2>"$CPB_STDERR_LOG" < /dev/null) &
    fi
    local pid=$!
    write_state "$pid" "$selected_port" "$resolved_script"

    for _ in {1..50}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        if port_in_use "$selected_port"; then
            rewrite_codex_config "$selected_port"
            printf 'Bridge started: http://%s:%s\n' "$CPB_LISTEN_ADDRESS" "$selected_port"
            printf 'HTTP /responses upstream: %s\n' "$CPB_UPSTREAM_URL"
            printf 'Responses WebSocket direct fallback: %s\n' "$CPB_RESPONSES_WS_UPSTREAM_URL"
            printf 'Responses transport: Official Responses WS goes direct first (avoids CC Switch 405 probe rows); third-party routes stay HTTP-only through CC Switch.\n'
            printf 'Token policy: auth-aware restart continuity. Codex may restart when CC Switch must reload the selected ChatGPT account/model UI; keep the Bridge running. Matching Official restart replays are converted to resident-session deltas; returning third-party models use conversation-scoped shadow cursors, durable previous_response_id catch-up, and guarded restart instruction-envelope pinning when supported. No replay pruning is used by default.\n'
            if ((CPB_ENABLE_SWITCH_REPLAY_COMPACTION && ! CPB_DISABLE_SWITCH_REPLAY_COMPACTION)); then
                printf 'Switch replay compaction: enabled by opt-in; threshold=%s bytes; recent user turns=%s.\n' "$CPB_SWITCH_REPLAY_THRESHOLD_BYTES" "$CPB_SWITCH_REPLAY_RECENT_USER_TURNS"
            else
                printf 'Switch replay compaction: disabled by default; full fallback history is preserved.\n'
            fi
            if ((CPB_ENABLE_PROMPT_CACHE_OPTIMIZATION && ! CPB_DISABLE_PROMPT_CACHE_OPTIMIZATION)); then
                printf 'Prompt-cache optimization: explicit markers enabled by opt-in; native implicit caching also remains active.\n'
            else
                printf 'Prompt-cache optimization: native implicit cache only (explicit markers disabled by default).\n'
            fi
            if ((CPB_DISABLE_PROVIDER_CONTINUATION)); then
                printf 'Provider continuation: disabled.\n'
            else
                printf 'Provider continuation: enabled (Official guarded resident WS; third-party conversation-scoped durable shadow cursor + provider-return instruction pin).\n'
            fi
            if ((CPB_PRESERVE_COMP_HASH)); then
                printf 'CompHash switch guard: disabled; upstream model comp_hash is preserved.\n'
            elif [[ -z "$CPB_MODEL" ]]; then
                printf 'CompHash switch guard: enabled; provider-scoped catalog guard exposes only the active CC Switch provider in Codex while retaining a private learned catalog for routing/capability metadata; provider files are never modified in place.\n'
            else
                printf "CompHash switch guard: enabled; provider-scoped catalog guard follows provider-switch rewrites and rotates Codex to a current-provider-only hash-neutral catalog. /models and models_cache.json remain fallbacks. Request-model override remains '%s'.\n" "$CPB_MODEL"
            fi
            printf 'Realtime voice sideband WebSocket: %s (bypasses bridge)\n' "$CPB_REALTIME_WS_BASE_URL"
            printf 'Realtime voice call creation: %s (bypasses bridge)\n' "$CPB_REALTIME_WEBRTC_CALL_BASE_URL"
            if ((CPB_FOREGROUND)); then
                printf 'Foreground mode is active. Press Ctrl+C, close this terminal, or terminate the VS Code task to stop the bridge.\n'
                trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; if [[ "$(state_value pid || true)" == "$pid" ]]; then rm -f -- "$CPB_STATE_FILE"; fi; exit 130' INT TERM
                local exit_code=0
                wait "$pid" || exit_code=$?
                trap - INT TERM
                if [[ "$(state_value pid || true)" == "$pid" ]]; then
                    rm -f -- "$CPB_STATE_FILE"
                fi
                return "$exit_code"
            fi
            return 0
        fi
        sleep 0.1
    done
    local error_tail=''
    [[ -f "$CPB_STDERR_LOG" ]] && error_tail="$(tail -n 8 "$CPB_STDERR_LOG" || true)"
    kill "$pid" 2>/dev/null || true
    rm -f -- "$CPB_STATE_FILE"
    die "Bridge failed to start.${error_tail:+\n$error_tail}"
}

repair_config() {
    resolve_python
    local port="$CPB_BRIDGE_PORT" state_port
    state_port="$(state_value port || true)"
    if [[ -z "$CPB_MODEL" ]]; then
        local state_model
        state_model="$(state_value model_override || true)"
        if [[ -n "$state_model" ]]; then
            CPB_MODEL="$state_model"
        fi
    fi
    if [[ "$state_port" =~ ^[0-9]+$ ]] && port_in_use "$state_port"; then
        port="$state_port"
    elif ! port_in_use "$port"; then
        printf 'Warning: no managed bridge is listening on port %s; config will be repaired but requests will fail until it starts.\n' "$port" >&2
    fi
    neutralize_configured_model_catalog_comp_hash
    export_hash_neutral_bundled_catalog
    neutralize_models_cache_comp_hash
    rewrite_codex_config "$port"
    printf 'Repair complete. Codex provider %s points to http://%s:%s/v1\n' "$CPB_PROVIDER_ID" "$CPB_LISTEN_ADDRESS" "$port"
}

show_status() {
    local pid port='' persisted_preserve_comp_hash=''
    pid="$(managed_pid || true)"
    port="$(state_value port || true)"
    persisted_preserve_comp_hash="$(state_value preserve_comp_hash || true)"
    [[ "$port" =~ ^[0-9]+$ ]] || port="$CPB_BRIDGE_PORT"
    printf 'BridgeVersion: %s\n' "$CPB_VERSION"
    printf 'ManagedProcess: %s\n' "$([[ -n "$pid" ]] && echo true || echo false)"
    printf 'ProcessId: %s\n' "${pid:-none}"
    printf 'BridgeUrl: http://%s:%s\n' "$CPB_LISTEN_ADDRESS" "$port"
    printf 'BridgeListening: %s\n' "$(port_in_use "$port" && echo true || echo false)"
    printf 'UpstreamUrl: %s\n' "$CPB_UPSTREAM_URL"
    printf 'ResponsesWebSocketUpstreamUrl: %s\n' "$CPB_RESPONSES_WS_UPSTREAM_URL"
    printf 'ResponsesWebSocketPolicy: cc-switch-first-direct-official-fallback\n'
    printf 'ModelOverride: %s\n' "$(state_value model_override || true)"
    printf 'ResponsesTransport: websocket-preferred\n'
    printf 'ResponsesContinuation: provider-local-durable-catchup\n'
    printf 'CatalogConfigGuard: %s\n' "$(state_value catalog_guard || echo none)"
    if [[ "$persisted_preserve_comp_hash" == "1" || "$persisted_preserve_comp_hash" == "true" ]]; then
        printf 'CompHashSwitchGuard: preserve\n'
    elif [[ "$persisted_preserve_comp_hash" == "0" || "$persisted_preserve_comp_hash" == "false" ]]; then
        printf 'CompHashSwitchGuard: neutralize-catalog\n'
    elif ((CPB_PRESERVE_COMP_HASH)); then
        printf 'CompHashSwitchGuard: preserve (requested; no managed state)\n'
    else
        printf 'CompHashSwitchGuard: neutralize-catalog (requested; no managed state)\n'
    fi
    printf 'HttpFallback: full-portable-replay-when-provider-state-unavailable\n'
    printf 'RealtimeVoiceRoute: native-chatgpt-openai\n'
    printf 'RealtimeWsBaseUrl: %s\n' "$CPB_REALTIME_WS_BASE_URL"
    printf 'RealtimeWebRtcCallBaseUrl: %s\n' "$CPB_REALTIME_WEBRTC_CALL_BASE_URL"
    local upstream_host upstream_port
    if [[ "$CPB_UPSTREAM_URL" =~ ^http://(127\.0\.0\.1|localhost):([0-9]+) ]]; then
        upstream_host="${BASH_REMATCH[1]}"
        upstream_port="${BASH_REMATCH[2]}"
        printf 'UpstreamListening: %s\n' "$(port_in_use "$upstream_port" && echo true || echo false)"
    else
        printf 'UpstreamListening: unknown\n'
    fi
    printf 'CodexConfig: %s\n' "$CPB_CODEX_CONFIG"
    printf 'StateFile: %s\n' "$CPB_STATE_FILE"
}

show_doctor() {
    printf 'Codex Cross-Provider Bridge portability check\n'
    printf 'ManagerScript: %s\n' "$CPB_SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")"
    printf 'ProjectRoot: %s\n' "$CPB_PROJECT_ROOT"
    printf 'BridgeScript: %s\n' "$CPB_BRIDGE_SCRIPT"
    printf 'BridgeScriptExists: %s\n' "$([[ -f "$CPB_BRIDGE_SCRIPT" ]] && echo true || echo false)"
    printf 'BundledPython: %s\n' "$CPB_BUNDLED_PYTHON"
    printf 'BundledPythonExists: %s\n' "$([[ -x "$CPB_BUNDLED_PYTHON" ]] && echo true || echo false)"
    if resolve_python 2>/dev/null; then
        printf 'Python: %s\n' "$CPB_PYTHON"
        printf 'PythonVersion: %s\n' "$($CPB_PYTHON -c 'import platform; print(platform.python_version())')"
    else
        printf 'Python: ERROR - Python 3.10 or newer was not found\n'
    fi
    printf 'CodexConfig: %s\n' "$CPB_CODEX_CONFIG"
    printf 'CodexConfigExists: %s\n' "$([[ -f "$CPB_CODEX_CONFIG" ]] && echo true || echo false)"
    printf 'DetectedConfigMode: %s\n' "$(detect_config_mode)"
    printf 'PreferredBridgePortAvailable: %s\n' "$(! port_in_use "$CPB_BRIDGE_PORT" && echo true || echo false)"
    printf 'ResponsesWebSocketUpstreamUrl: %s\n' "$CPB_RESPONSES_WS_UPSTREAM_URL"
    printf 'ResponsesWebSocketPolicy: cc-switch-first-direct-official-fallback\n'
    printf 'ResponsesTransport: websocket-preferred (HTTP fallback remains available)\n'
    printf 'ResponsesContinuation: provider-local durable cursor + unseen catch-up delta; full replay fallback\n'
    if ((CPB_PRESERVE_COMP_HASH)); then
        printf 'CompHashSwitchGuard: preserve\n'
    else
        printf 'CompHashSwitchGuard: neutralize-catalog\n'
    fi
    printf 'RealtimeVoiceRoute: native-chatgpt-openai (bypasses local bridge and CC Switch)\n'
    printf 'RealtimeWsBaseUrl: %s\n' "$CPB_REALTIME_WS_BASE_URL"
    printf 'RealtimeWebRtcCallBaseUrl: %s\n' "$CPB_REALTIME_WEBRTC_CALL_BASE_URL"
    show_status
}

automatic_bridge() {
    resolve_python
    local mode
    mode="$(detect_config_mode)"
    case "$mode" in
        official|bridge)
            printf 'Official/bridge Codex configuration detected; ensuring the bridge is running.\n'
            start_bridge ;;
        *)
            local existing_pid
            existing_pid="$(managed_pid || true)"
            if [[ -n "$existing_pid" ]]; then
                printf 'Third-party configuration detected; leaving the already-running bridge resident and idle. Its resident provider-scoped catalog guard maintains current-provider-only model_catalog_json wiring; provider/model routing remains owned by the current configuration. Use stop to terminate it explicitly.\n'
            else
                printf 'Third-party or non-bridge Codex configuration detected; no bridge will be started.\n'
                [[ -f "$CPB_STATE_FILE" ]] && rm -f -- "$CPB_STATE_FILE"
            fi ;;
    esac
}

main() {
    parse_args "$@"
    case "$CPB_COMMAND" in
        auto) automatic_bridge ;;
        start) start_bridge ;;
        repair) repair_config ;;
        status) show_status ;;
        doctor) show_doctor ;;
        stop) stop_bridge ;;
    esac
}

main "$@"
