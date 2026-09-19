#!/usr/bin/env python3
"""Adaptive provider-neutral bridge for Codex Responses requests.

v2.15.1-repo-quickstart-compilefix prioritizes conversation correctness over
third-party replay savings. Third-party shadow cursors are isolated by Codex's logical
thread identity from ``x-client-request-id`` when available (hashed locally), with the old
first-user fingerprint used only as a compatibility fallback. Cross-provider durable shadow continuation is now disabled for
tool-bearing histories, open tool chains, unverified/empty provider completions, and any
system/developer instruction drift. Those cases fall back to a complete portable replay
instead of attaching a possibly stale previous_response_id. This closes the class of bugs
where a long Codex task could resume with the wrong working state after DeepSeek/GLM/Qwen
switches. Pure-message conversations may still use durable delta continuation, but only
when the saved provider checkpoint is completion-verified and the current instruction
envelope is semantically unchanged.

v2.11.4-third-party-proxy-supervisor keeps provider-scoped catalogs and uses a guarded handoff latch so Launcher can keep model_provider=custom while switching custom.base_url between the local Bridge and the direct Official ChatGPT Codex backend. The bridge still keeps
a private learned catalog for routing/capability memory, but Codex now receives an immutable
hash-neutral catalog containing only the currently selected CC Switch provider. Official
routes publish only bundled Official models; GLM/DeepSeek/Qwen routes publish only the
provider catalog observed from CC Switch. Provider changes rotate model_catalog_json before
the launcher restarts Codex, so stale models from other providers no longer remain selectable.

v2.10.2-third-party-envelope-pin-relaxed keeps conversation-scoped third-party shadow
cursors and fixes the remaining provider-return instruction spike.  A verified leave/return
already proves the same provider/model conversation via conversation fingerprint, semantic
timeline prefix, durable response cursor, and route-serial gap.  For that narrow case, large
Codex runtime bootstrap envelopes are pinned using role + large-envelope + runtime-marker
guards instead of requiring the nested JSON shape to remain byte-structurally identical
across a Codex restart.  Small/new instructions are still sent, and deletion/reorder still
falls back conservatively.  The saved provider response_id remains the durable cursor: when
accepted, the Bridge sends only provider-unseen conversation suffix; when rejected it falls
back once to the complete current replay and invalidates only that stale cursor.

v2.9.4-http-error-sanitize treats a Codex authentication restart as a transport
re-attachment, not a provider-instruction refresh, but only after the new canonical replay
has been matched to the exact detached resident Official WebSocket.  For that one verified
restart replay, if the system/developer instruction count and role layout are unchanged, the
resident instruction envelope is pinned and only unseen conversational items are appended.
Instruction deletions/reorders still reject the optimization and preserve the full-replay
fallback.  This targets the observed 73 KB restart-only instruction delta without changing
normal same-process instruction updates or third-party durable continuation.

v2.9.1-resident-delta-refine builds on the resident restart architecture after real
A->third-party->Official testing.  It keeps restart-generated Codex instruction envelopes
from defeating a valid resident-session match when the old/new system/developer messages
are overwhelmingly identical apart from volatile restart metadata.  The comparison is
conservative: roles must match, large text length may change only slightly, and normalized
token similarity must remain very high; materially changed instructions are still appended
or force the existing full-replay safety fallback.  Official internal HTTP models such as
Terra are also sent directly to the Official Codex backend while a third-party CC Switch
route is active, so they are never silently billed as GLM/DeepSeek/Qwen work.  Stale
third-party startup probes on an Official direct WebSocket are repaired to the current
Official model before forwarding.

v2.9.0-resident-restart-continuity accepts that returning from a third-party route to
OpenAI Official may require a Codex restart to reload ChatGPT account authentication. The
bridge therefore keeps the *provider conversation* alive independently of the Codex client:
a completed Official conversation stays on its original direct Responses WebSocket while
Codex/CC Switch restart. New Codex WebSockets begin on an isolated bootstrap upstream; only
a meaningful full replay whose portable timeline matches a detached resident conversation
is migrated onto that old Official socket. Startup probes/background sockets are never
blindly re-attached. The matched replay is then converted to previous_response_id + unseen
delta by the existing live continuation store. If the resident socket expired or the backend
rejects its live response id, correctness falls back to the complete current replay.

v2.7.2-catalog-refresh extends v2.7.1 with immutable catalog snapshots. When a new
third-party model catalog is learned while Codex is already running, the bridge publishes
a content-addressed snapshot and rotates config.toml model_catalog_json to the new path.
Recent Codex builds may still require a process restart before the picker reflects a new
catalog; catalog refresh is therefore no longer treated as a prerequisite for continuity.

v2.7.1-unified-catalog keeps the restart-free hot-switch path from v2.7.0 and adds
a unified, hash-neutral model catalog. The catalog preserves the full bundled Official
model entries plus every third-party catalog observed from CC Switch, including each
model's reasoning-effort/capability metadata. Codex therefore keeps one process alive
while its model picker can select the concrete model for the currently selected CC Switch
route. The bridge tracks the upstream route separately from the model selected in Codex,
so changing the UI model no longer changes provider routing. Requests that still carry a
stale model immediately after a CC Switch route change are rebound once to that route's
default model; once the user selects a concrete model from the unified catalog, that exact
model and its reasoning settings are preserved. One logical request is forwarded to one
upstream route only; no cross-provider retry is attempted on a route mismatch.

v2.7.0-hot-switch removes Codex restart from the provider-switch path. The resident
config guard keeps Codex permanently pointed at this bridge, while each user-facing
Responses request is dynamically rebound to the model currently selected by CC Switch.
Official internal/background models (for example Terra) are never rewritten. When the
route changes away from an already-open Official WebSocket, the bridge closes that
client connection before forwarding a stale request so Codex can immediately retry on
the current route; third-party routes remain HTTP-only. The bridge remembers the last
user-facing Official model seen on the live Codex process so returning from a third-party
route does not accidentally replace Luna with a stale config-default Sol. Provider-local
continuation remains a second layer: third-party durable state catches up only unseen
timeline items, while Official keeps native store=false semantics and implicit caching.
No conversation text, tool history, or instructions are pruned by default.

v2.6.5-continuity-refine keeps the v2.6.4 provider-local cursor model and fixes
three remaining continuity leaks. Third-party instruction refresh compares semantic wire
content (ignoring nested provider ids/status/annotations) before deciding that a large
system/developer item changed, preventing metadata-only restarts from resending tens of
kilobytes. Official-looking payload models are classified as Official even while CC
Switch is temporarily on a third-party route, so internal GPT background requests never
probe third-party durable storage. Finally, Official full replays always receive a stable
model/conversation prompt_cache_key; if no user item is present yet, a model-local cache
bucket is used instead of silently skipping the key.

v2.6.4-continuity-delta fixes two remaining switch-cost regressions. Third-party
provider continuation now diffs system/developer instructions item-by-item instead of
resending the entire instruction envelope when any single instruction changes. If the
instruction sequence cannot be updated safely (for example an instruction disappeared or
roles were reordered), the bridge preserves correctness with a full replay. Official
full replays now receive the same deterministic prompt_cache_key on both HTTP and WS
paths, so a Codex restart does not lose cache bucketing merely because transport changed.

v2.6.3-cache-continuity restores Codex's native Official turn semantics and targets the
actual switch-cost problem: cache continuity across Codex/provider restarts. Official
cross-turn previous_response_id resurrection is disabled because the ChatGPT Codex
store=false backend rejects those saved turn handles. Full Official replays instead get
a deterministic per-conversation prompt_cache_key (with transparent capability
fallback) while exact replay-prefix stabilization remains conservative. Third-party
durable continuation now compares semantically normalized conversation items so a
provider output message can match the equivalent Codex replay message even when wire
content block types/status fields differ. The manager no longer freezes a startup
Official model such as Sol and later applies it while the user selected Luna; stale
third-party model repair follows the current config dynamically.

v2.6.2-live-official-session kept Official store=false while preserving its live
Responses WebSocket across provider switches. Returning to the same Official model
re-attaches to the still-live upstream socket and sends only the canonical conversation
delta the Official session has not seen. Third-party HTTP continuation remains durable
when the provider supports store=true. If the live Official socket expires, the bridge
falls back to the complete portable replay rather than pruning history.

v2.6.1-storefalse-hotfix keeps provider-local continuation logic but respects the
ChatGPT Codex backend requirement that Official Responses requests use ``store=false``.
Third-party HTTP routes may still probe durable storage when supported. The optimization
target remains provider-local continuity rather than replay pruning.

v2.6.0-provider-continuation changes the optimization target from replay pruning to
provider-local conversation continuity. Each effective provider/model keeps a durable
Responses checkpoint when the upstream accepts ``store=true``. When the user returns
to that provider, the bridge compares the provider's last synchronized conversation
timeline with Codex's current canonical history and sends only the messages/tool state
that provider has not seen yet. System/developer instructions are never silently pinned:
if they changed while the provider was inactive, the current instruction items are sent
as part of the catch-up delta. If durable response storage or an old response id is
rejected, the bridge falls back to the complete portable replay and remembers the
provider capability instead of repeatedly retrying an invalid optimization. Conservative
replay compaction and explicit prompt-cache markers remain available but are disabled by
default; native implicit caching and same-turn continuation stay intact. Third-party
Responses WebSocket attempts are rejected locally so HTTP fallback does not sit through
repeated CC Switch 405/timeout cycles.

v2.5.4-stateful-save keeps the v2.5.3 compatibility path and adds guarded per-model
continuation reuse across provider switches. If a saved response covers an exact
portable prefix of the next full replay for the same model, the bridge sends only the
new suffix with that saved ``previous_response_id``. If the provider rejects the old
state, the bridge transparently retries the full portable replay and invalidates only
that stale checkpoint. Multiple recent response states are retained so background
Codex requests cannot overwrite the useful visible-turn state. Third-party custom
routes are also marked HTTP-only and local WS upgrades are rejected immediately,
avoiding the repeated 405/timeout loop seen when CC Switch does not support Responses
WebSocket for those providers. Existing CompHash, voice bypass, replay sanitation,
implicit-cache stabilization, and native same-turn continuation behavior remain.

v2.5.1-token-save keeps all v2.5.0 compatibility behavior and adds conservative
switch-replay token reduction plus runtime cache-capability memory. Full replays now
deduplicate byte-identical system/developer items and may omit stale, fully paired
tool call/output records that are older than the configured recent-user-turn window.
Visible user/assistant text is never summarized or truncated. If the Official backend
rejects explicit prompt-cache breakpoints once, the bridge remembers that capability
for the process lifetime and stops sending the rejected fields.

v2.5.0 keeps the v2.4 resident CompHash guard and adds stable explicit prompt-cache
breakpoints for GPT-5.6 full replays. The breakpoints are placed at deterministic
prefix-size checkpoints so append-only canonical history keeps the same reusable
boundaries across provider switches. For ChatGPT Codex backend compatibility the
bridge does not send request-level ``prompt_cache_options``; it relies on the
backend's default implicit-cache behavior. If an Official backend rejects an
explicit breakpoint, the bridge transparently retries that request once without
v2.5 cache-control fields, preserving the v2.4 request semantics.

v2.4.0 keeps the v2.3 native Responses-over-WebSocket/token path and adds
CompHashChanged protection for cross-provider switches. The manager exports a
hash-neutral bundled catalog from the selected local Codex binary. A resident
catalog guard in this bridge then follows provider-switch rewrites of config.toml:
external catalogs are copied to a bridge-owned mirror with only ``comp_hash``
removed, while Official configurations that remove ``model_catalog_json`` are
re-pointed at the bundled hash-neutral catalog. Provider-managed catalogs are never
modified in place. The bridge also strips ``comp_hash`` from bridged ``/models``
responses as defense in depth. Missing hashes mean unknown compatibility, not fake
compatibility. Provider-private reasoning/item/response state is still scrubbed at
replay boundaries.

v2.3.0 prefers Codex's native Responses-over-WebSocket transport and mirrors
Codex's turn-scoped token behavior instead of inventing a second conversation
state machine. The first request of a Codex turn may contain the full canonical
history; prompt caching can make most of that prefix reused/cached upstream.
Within the same turn, provider-issued ``previous_response_id`` values plus only
the incremental input delta are preserved unchanged. The bridge deliberately
does not synthesize cross-turn deltas because Codex treats response-chain state
and sticky routing as turn-scoped. HTTP remains a conservative stateless
fallback for compatibility.

The bridge sits between Codex and a local CC Switch proxy. HTTP /responses
continues to use CC Switch. Responses WebSocket upgrades try CC Switch first and
fall back directly to the ChatGPT Codex backend when the local route does not
support WebSocket, preserving Codex's native incremental transport on the
Official route. An optional model override can replace a stale third-party model
name without rewriting the stored Codex session.
"""

from __future__ import annotations

import argparse
import base64
from collections import deque
import difflib
import http.client
import hashlib
import json
import os
import re
import select
import signal
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies, proxy_bypass


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

PORTABILITY_ERROR_MARKERS = (
    b"invalid 'input[",
    b'invalid "input[',
    b"encrypted content",
    b"could not be verified",
    b"expected an id that begins",
    b"array too long",
    b"previous_response_id",
    b"no tool output found for tool call",
    b"no tool call found for tool output",
    b"tool output not found",
    b"tool call not found",
)

# These terms are deliberately narrow.  A generic 400/422 must not trigger replay
# rewriting merely because a model, account, quota, or authentication setting is invalid.
# The compatibility firewall activates only when the upstream error names structured
# Responses state that commonly becomes non-portable after switching providers.
PORTABILITY_STATE_TERMS = (
    b"encrypted_content",
    b"encrypted content",
    b"reasoning",
    b"item_reference",
    b"item reference",
    b"compaction",
    b"previous_response_id",
    b"function_call",
    b"function call",
    b"function_call_output",
    b"tool_call",
    b"tool call",
    b"tool_output",
    b"tool output",
    b"call_id",
    b"computer_call",
    b"web_search_call",
)
PORTABILITY_REJECTION_TERMS = (
    b"unsupported",
    b"not supported",
    b"unknown",
    b"invalid",
    b"missing",
    b"not found",
    b"expected",
    b"must be",
    b"cannot",
    b"could not",
)


MAX_WS_FRAME_PAYLOAD = 128 * 1024 * 1024
WS_TEXT = 0x1
WS_BINARY = 0x2
WS_CLOSE = 0x8
WS_PING = 0x9
WS_PONG = 0xA
WS_CONTINUATION = 0x0


class BufferedSocketReader:
    """Small exact-read wrapper that preserves bytes received with the WS handshake."""

    def __init__(self, sock: socket.socket, initial: bytes = b"") -> None:
        self.sock = sock
        self.buffer = bytearray(initial)

    def read_exact(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = self.sock.recv(max(4096, size - len(self.buffer)))
            if not chunk:
                raise EOFError("websocket peer closed")
            self.buffer.extend(chunk)
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data


def read_ws_frame(reader: BufferedSocketReader) -> tuple[bool, int, bytes, int]:
    """Read one RFC6455 frame and return (fin, opcode, payload, rsv_bits)."""
    first, second = reader.read_exact(2)
    fin = bool(first & 0x80)
    rsv_bits = first & 0x70
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(reader.read_exact(2), "big")
    elif length == 127:
        length = int.from_bytes(reader.read_exact(8), "big")
    if length > MAX_WS_FRAME_PAYLOAD:
        raise OSError(f"websocket frame too large: {length} bytes")
    mask_key = reader.read_exact(4) if masked else b""
    payload = reader.read_exact(length) if length else b""
    if masked:
        payload = bytes(byte ^ mask_key[index & 3] for index, byte in enumerate(payload))
    return fin, opcode, payload, rsv_bits


def encode_ws_frame(
    fin: bool,
    opcode: int,
    payload: bytes,
    *,
    masked: bool,
    rsv_bits: int = 0,
) -> bytes:
    first = (0x80 if fin else 0) | (rsv_bits & 0x70) | (opcode & 0x0F)
    length = len(payload)
    second_mask = 0x80 if masked else 0
    if length < 126:
        head = bytes((first, second_mask | length))
    elif length < (1 << 16):
        head = bytes((first, second_mask | 126)) + length.to_bytes(2, "big")
    else:
        head = bytes((first, second_mask | 127)) + length.to_bytes(8, "big")
    if not masked:
        return head + payload
    mask_key = os.urandom(4)
    masked_payload = bytes(byte ^ mask_key[index & 3] for index, byte in enumerate(payload))
    return head + mask_key + masked_payload


def strip_websocket_extensions(header_bytes: bytes) -> bytes:
    """Disable per-message compression so the bridge can safely inspect JSON frames."""
    lines = header_bytes.split(b"\r\n")
    filtered = [
        line
        for line in lines
        if not line.lower().startswith(b"sec-websocket-extensions:")
    ]
    return b"\r\n".join(filtered)


def _connect_via_http_proxy(
    proxy_url: str,
    target_host: str,
    target_port: int,
    *,
    timeout: float,
) -> socket.socket:
    """Open an HTTP CONNECT tunnel without exposing proxy credentials in logs."""
    proxy = urlsplit(proxy_url)
    if proxy.scheme.lower() != "http" or not proxy.hostname:
        raise OSError(
            f"unsupported proxy scheme for Responses WebSocket: {proxy.scheme or 'unknown'}"
        )
    proxy_port = proxy.port or 80
    sock = socket.create_connection((proxy.hostname, proxy_port), timeout=timeout)
    try:
        request = [
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n".encode("ascii"),
            f"Host: {target_host}:{target_port}\r\n".encode("ascii"),
            b"Proxy-Connection: Keep-Alive\r\n",
        ]
        if proxy.username is not None:
            username = unquote(proxy.username)
            password = unquote(proxy.password or "")
            token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            request.append(f"Proxy-Authorization: Basic {token}\r\n".encode("ascii"))
        request.append(b"\r\n")
        sock.sendall(b"".join(request))

        response_head = bytearray()
        while b"\r\n\r\n" not in response_head:
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("HTTP proxy closed during CONNECT")
            response_head.extend(chunk)
            if len(response_head) > 65536:
                raise OSError("HTTP proxy CONNECT response headers are too large")
        status_line = bytes(response_head).split(b"\r\n", 1)[0]
        try:
            status = int(status_line.split(b" ", 2)[1])
        except (IndexError, ValueError) as exc:
            raise OSError(f"invalid HTTP proxy CONNECT response: {status_line!r}") from exc
        if status != 200:
            raise OSError(f"HTTP proxy CONNECT failed with status {status}")
        return sock
    except Exception:
        sock.close()
        raise


def _connect_outbound_socket(
    scheme: str,
    host: str,
    port: int,
    *,
    timeout: float,
) -> socket.socket:
    """Connect to an upstream, honoring standard HTTP proxy discovery for HTTPS.

    This is used only for the bridge's direct Official Responses WebSocket
    fallback. Loopback targets are always connected directly.
    """
    loopback = host.lower() in {"127.0.0.1", "localhost", "::1"}
    if scheme == "https" and not loopback and not proxy_bypass(host):
        proxies = getproxies()
        proxy_url = proxies.get("https") or proxies.get("http") or proxies.get("all")
        if proxy_url:
            parsed = urlsplit(proxy_url)
            if parsed.scheme.lower() == "http":
                return _connect_via_http_proxy(
                    proxy_url, host, port, timeout=timeout
                )
    return socket.create_connection((host, port), timeout=timeout)


def _is_full_replay_input(items: object) -> bool:
    if not isinstance(items, list):
        return False
    if len(items) > 1:
        return True
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        role = item.get("role")
        if item_type in {
            "reasoning",
            "compaction",
            "function_call",
            "function_call_output",
            "item_reference",
            "computer_call",
            "computer_call_output",
            "web_search_call",
            "custom_tool_call",
            "custom_tool_call_output",
        }:
            return True
        if role in {"assistant", "developer", "system"}:
            return True
    return False


class WebSocketContinuationState:
    """Tracks provider IDs and native turn-scoped WS request modes.

    The socket may outlive one model request, but this bridge does not treat a
    provider response ID as durable conversation history. It only recognizes IDs
    actually observed from the live upstream connection and never fabricates an unverified
    cross-turn ``previous_response_id`` chain. v2.5.4 may reuse a response id only
    through the guarded per-model continuation store with exact-prefix matching.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.known_response_ids: set[str] = set()
        self.known_item_ids: set[str] = set()
        self.response_create_count = 0
        self.full_replay_count = 0
        self.native_incremental_count = 0

    def response_is_known(self, value: object) -> bool:
        return isinstance(value, str) and value in self.known_response_ids

    def item_is_known(self, value: object) -> bool:
        return isinstance(value, str) and value in self.known_item_ids

    def record_server_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        response_ids: set[str] = set()
        item_ids: set[str] = set()

        response = event.get("response")
        if isinstance(response, dict):
            response_id = response.get("id")
            if isinstance(response_id, str) and response_id:
                response_ids.add(response_id)
            output = response.get("output")
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, dict):
                        item_id = item.get("id")
                        if isinstance(item_id, str) and item_id:
                            item_ids.add(item_id)

        response_id = event.get("response_id")
        if isinstance(response_id, str) and response_id:
            response_ids.add(response_id)

        item = event.get("item")
        if isinstance(item, dict):
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                item_ids.add(item_id)

        # Some event shapes nest output items more deeply. Only trust exact IDs
        # that came from the upstream server on this live socket.
        def walk(value: object) -> None:
            if isinstance(value, dict):
                if "type" in value:
                    nested_id = value.get("id")
                    if isinstance(nested_id, str) and nested_id and not nested_id.startswith("resp_"):
                        item_ids.add(nested_id)
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(event)
        with self.lock:
            self.known_response_ids.update(response_ids)
            self.known_item_ids.update(item_ids)

    def snapshot_counts(self) -> tuple[int, int, int, int, int]:
        with self.lock:
            return (
                self.response_create_count,
                self.full_replay_count,
                self.native_incremental_count,
                len(self.known_response_ids),
                len(self.known_item_ids),
            )


PROMPT_CACHE_CHECKPOINT_BYTES = (48 * 1024, 96 * 1024, 192 * 1024)


SWITCH_REPLAY_DEFAULT_THRESHOLD_BYTES = 64 * 1024
SWITCH_REPLAY_DEFAULT_RECENT_USER_TURNS = 1

TOOL_CALL_TYPES = {
    "function_call",
    "custom_tool_call",
    "computer_call",
}
TOOL_OUTPUT_TYPES = {
    "function_call_output",
    "custom_tool_call_output",
    "computer_call_output",
}

# Provider-hosted tool state is not portable in the same way as a plain function
# call/result pair.  It is removed only on a retry *after* the target provider has
# already rejected the original request; normal successful traffic is untouched.
PORTABLE_PROVIDER_OWNED_ITEM_TYPES = {
    "reasoning",
    "compaction",
    "item_reference",
    "web_search_call",
    "web_search_call_output",
    "computer_call",
    "computer_call_output",
}

# Optional response-shaping fields that are safe to drop on the guarded compatibility
# retry.  They do not carry the user's conversational text or tool results.
PORTABLE_OPTIONAL_TOP_LEVEL_FIELDS = {
    "reasoning",
    "include",
    "prompt_cache_key",
    "prompt_cache_retention",
    "prompt_cache_breakpoint",
    "prompt_cache_options",
}

def _portable_item_signature(item: object) -> bytes:
    """Stable signature for exact replay deduplication, ignoring provider item IDs."""
    if not isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    normalized = dict(item)
    normalized.pop("id", None)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _semantic_timeline_item(item: object) -> object:
    """Normalize the same conversational item across provider/output wire shapes.

    This is used only to decide whether a durable third-party provider has already
    seen a conversation prefix. It does not rewrite the request sent upstream.
    Provider ids/status/annotations and input_text vs output_text wrappers are not
    semantic conversation changes, so they are normalized for matching.
    """
    if not isinstance(item, dict):
        return item
    item_type = item.get("type")
    role = item.get("role")
    if item_type == "message" or role in {"user", "assistant", "system", "developer"}:
        content = item.get("content")
        normalized_content: list[object] = []
        if isinstance(content, str):
            normalized_content.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    normalized_content.append(block)
                    continue
                block_type = block.get("type")
                if block_type in {"input_text", "output_text", "text"}:
                    normalized_content.append({"type": "text", "text": block.get("text", "")})
                    continue
                cleaned_block = {
                    k: v for k, v in block.items()
                    if k not in {"id", "status", "annotations", "encrypted_content"}
                }
                normalized_content.append(cleaned_block)
        return {"type": "message", "role": role, "content": normalized_content}

    if item_type in TOOL_CALL_TYPES:
        return {
            "type": "tool_call",
            "name": item.get("name"),
            "call_id": item.get("call_id") or item.get("tool_call_id"),
            "arguments": item.get("arguments"),
        }
    if item_type in TOOL_OUTPUT_TYPES:
        return {
            "type": "tool_output",
            "call_id": item.get("call_id") or item.get("tool_call_id"),
            "output": item.get("output"),
        }

    return {
        k: v for k, v in item.items()
        if k not in {"id", "status", "encrypted_content", "annotations"}
    }


def _semantic_timeline_signature(item: object) -> bytes:
    return json.dumps(
        _semantic_timeline_item(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _timeline_contains_tool_state(items: object) -> bool:
    """Return True when a canonical conversation contains provider/tool state.

    Tool-bearing Codex histories are deliberately treated as unsafe for cross-provider
    durable cursor reuse. Even when visible messages match, a provider-side response cursor
    can carry hidden tool execution state that another Codex/provider cycle cannot prove.
    Full portable replay is cheaper than corrupting the agent's working task.
    """
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in TOOL_CALL_TYPES | TOOL_OUTPUT_TYPES | {
            "web_search_call",
            "web_search_call_output",
            "computer_call",
            "computer_call_output",
        }:
            return True
    return False


def _tool_chain_closed(items: object) -> bool:
    """Conservatively verify that every visible tool call has a matching output.

    Missing/opaque call ids are considered unsafe rather than guessed. This guard is used
    only for provider-return optimization; normal full replay behavior is unchanged.
    """
    if not isinstance(items, list):
        return True
    open_calls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in TOOL_CALL_TYPES:
            call_id = item.get("call_id") or item.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                return False
            open_calls.add(call_id)
            continue
        if item_type in TOOL_OUTPUT_TYPES:
            call_id = item.get("call_id") or item.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                return False
            open_calls.discard(call_id)
    return not open_calls


def _has_meaningful_provider_output(items: object) -> bool:
    """Require a concrete assistant/tool result before creating a durable shadow cursor."""
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "assistant":
            return True
        if item.get("type") in TOOL_CALL_TYPES | TOOL_OUTPUT_TYPES:
            return True
    return False


def _instruction_text_for_restart_compare(item: object) -> str:
    """Extract human-readable instruction text without provider-owned wire metadata."""
    if not isinstance(item, dict):
        return ""
    content = item.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type in {"input_text", "output_text", "text"}:
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


_VOLATILE_RESTART_PATTERNS = (
    re.compile(r"\b(?:resp|msg|call|item|sess|session|request|req)_[A-Za-z0-9_-]{6,}\b", re.I),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
    re.compile(r"cpb-active-model-catalog\.snapshot-[0-9a-f]{8,}\.json", re.I),
    re.compile(r"\b20\d{2}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b"),
)


def _normalize_restart_instruction_text(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    for pattern in _VOLATILE_RESTART_PATTERNS:
        value = pattern.sub("<volatile>", value)
    value = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n"))
    return value.strip()


_VOLATILE_RESTART_LINE_PATTERNS = (
    re.compile(r"(?i)^\s*(?:model_provider|model_catalog_json|base_url|wire_api|supports_websockets|requires_openai_auth)\s*="),
    re.compile(r"(?i)\b(?:cpb-|codexproviderbridge|cc switch|models_cache|client_version|comp_hash|route_model|provider_state)\b"),
    re.compile(r"(?i)\b(?:session|request|response|item)[-_ ]?(?:id|key)\b"),
)


def _restart_volatile_line(line: str) -> bool:
    value = line.strip()
    if not value:
        return True
    if "<volatile>" in value:
        return True
    return any(pattern.search(value) for pattern in _VOLATILE_RESTART_LINE_PATTERNS)


def _restart_instruction_equivalent(previous: object, current: object) -> bool:
    """Ignore only restart churn that is provably confined to runtime metadata lines.

    Exact semantic equality remains the primary path. After normalizing generated ids,
    timestamps and catalog snapshot hashes, any remaining textual edit is considered real
    unless every changed line is explicitly recognized as bridge/Codex runtime metadata.
    This is intentionally stricter than fuzzy similarity: one user/project policy line
    changing must never disappear merely because the surrounding 70 KB envelope stayed the
    same.
    """
    if _semantic_timeline_signature(previous) == _semantic_timeline_signature(current):
        return True
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    if previous.get("role") != current.get("role"):
        return False
    old_text = _normalize_restart_instruction_text(_instruction_text_for_restart_compare(previous))
    new_text = _normalize_restart_instruction_text(_instruction_text_for_restart_compare(current))
    if not old_text or not new_text:
        return False
    if old_text == new_text:
        return True
    # Do not relax matching for small instructions; exact normalized equality is required.
    if max(len(old_text), len(new_text)) < 2048:
        return False

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    changed_any = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_any = True
        changed_lines = old_lines[i1:i2] + new_lines[j1:j2]
        if not changed_lines or not all(_restart_volatile_line(line) for line in changed_lines):
            return False
    return changed_any



def _conversation_fingerprint(items: object) -> str:
    """Return a stable, privacy-preserving label for one conversational timeline.

    The fingerprint is deliberately *not* used as proof that two conversations are the
    same. Resident Official re-attachment is authorized only by a semantic prefix match
    against provider state that was actually completed on that exact live upstream socket.
    This short hash is only useful in logs and for distinguishing resident sessions.
    """
    portable = _portableize_state_items(items)
    first_user: object | None = None
    for item in portable:
        if isinstance(item, dict) and item.get("role") == "user":
            first_user = item
            break
    if first_user is None:
        return ""
    digest = hashlib.sha256(_semantic_timeline_signature(first_user)).hexdigest()
    return digest[:16]


def _conversation_prompt_cache_key(model: object, items: object) -> str | None:
    """Derive a stable cache bucket from the first user message of one conversation.

    The key is only a cache-bucketing hint; exact prompt prefixes are still required
    by the upstream cache, so a collision cannot substitute content from another chat.
    """
    if not isinstance(model, str) or not isinstance(items, list):
        return None
    first_user: object | None = None
    for item in items:
        if isinstance(item, dict) and item.get("role") == "user":
            first_user = item
            break
    digest = hashlib.sha256()
    digest.update(model.strip().lower().encode("utf-8"))
    digest.update(b"\0")
    if first_user is not None:
        digest.update(b"conversation\0")
        digest.update(_semantic_timeline_signature(first_user))
    else:
        # Some Codex startup/full-replay requests contain only the large
        # system/developer envelope.  A per-model bucket still keeps those
        # prefixes on a stable cache route; exact prefix equality remains
        # required upstream, so this cannot substitute content across chats.
        digest.update(b"model-bucket")
    return "cpb-" + digest.hexdigest()[:40]


def apply_prompt_cache_key(
    payload: object, *, enabled: bool, namespace: str
) -> tuple[object, bool]:
    """Attach one deterministic cache bucket to an Official full replay.

    The same helper is used by HTTP and WS so a Codex restart/transport change does
    not silently create a different cache bucket.  Exact prefix equality is still
    required by the upstream cache; this key only improves routing affinity.
    """
    if (
        not enabled
        or namespace != "official"
        or not isinstance(payload, dict)
        or not isinstance(payload.get("input"), list)
        or not _is_full_replay_input(payload.get("input"))
        or "prompt_cache_key" in payload
    ):
        return payload, False
    cache_key = _conversation_prompt_cache_key(payload.get("model"), payload.get("input"))
    if not cache_key:
        return payload, False
    rewritten = dict(payload)
    rewritten["prompt_cache_key"] = cache_key
    return rewritten, True


def _tool_link_id(item: dict[str, object]) -> str | None:
    """Return a provider-neutral call linkage key when one is explicitly present."""
    for key in ("call_id", "tool_call_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _prune_unpaired_tool_items(items: list[object]) -> tuple[list[object], int]:
    """Drop only tool call/output records whose visible counterpart is absent.

    Some provider adapters reject a portable full replay when Codex replays a tool call
    whose output lived only in provider-side state (or vice versa).  Never invent a tool
    result.  On the portability retry path, retain complete call/output pairs verbatim and
    omit only dangling tool records so the remaining visible transcript is structurally
    valid for a stateless provider.
    """
    call_ids: set[str] = set()
    output_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in TOOL_CALL_TYPES:
            call_id = _tool_link_id(item)
            if call_id:
                call_ids.add(call_id)
        elif item_type in TOOL_OUTPUT_TYPES:
            call_id = _tool_link_id(item)
            if call_id:
                output_ids.add(call_id)

    complete_ids = call_ids & output_ids
    cleaned: list[object] = []
    omitted = 0
    for item in items:
        if isinstance(item, dict) and item.get("type") in TOOL_CALL_TYPES | TOOL_OUTPUT_TYPES:
            call_id = _tool_link_id(item)
            if not call_id or call_id not in complete_ids:
                omitted += 1
                continue
        cleaned.append(item)
    return cleaned, omitted


def _strict_tool_adjacency_error(error_body: bytes | None) -> bool:
    """Recognize the narrow tool-transcript ordering failure seen in strict adapters.

    This is intentionally separate from the broader portability classifier.  The extra
    adjacency repair must run only after the target has explicitly rejected a tool-call
    transcript, not for unrelated encrypted/reasoning/id portability failures.
    """
    if not error_body:
        return False
    lowered = error_body.lower()
    names_tool_state = (
        b"tool_calls" in lowered
        or b"tool call" in lowered
        or b"tool_call_id" in lowered
        or b"tool message" in lowered
    )
    names_adjacency = any(
        marker in lowered
        for marker in (
            b"must be followed",
            b"followed by tool",
            b"insufficient tool messages",
            b"responding to each",
        )
    )
    return names_tool_state and names_adjacency


STRICT_TOOL_ADJACENCY_REPAIR_HINT = (
    b"tool_calls must be followed by tool messages responding to each tool_call_id"
)


class StrictToolAdjacencyCapabilityStore:
    """Process-local, conversation-scoped memory for proven strict tool adapters.

    A capability is learned only after an explicit strict-tool 400/422 is repaired by the
    existing compatibility firewall and that retry succeeds.  The key includes the
    provider-state conversation scope and route serial, so another Codex conversation
    (or a later route epoch) keeps the already-working normal path untouched.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.required_keys: set[tuple[int, str]] = set()

    @staticmethod
    def _key(provider_state_key: str, route_serial: int) -> tuple[int, str] | None:
        if not provider_state_key or provider_state_key == "-":
            return None
        return int(route_serial), provider_state_key

    def requires(self, provider_state_key: str, route_serial: int) -> bool:
        key = self._key(provider_state_key, route_serial)
        if key is None:
            return False
        with self.lock:
            return key in self.required_keys

    def mark_required(self, provider_state_key: str, route_serial: int) -> bool:
        key = self._key(provider_state_key, route_serial)
        if key is None:
            return False
        with self.lock:
            was_new = key not in self.required_keys
            self.required_keys.add(key)
            return was_new

    def forget(self, provider_state_key: str, route_serial: int) -> bool:
        key = self._key(provider_state_key, route_serial)
        if key is None:
            return False
        with self.lock:
            if key not in self.required_keys:
                return False
            self.required_keys.remove(key)
            return True


def make_learned_strict_tool_payload(
    payload: dict[str, object],
) -> tuple[dict[str, object], int, int, bool]:
    """Reuse the already-proven firewall repair shape without another failed probe."""
    return make_portable_responses_payload(
        payload, error_body=STRICT_TOOL_ADJACENCY_REPAIR_HINT
    )


def _prune_nonadjacent_tool_groups(items: list[object]) -> tuple[list[object], int]:
    """Drop globally paired tool groups whose call/output ordering is not portable.

    Some OpenAI-compatible adapters translate Responses function-call items into a
    Chat-Completions-style assistant ``tool_calls`` message.  Those adapters require that
    message to be followed immediately by tool messages covering every declared call id
    before any unrelated message appears.

    Never reorder history and never fabricate a tool result.  Keep a tool group only when a
    contiguous run of calls is immediately followed by a contiguous run of outputs covering
    exactly the same unique call ids.  Otherwise omit that invalid tool segment while
    preserving all non-tool conversation items in their original order.
    """
    keep_indexes: set[int] = set()
    omitted_indexes: set[int] = set()
    index = 0

    while index < len(items):
        item = items[index]
        item_type = item.get("type") if isinstance(item, dict) else None

        if item_type in TOOL_CALL_TYPES:
            call_indexes: list[int] = []
            call_ids: list[str] = []
            cursor = index
            while cursor < len(items):
                current = items[cursor]
                current_type = current.get("type") if isinstance(current, dict) else None
                if current_type not in TOOL_CALL_TYPES:
                    break
                call_indexes.append(cursor)
                call_id = _tool_link_id(current)
                if call_id:
                    call_ids.append(call_id)
                cursor += 1

            output_indexes: list[int] = []
            output_ids: list[str] = []
            while cursor < len(items):
                current = items[cursor]
                current_type = current.get("type") if isinstance(current, dict) else None
                if current_type not in TOOL_OUTPUT_TYPES:
                    break
                output_indexes.append(cursor)
                call_id = _tool_link_id(current)
                if call_id:
                    output_ids.append(call_id)
                cursor += 1

            call_id_set = set(call_ids)
            output_id_set = set(output_ids)
            valid_group = bool(
                call_indexes
                and output_indexes
                and len(call_ids) == len(call_indexes)
                and len(output_ids) == len(output_indexes)
                and len(call_id_set) == len(call_ids)
                and len(output_id_set) == len(output_ids)
                and call_id_set == output_id_set
            )

            if valid_group:
                keep_indexes.update(call_indexes)
                keep_indexes.update(output_indexes)
            else:
                omitted_indexes.update(call_indexes)
                omitted_indexes.update(output_indexes)

            index = cursor
            continue

        if item_type in TOOL_OUTPUT_TYPES:
            # An output not consumed by an immediately preceding call group is structurally
            # orphaned for strict Chat-Completions-style adapters.
            omitted_indexes.add(index)

        index += 1

    cleaned: list[object] = []
    for idx, item in enumerate(items):
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type in TOOL_CALL_TYPES | TOOL_OUTPUT_TYPES:
            if idx in keep_indexes and idx not in omitted_indexes:
                cleaned.append(item)
            continue
        cleaned.append(item)

    return cleaned, len(omitted_indexes)


def compact_switch_replay_items(
    items: list[object],
    *,
    threshold_bytes: int = SWITCH_REPLAY_DEFAULT_THRESHOLD_BYTES,
    recent_user_turns: int = SWITCH_REPLAY_DEFAULT_RECENT_USER_TURNS,
) -> tuple[list[object], dict[str, int | bool]]:
    """Conservatively reduce portable full-replay history without summarizing text.

    The optimization is intentionally narrow: exact duplicate system/developer
    messages are removed, and old tool call/output pairs may be omitted only when
    both sides carry the same explicit call id and occur before the recent-user-turn
    window. User and assistant messages are always retained verbatim.
    """
    before_bytes = sum(_json_size(item) for item in items)
    meta: dict[str, int | bool] = {
        "applied": False,
        "before_bytes": before_bytes,
        "after_bytes": before_bytes,
        "deduped_instruction_items": 0,
        "omitted_stale_tool_items": 0,
    }
    if before_bytes < max(0, threshold_bytes) or not items:
        return items, meta

    # Find the first item that belongs to the N most recent user turns.
    keep_from = len(items)
    turns_seen = 0
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if isinstance(item, dict) and item.get("role") == "user":
            turns_seen += 1
            keep_from = index
            if turns_seen >= max(1, recent_user_turns):
                break
    if turns_seen == 0:
        keep_from = len(items)

    # Exact duplicate instruction messages are safe to dedupe. Keep the first
    # occurrence so append-only prefix shape remains as stable as possible.
    seen_instruction_signatures: set[bytes] = set()
    duplicate_instruction_indexes: set[int] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("role") not in {"system", "developer"}:
            continue
        signature = _portable_item_signature(item)
        if signature in seen_instruction_signatures:
            duplicate_instruction_indexes.add(index)
        else:
            seen_instruction_signatures.add(signature)

    # Omit only fully paired, stale tool records. If linkage is missing or the
    # pair crosses into the recent window, preserve it unchanged.
    calls: dict[str, list[int]] = {}
    outputs: dict[str, list[int]] = {}
    for index, item in enumerate(items[:keep_from]):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        link = _tool_link_id(item)
        if link is None:
            continue
        if item_type in TOOL_CALL_TYPES:
            calls.setdefault(link, []).append(index)
        elif item_type in TOOL_OUTPUT_TYPES:
            outputs.setdefault(link, []).append(index)

    stale_tool_indexes: set[int] = set()
    for link in calls.keys() & outputs.keys():
        stale_tool_indexes.update(calls[link])
        stale_tool_indexes.update(outputs[link])

    compacted: list[object] = []
    for index, item in enumerate(items):
        if index in duplicate_instruction_indexes:
            meta["deduped_instruction_items"] = int(meta["deduped_instruction_items"]) + 1
            continue
        if index in stale_tool_indexes:
            meta["omitted_stale_tool_items"] = int(meta["omitted_stale_tool_items"]) + 1
            continue
        compacted.append(item)

    after_bytes = sum(_json_size(item) for item in compacted)
    meta["after_bytes"] = after_bytes
    meta["applied"] = len(compacted) != len(items)
    return compacted, meta


class ReplayPrefixCheckpointStore:
    """Keep recent byte-stable portable replay prefixes per effective model.

    v2.5.2 kept only the *latest* replay for each model. Codex can emit several
    unrelated/background full replays around startup and model switching, so that
    single slot was frequently overwritten before the user returned to a model.
    v2.5.3 keeps a short history and chooses the candidate with the longest exact
    portable prefix. It may also pin a leading system/developer instruction item
    from that same model when its wire shape and size are nearly identical; this
    neutralizes small volatile fields (timestamps/session metadata) that otherwise
    destroy the whole implicit-cache prefix while keeping user/assistant text and
    tool records untouched.

    This still is *not* response-id/session resurrection. No old response ID or
    encrypted provider state is reused.
    """

    MAX_CHECKPOINTS_PER_KEY = 12
    INSTRUCTION_SIZE_TOLERANCE = 0.12
    INSTRUCTION_SIZE_ABS_TOLERANCE = 4096

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items_by_key: dict[str, deque[list[object]]] = {}

    @staticmethod
    def _clone(items: list[object]) -> list[object]:
        # JSON round-trip keeps only wire-relevant data and avoids later mutation.
        return json.loads(json.dumps(items, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    def _common_prefix(previous: list[object], current: list[object]) -> tuple[int, int]:
        common = 0
        prefix_bytes = 0
        limit = min(len(previous), len(current))
        while common < limit:
            if _portable_item_signature(previous[common]) != _portable_item_signature(current[common]):
                break
            prefix_bytes += _json_size(previous[common])
            common += 1
        return common, prefix_bytes

    @staticmethod
    def _instruction_role(item: object) -> str | None:
        if not isinstance(item, dict):
            return None
        role = item.get("role")
        return role if role in {"system", "developer"} else None

    @staticmethod
    def _instruction_shape(item: object) -> bytes:
        """Shape-only signature for a leading instruction message.

        Text values are replaced with markers; keys, roles and content block types
        stay in the signature. This lets us recognize the same Codex instruction
        envelope even when a tiny volatile string changes.
        """
        def normalize(value: object, key: str | None = None) -> object:
            if isinstance(value, dict):
                return {k: normalize(v, k) for k, v in sorted(value.items()) if k != "id"}
            if isinstance(value, list):
                return [normalize(v, key) for v in value]
            if isinstance(value, str):
                if key in {"role", "type", "name"}:
                    return value
                return "<text>"
            return value
        return json.dumps(normalize(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def _can_pin_instruction(cls, previous: object, current: object) -> bool:
        # v2.6 never substitutes an older instruction envelope. Provider continuity
        # should follow current Codex instructions; exact prefix stabilization remains.
        return False

    def _remember(self, key: str, items: list[object]) -> None:
        bucket = self.items_by_key.setdefault(key, deque(maxlen=self.MAX_CHECKPOINTS_PER_KEY))
        cloned = self._clone(items)
        if bucket and len(bucket[-1]) == len(cloned):
            # Avoid filling the ring with identical background replays.
            if all(
                _portable_item_signature(a) == _portable_item_signature(b)
                for a, b in zip(bucket[-1], cloned)
            ):
                return
        bucket.append(cloned)

    def stabilize(
        self, key: str, items: list[object]
    ) -> tuple[list[object], dict[str, int | bool | str]]:
        before_bytes = sum(_json_size(item) for item in items)
        meta: dict[str, int | bool | str] = {
            "checkpoint_hit": False,
            "checkpoint_prefix_items": 0,
            "checkpoint_prefix_bytes": 0,
            "checkpoint_before_bytes": before_bytes,
            "checkpoint_candidates": 0,
            "checkpoint_pinned_instruction_items": 0,
            "checkpoint_match_mode": "none",
        }
        if not key or not items:
            return items, meta

        with self.lock:
            candidates = list(self.items_by_key.get(key, ()))
            meta["checkpoint_candidates"] = len(candidates)
            if not candidates:
                self._remember(key, items)
                return items, meta

            best_items = items
            best_common = 0
            best_bytes = 0
            best_pinned = 0
            best_mode = "none"

            # First prefer a truly exact historical prefix from any recent replay.
            for previous in reversed(candidates):
                common, prefix_bytes = self._common_prefix(previous, items)
                if (prefix_bytes, common) > (best_bytes, best_common):
                    best_common = common
                    best_bytes = prefix_bytes
                    best_pinned = 0
                    best_mode = "exact" if common else "none"
                    best_items = self._clone(previous[:common]) + items[common:] if common else items

            # If the exact prefix is zero, a tiny volatile change in the leading
            # system/developer envelope can invalidate tens of thousands of cached
            # tokens. Pin only those leading instruction items when their structure
            # and size are nearly identical, then score the resulting exact prefix.
            if best_common == 0:
                for previous in reversed(candidates):
                    limit = min(len(previous), len(items))
                    pinned = 0
                    while pinned < limit and self._can_pin_instruction(previous[pinned], items[pinned]):
                        pinned += 1
                    if pinned == 0:
                        continue
                    candidate_items = self._clone(previous[:pinned]) + items[pinned:]
                    common, prefix_bytes = self._common_prefix(previous, candidate_items)
                    # Do not pin an instruction merely because its envelope looks
                    # similar. Require at least one *non-instruction* item after
                    # the pinned prefix to match exactly (normally the previous
                    # user turn). This avoids reusing an unrelated background
                    # Codex request that happens to have the same prompt shape.
                    if common <= pinned:
                        continue
                    if (prefix_bytes, common) > (best_bytes, best_common):
                        best_common = common
                        best_bytes = prefix_bytes
                        best_pinned = pinned
                        best_mode = "instruction-pinned"
                        best_items = candidate_items

            if best_common > 0:
                meta["checkpoint_hit"] = True
                meta["checkpoint_prefix_items"] = best_common
                meta["checkpoint_prefix_bytes"] = best_bytes
                meta["checkpoint_pinned_instruction_items"] = best_pinned
                meta["checkpoint_match_mode"] = best_mode

            # Keep the current/stabilized replay *and* older candidates. This is
            # the key v2.5.3 change: background full replays no longer destroy the
            # useful checkpoint from the user's previous turn on this model.
            self._remember(key, best_items)
            return best_items, meta



def _portableize_state_items(items: object) -> list[object]:
    """Return provider-neutral items suitable for continuation-prefix matching."""
    if not isinstance(items, list):
        return []
    portable: list[object] = []
    for original in items:
        if not isinstance(original, dict):
            portable.append(original)
            continue
        item = dict(original)
        item_type = item.get("type")
        if item_type in {"reasoning", "compaction", "item_reference"}:
            continue
        item.pop("id", None)
        item.pop("encrypted_content", None)
        portable.append(item)
    return portable


def _response_from_event(event: object) -> dict[str, object] | None:
    if not isinstance(event, dict):
        return None
    response = event.get("response")
    return response if isinstance(response, dict) else None


def _response_id_from_event(event: object) -> str | None:
    response = _response_from_event(event)
    if response is not None:
        value = response.get("id")
        if isinstance(value, str) and value:
            return value
    if isinstance(event, dict):
        value = event.get("response_id")
        if isinstance(value, str) and value:
            return value
    return None


def _portable_response_output(event: object) -> list[object]:
    response = _response_from_event(event)
    if response is None:
        return []
    return _portableize_state_items(response.get("output"))


def _is_response_completion_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    return str(event.get("type", "")).lower() in {
        "response.completed", "response.done", "response.complete"
    }


def _is_response_created_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    return str(event.get("type", "")).lower() == "response.created"


def is_previous_response_rejection_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    event_type = str(event.get("type", "")).lower()
    if event_type not in {"error", "response.failed", "response.error"}:
        return False
    text = json.dumps(event, ensure_ascii=False).lower()
    return (
        "previous_response_id" in text
        or "previous response" in text
        or "sticky routing" in text
        or "response not found" in text
    )


def is_previous_response_rejection_body(status: int, body: bytes) -> bool:
    if status != 400 or not body:
        return False
    lowered = body.lower()
    return any(
        marker in lowered
        for marker in (
            b"previous_response_id",
            b"previous response",
            b"sticky routing",
            b"response not found",
        )
    )


def is_store_parameter_rejection_event(event: object) -> bool:
    """Return True only for an explicit schema/capability rejection of ``store``."""
    if not isinstance(event, dict):
        return False
    event_type = str(event.get("type", "")).lower()
    text = json.dumps(event, ensure_ascii=False).lower()
    # ChatGPT Codex can surface this capability error in a wrapper event whose
    # outer type is not one of the usual error events. Recognize the explicit
    # message before applying the stricter event-type gate.
    if "store must be set to false" in text:
        return True
    if event_type not in {"error", "response.failed", "response.error"}:
        return False
    names_store = "store" in text
    return names_store and any(
        token in text
        for token in (
            "unsupported parameter",
            "unknown parameter",
            "invalid parameter",
            "not supported",
            "must be false",
        )
    )


def is_store_parameter_rejection_body(status: int, body: bytes) -> bool:
    if status not in {400, 422} or not body:
        return False
    lowered = body.lower()
    names_store = b"store" in lowered
    return names_store and any(
        marker in lowered
        for marker in (
            b"unsupported parameter",
            b"unknown parameter",
            b"invalid parameter",
            b"not supported",
            b"must be false",
            b"must be set to false",
        )
    )


def _provider_state_key(model: object, namespace: str) -> str:
    if not isinstance(model, str) or not model.strip():
        return ""
    model_key = model.strip().lower()
    route_key = (namespace or "route").strip().lower()
    return f"{route_key}|{model_key}"


def _codex_thread_scope(headers: object) -> tuple[str, str]:
    """Return a privacy-preserving Codex thread scope from request headers when available.

    Current Codex sends its logical thread id as ``x-client-request-id`` on Responses HTTP
    requests. Using that identity is substantially safer than keying provider cursors by the
    first user message alone. A subagent discriminator is folded into the hash when present.
    Older Codex builds that do not send the header fall back to the conversation fingerprint.
    """
    if headers is None or not hasattr(headers, "get"):
        return "", "fallback"
    try:
        thread_id = headers.get("x-client-request-id")
        subagent = headers.get("x-openai-subagent") or ""
    except Exception:
        return "", "fallback"
    if not isinstance(thread_id, str) or not thread_id.strip():
        return "", "fallback"
    digest = hashlib.sha256()
    digest.update(thread_id.strip().encode("utf-8", errors="ignore"))
    digest.update(b"\0")
    if isinstance(subagent, str):
        digest.update(subagent.strip().encode("utf-8", errors="ignore"))
    return digest.hexdigest()[:20], "x-client-request-id"


def _provider_shadow_state_key(
    model: object,
    namespace: str,
    items: object,
    *,
    request_scope: str = "",
) -> tuple[str, str]:
    """Return a conversation-scoped durable state key for third-party providers.

    Prefer Codex's logical thread identity (hashed) when available. The first-user
    conversation fingerprint is retained only as a compatibility fallback and for logs.
    Provider capability remains shared per model family.
    """
    base = _provider_state_key(model, namespace)
    fingerprint = _conversation_fingerprint(items) if base else ""
    if base and namespace == "third-party":
        if request_scope:
            return f"{base}|thread:{request_scope}", fingerprint
        if fingerprint:
            return f"{base}|conv:{fingerprint}", fingerprint
    return base, fingerprint


def _restart_instruction_pin_compatible(previous: object, current: object) -> bool:
    """Return True for a large Codex runtime envelope safe to pin on provider return.

    The caller has already established the strong guards that matter most:
      * same provider/model + conversation-scoped shadow key,
      * saved durable response cursor,
      * saved conversational timeline is a semantic prefix of the current replay,
      * leave -> other route -> return (route serial gap >= 2),
      * instruction sequence is append-compatible and roles are unchanged.

    v2.10.1 additionally required the nested JSON *shape* and high line similarity to remain
    nearly identical. Real Codex restarts rebuild tool/model/runtime blocks, so those guards
    rejected every one of the observed ~73 KB regenerated envelopes even though the durable
    conversation cursor had matched. Here we instead identify only large, runtime-looking
    envelopes. Small instructions and appended instruction slots are never relaxed by the
    caller, so genuine compact project/user policy changes still flow as fresh delta.
    """
    if _restart_instruction_equivalent(previous, current):
        return True
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    if previous.get("role") != current.get("role"):
        return False

    old_text = _normalize_restart_instruction_text(
        _instruction_text_for_restart_compare(previous)
    )
    new_text = _normalize_restart_instruction_text(
        _instruction_text_for_restart_compare(current)
    )
    if not old_text or not new_text:
        return False

    old_len = len(old_text)
    new_len = len(new_text)
    max_len = max(old_len, new_len)
    min_len = min(old_len, new_len)

    # Only large Codex bootstrap envelopes are eligible for relaxed pinning.
    # Small instructions are cheap and much more likely to be intentional policy edits.
    if max_len < 4096 or min_len / max_len < 0.45:
        return False

    def runtime_marker_score(value: str) -> int:
        lowered = value.lower()
        marker_groups = (
            ("codex", "coding agent", "openai"),
            ("tool", "function", "shell", "terminal"),
            ("sandbox", "workspace", "working directory", "cwd"),
            ("model", "provider", "cc switch", "model_catalog", "comp_hash"),
            ("git", "repository", "repo"),
        )
        return sum(1 for group in marker_groups if any(marker in lowered for marker in group))

    old_score = runtime_marker_score(old_text)
    new_score = runtime_marker_score(new_text)

    # If the restart-normalized text is still substantially similar, accept it even when
    # nested content-block metadata changed. SequenceMatcher works on lines to avoid a
    # quadratic character diff on 50-70 KB envelopes.
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    ratio = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).ratio()
    if ratio >= 0.45:
        return True

    # Large Codex runtime envelopes can have route/tool/catalog sections regenerated so
    # aggressively that line similarity falls below the threshold. Require several
    # independent runtime markers on both versions before pinning this case.
    return (
        max_len >= 8192
        and min_len / max_len >= 0.55
        and old_score >= 2
        and new_score >= 2
    )


class ProviderContinuationStore:
    """Provider-local durable conversation checkpoints.

    A checkpoint represents what one provider/model has *actually seen*: the complete
    portable input before a response plus that response's portable output.  For a later
    Codex full replay we compare only the conversational timeline (user/assistant/tool
    items) so volatile system/developer envelopes do not destroy the sync cursor.

    For third-party HTTP routes, correctness-first guards are stricter: any tool-bearing
    history, unverified completion, open tool chain, or instruction drift disables cursor
    reuse and falls back to the complete current portable replay. Pure-message stable
    conversations may still use durable ``store=true`` delta continuation. A schema
    rejection marks the provider unsupported for the remainder of the bridge process and
    clears its saved response ids.
    """

    MAX_STATES_PER_KEY = 24

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entries: dict[str, deque[dict[str, object]]] = {}
        self.capabilities: dict[str, str] = {}

    @staticmethod
    def _clone(items: list[object]) -> list[object]:
        return json.loads(json.dumps(items, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    def _prefix_bytes(items: list[object]) -> int:
        return sum(_json_size(item) for item in items)

    @staticmethod
    def _is_instruction(item: object) -> bool:
        return isinstance(item, dict) and item.get("role") in {"system", "developer"}

    @classmethod
    def _partition(cls, items: list[object]) -> tuple[list[object], list[object]]:
        instructions: list[object] = []
        timeline: list[object] = []
        for item in items:
            if cls._is_instruction(item):
                instructions.append(item)
            else:
                timeline.append(item)
        return instructions, timeline

    @staticmethod
    def _same_sequence(left: list[object], right: list[object]) -> bool:
        if len(left) != len(right):
            return False
        return all(
            _portable_item_signature(a) == _portable_item_signature(b)
            for a, b in zip(left, right)
        )

    @classmethod
    def _instruction_delta_indexes(
        cls, saved: list[object], current: list[object]
    ) -> set[int] | None:
        """Return current instruction indexes that need refreshing.

        A durable provider already owns the saved instruction envelope in its response
        state.  Resending *every* large Codex developer/system item merely because one
        volatile item changed defeats continuation and caused 40k-token switch spikes.

        We can safely append changed/new instruction messages when the instruction
        sequence has the same role layout (or only grows at the end).  A deletion or
        role reorder cannot be represented as an append-only delta, so return None and
        let the caller preserve correctness with a full replay.
        """
        if len(current) < len(saved):
            return None
        changed: set[int] = set()
        for index, previous in enumerate(saved):
            now = current[index]
            prev_role = previous.get("role") if isinstance(previous, dict) else None
            cur_role = now.get("role") if isinstance(now, dict) else None
            if prev_role != cur_role:
                return None
            # Compare the semantic message envelope, not raw provider wire
            # metadata.  Nested item ids/status/annotations can change on every
            # Codex restart without changing the actual instruction text.
            if not _restart_instruction_equivalent(previous, now):
                changed.add(index)
        for index in range(len(saved), len(current)):
            changed.add(index)
        return changed

    @staticmethod
    def _timeline_is_prefix(covered: list[object], current: list[object]) -> bool:
        if len(covered) > len(current):
            return False
        return all(
            _semantic_timeline_signature(previous)
            == _semantic_timeline_signature(current[index])
            for index, previous in enumerate(covered)
        )

    @staticmethod
    def _capability_key(key: str) -> str:
        # Conversation/thread-scoped shadow cursors share one capability probe per
        # provider/model family.
        if not key:
            return ""
        for marker in ("|thread:", "|conv:"):
            if marker in key:
                return key.split(marker, 1)[0]
        return key

    def capability_state(self, key: str) -> str:
        capability_key = self._capability_key(key)
        if not capability_key:
            return "disabled"
        with self.lock:
            return self.capabilities.get(capability_key, "unknown")

    def should_request_durable(self, key: str) -> bool:
        return bool(key) and self.capability_state(key) != "unsupported"

    def mark_supported(self, key: str) -> None:
        capability_key = self._capability_key(key)
        if not capability_key:
            return
        with self.lock:
            self.capabilities[capability_key] = "supported"

    def mark_unsupported(self, key: str) -> None:
        capability_key = self._capability_key(key)
        if not capability_key:
            return
        with self.lock:
            self.capabilities[capability_key] = "unsupported"
            stale_keys = [entry_key for entry_key in self.entries if self._capability_key(entry_key) == capability_key]
            for entry_key in stale_keys:
                self.entries.pop(entry_key, None)

    def candidate(
        self,
        key: str,
        current_items: list[object],
        *,
        ignore_instruction_refresh: bool = False,
        current_route_serial: int = 0,
        allow_provider_return_instruction_pin: bool = False,
        diagnostics: dict[str, object] | None = None,
    ) -> tuple[str, list[object], int, int, int, int, bool] | None:
        """Return the longest *provably safe* provider sync cursor.

        v2.12 correctness rule: a cross-provider return is optimized only for a pure-message
        conversation whose prior provider completion was verified and whose instruction
        envelope is unchanged. Tool-bearing histories, open tool chains, or instruction
        drift fall back to a complete portable replay. The fallback costs tokens but cannot
        resurrect stale hidden agent/tool state.
        """
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update({
                "matched": False,
                "reason": "disabled-or-empty",
                "provider_return": False,
                "tool_history": _timeline_contains_tool_state(current_items),
                "tool_chain_closed": _tool_chain_closed(current_items),
                "instruction_drift": False,
                "completion_verified": False,
            })
        if not key or not current_items or not self.should_request_durable(key):
            return None

        current_instructions, current_timeline = self._partition(current_items)
        current_has_tools = _timeline_contains_tool_state(current_timeline)
        current_tool_chain_closed = _tool_chain_closed(current_timeline)

        with self.lock:
            bucket = list(self.entries.get(key, ()))
            if not bucket:
                if diagnostics is not None:
                    diagnostics["reason"] = "no-checkpoint"
                return None

            best: tuple[str, list[object], int, int, int, int, bool] | None = None
            best_reason = "no-compatible-checkpoint"
            for entry in reversed(bucket):
                response_id = entry.get("response_id")
                saved_instructions = entry.get("instruction_items")
                saved_timeline = entry.get("timeline_items")
                if (
                    not isinstance(response_id, str)
                    or not response_id
                    or not isinstance(saved_instructions, list)
                    or not isinstance(saved_timeline, list)
                ):
                    best_reason = "invalid-checkpoint"
                    continue
                if not self._timeline_is_prefix(saved_timeline, current_timeline):
                    best_reason = "timeline-prefix-mismatch"
                    continue

                saved_route_serial = entry.get("route_serial")
                provider_return = bool(
                    allow_provider_return_instruction_pin
                    and isinstance(saved_route_serial, int)
                    and current_route_serial >= saved_route_serial + 2
                )
                completion_verified = bool(entry.get("completion_verified"))
                saved_has_tools = bool(entry.get("tool_history"))
                saved_tool_chain_closed = bool(entry.get("tool_chain_closed", True))

                if diagnostics is not None:
                    diagnostics["provider_return"] = provider_return
                    diagnostics["completion_verified"] = completion_verified

                # Third-party durable state is reused only from a definitely completed
                # response. Older/partial/empty checkpoints are too weak to prove that the
                # server-side state belongs to this visible conversation.
                strict_third_party = bool(allow_provider_return_instruction_pin)
                if strict_third_party and not completion_verified:
                    best_reason = "unverified-completion"
                    continue

                # Never attach hidden third-party provider state to a tool-bearing Codex
                # task, even without a route change. Tool calls can carry opaque execution
                # state beyond the visible call_id/output pair. Full portable replay keeps
                # the visible transcript authoritative and prevents stale agent state from
                # hijacking a long-running task.
                if strict_third_party and (saved_has_tools or current_has_tools):
                    best_reason = "tool-history-full-replay"
                    continue
                if strict_third_party and (not saved_tool_chain_closed or not current_tool_chain_closed):
                    best_reason = "open-tool-chain"
                    continue

                changed_instruction_indexes = self._instruction_delta_indexes(
                    saved_instructions, current_instructions
                )
                if changed_instruction_indexes is None:
                    best_reason = "instruction-layout-changed"
                    if diagnostics is not None:
                        diagnostics["instruction_drift"] = True
                    continue

                # Critical v2.12 safety change: for third-party durable state, any existing
                # or newly appended instruction change invalidates delta reuse. Appending a
                # regenerated developer envelope on top of stale server-side instructions
                # can silently change the active task/workspace. Replaying the current full
                # envelope is the only correctness-preserving representation.
                if strict_third_party and changed_instruction_indexes:
                    best_reason = "instruction-drift-full-replay"
                    if diagnostics is not None:
                        diagnostics["instruction_drift"] = True
                    continue

                # Official resident re-attachment uses a different proof: the exact live
                # upstream socket owns the old instruction state. Preserve that existing
                # behavior; this flag is not used for third-party provider returns.
                if ignore_instruction_refresh:
                    changed_instruction_indexes = set()

                # An identical state is not a useful continuation candidate.
                if len(saved_timeline) == len(current_timeline) and not changed_instruction_indexes:
                    best_reason = "no-unseen-delta"
                    continue

                timeline_seen = 0
                instruction_seen = 0
                suffix: list[object] = []
                instruction_delta_items = 0
                instruction_delta_bytes = 0
                for item in current_items:
                    if self._is_instruction(item):
                        if instruction_seen in changed_instruction_indexes:
                            suffix.append(item)
                            instruction_delta_items += 1
                            instruction_delta_bytes += _json_size(item)
                        instruction_seen += 1
                        continue
                    if timeline_seen < len(saved_timeline):
                        timeline_seen += 1
                        continue
                    suffix.append(item)
                    timeline_seen += 1

                prefix_bytes = self._prefix_bytes(saved_timeline)
                candidate = (
                    response_id,
                    self._clone(suffix),
                    len(saved_timeline),
                    prefix_bytes,
                    instruction_delta_items,
                    instruction_delta_bytes,
                    bool(ignore_instruction_refresh),
                )
                if best is None or (candidate[3], candidate[2]) > (best[3], best[2]):
                    best = candidate
                    best_reason = "matched"

            if diagnostics is not None:
                diagnostics["matched"] = best is not None
                diagnostics["reason"] = best_reason
            return best

    def extend_from_previous(
        self, key: str, previous_response_id: object, delta_items: object
    ) -> list[object] | None:
        if not key or not isinstance(previous_response_id, str):
            return None
        portable_delta = _portableize_state_items(delta_items)
        with self.lock:
            for entry in reversed(self.entries.get(key, ())):
                if entry.get("response_id") != previous_response_id:
                    continue
                covered = entry.get("covered_items")
                if isinstance(covered, list):
                    return self._clone(covered) + portable_delta
            return None

    def commit(
        self,
        key: str,
        response_id: str,
        covered_items: list[object],
        *,
        durable: bool,
        route_serial: int = 0,
        completion_verified: bool = False,
    ) -> None:
        if not durable or not key or not response_id or not covered_items:
            return
        if not self.should_request_durable(key):
            return
        cloned = self._clone(covered_items)
        instructions, timeline = self._partition(cloned)
        capability_key = self._capability_key(key)
        with self.lock:
            if self.capabilities.get(capability_key) == "unsupported":
                return
            self.capabilities[capability_key] = "supported"
            bucket = self.entries.setdefault(key, deque(maxlen=self.MAX_STATES_PER_KEY))
            record = {
                "response_id": response_id,
                "covered_items": cloned,
                "instruction_items": instructions,
                "timeline_items": timeline,
                "route_serial": int(route_serial),
                "completion_verified": bool(completion_verified),
                "tool_history": _timeline_contains_tool_state(timeline),
                "tool_chain_closed": _tool_chain_closed(timeline),
            }
            for index, entry in enumerate(bucket):
                if entry.get("response_id") == response_id:
                    bucket[index] = record
                    return
            bucket.append(record)

    def invalidate(self, key: str, response_id: str | None = None) -> None:
        if not key:
            return
        with self.lock:
            bucket = self.entries.get(key)
            if not bucket:
                return
            if response_id is None:
                self.entries.pop(key, None)
                return
            kept = [entry for entry in bucket if entry.get("response_id") != response_id]
            if kept:
                self.entries[key] = deque(kept, maxlen=self.MAX_STATES_PER_KEY)
            else:
                self.entries.pop(key, None)


class LiveProviderContinuationStore(ProviderContinuationStore):
    """Socket-scoped continuation state for Official ``store=false`` sessions.

    The response id is reusable only while the exact upstream Responses WebSocket stays
    alive.  This store is therefore owned by one persistent Official socket and is never
    shared with a replacement socket.
    """

    def capability_state(self, key: str) -> str:
        return "live" if key else "disabled"

    def should_request_durable(self, key: str) -> bool:
        return bool(key)

    def mark_supported(self, key: str) -> None:
        return

    def mark_unsupported(self, key: str) -> None:
        if key:
            self.invalidate(key)

    def commit(
        self,
        key: str,
        response_id: str,
        covered_items: list[object],
        *,
        durable: bool,
        route_serial: int = 0,
        completion_verified: bool = False,
    ) -> None:
        if not key or not response_id or not covered_items:
            return
        cloned = self._clone(covered_items)
        instructions, timeline = self._partition(cloned)
        with self.lock:
            bucket = self.entries.setdefault(key, deque(maxlen=self.MAX_STATES_PER_KEY))
            record = {
                "response_id": response_id,
                "covered_items": cloned,
                "instruction_items": instructions,
                "timeline_items": timeline,
                "route_serial": int(route_serial),
                "completion_verified": bool(completion_verified),
                "tool_history": _timeline_contains_tool_state(timeline),
                "tool_chain_closed": _tool_chain_closed(timeline),
            }
            for index, entry in enumerate(bucket):
                if entry.get("response_id") == response_id:
                    bucket[index] = record
                    return
            bucket.append(record)


class ContinuationRequestTracker:
    """Associate outgoing durable response.create requests with completions."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending: deque[dict[str, object]] = deque()
        self.active: dict[str, dict[str, object]] = {}

    def note(self, plan: object) -> None:
        if not isinstance(plan, dict):
            return
        key = plan.get("key")
        canonical = plan.get("canonical_before")
        durable = bool(plan.get("durable"))
        live = bool(plan.get("live"))
        if not (durable or live) or not isinstance(key, str) or not key or not isinstance(canonical, list):
            return
        with self.lock:
            self.pending.append(
                {
                    "key": key,
                    "canonical_before": canonical,
                    "durable": durable,
                    "live": live,
                }
            )

    def handle_event(
        self,
        event: object,
        store: ProviderContinuationStore,
        live_store: LiveProviderContinuationStore | None = None,
    ) -> None:
        response_id = _response_id_from_event(event)
        if _is_response_created_event(event) and response_id:
            with self.lock:
                if self.pending:
                    self.active[response_id] = self.pending.popleft()
            return
        if _is_response_completion_event(event) and response_id:
            with self.lock:
                plan = self.active.pop(response_id, None)
                if plan is None and self.pending:
                    plan = self.pending.popleft()
            if not plan:
                return
            output = _portable_response_output(event)
            canonical = plan["canonical_before"]
            if not isinstance(canonical, list):
                return
            if bool(plan.get("live")) and live_store is not None:
                live_store.commit(
                    str(plan["key"]),
                    response_id,
                    canonical + output,
                    durable=False,
                    completion_verified=True,
                )
            if bool(plan.get("durable")) and _has_meaningful_provider_output(output):
                store.commit(
                    str(plan["key"]),
                    response_id,
                    canonical + output,
                    durable=True,
                    completion_verified=True,
                )


class HttpContinuationCollector:
    """Observe JSON/SSE output and commit only durable provider state."""

    MAX_BUFFER = 8 * 1024 * 1024

    def __init__(
        self,
        key: str,
        canonical_before: list[object],
        store: ProviderContinuationStore,
        *,
        durable: bool,
        route_serial: int = 0,
    ) -> None:
        self.key = key
        self.canonical_before = canonical_before
        self.store = store
        self.durable = durable
        self.route_serial = int(route_serial)
        self.buffer = bytearray()
        self.line_buffer = bytearray()
        self.committed = False
        self.last_response_id = ""

    def _consume_event(self, event: object) -> None:
        if self.committed or not self.durable or not _is_response_completion_event(event):
            return
        response_id = _response_id_from_event(event)
        if not response_id:
            return
        output = _portable_response_output(event)
        if not _has_meaningful_provider_output(output):
            # Never create a durable cursor from an empty/reasoning-only completion.
            # Such a cursor proves too little and can collide with background requests.
            return
        self.last_response_id = response_id
        self.store.commit(
            self.key,
            response_id,
            self.canonical_before + output,
            durable=True,
            route_serial=self.route_serial,
            completion_verified=True,
        )
        self.committed = True

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(self.buffer) < self.MAX_BUFFER:
            remaining = self.MAX_BUFFER - len(self.buffer)
            self.buffer.extend(chunk[:remaining])
        self.line_buffer.extend(chunk)
        while b"\n" in self.line_buffer:
            raw_line, _, rest = self.line_buffer.partition(b"\n")
            self.line_buffer = bytearray(rest)
            line = raw_line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                self._consume_event(json.loads(data.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

    def finish(self) -> None:
        if self.committed or not self.durable or not self.buffer:
            return
        try:
            payload = json.loads(bytes(self.buffer).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            event = {"type": "response.completed", "response": payload}
            self._consume_event(event)
            return
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            response = payload.get("response")
            if isinstance(response.get("id"), str):
                event = {"type": "response.completed", "response": response}
                self._consume_event(event)

def _looks_official_model(model: object) -> bool:
    if not isinstance(model, str) or not model.strip():
        return False
    return bool(re.match(r"(?i)^(gpt-|o[0-9]|codex)", model.strip()))


def _looks_internal_official_model(model: object) -> bool:
    """Return True for Codex-owned background models that must never follow CC Switch.

    Terra is currently emitted by Codex for internal/background work.  Keep this list
    intentionally narrow: unknown GPT models with actual conversation input are treated
    as user-facing and may follow the hot-switch route.
    """
    if not isinstance(model, str):
        return False
    value = model.strip().lower()
    return value.startswith("gpt-") and ("terra" in value)


def _payload_has_conversation_work(payload: object) -> bool:
    """Conservatively identify a user/session Responses request.

    A hot-switch rewrite is allowed only when the request contains a conversational
    item (user/assistant/tool) or an explicit previous_response_id. Pure system/developer
    startup probes stay on their original Official model.
    """
    if not isinstance(payload, dict):
        return False
    previous = payload.get("previous_response_id")
    if isinstance(previous, str) and previous:
        return True
    items = payload.get("input")
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        item_type = item.get("type")
        if role in {"user", "assistant"}:
            return True
        if item_type in TOOL_CALL_TYPES | TOOL_OUTPUT_TYPES | {
            "computer_call", "computer_call_output", "custom_tool_call",
            "custom_tool_call_output", "web_search_call",
        }:
            return True
    return False


class HotSwitchRouteState:
    """Route user requests without taking model selection away from Codex.

    The CatalogConfigGuard owns provider routing state. Codex owns the concrete model
    and reasoning-effort selection from the unified catalog. A stale model is rebound
    only immediately after a provider switch; a concrete model that belongs to the
    current route is preserved verbatim.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_official_user_model = ""

    def rewrite(
        self,
        payload: object,
        route_model: str,
        route_official: bool,
        route_models: set[str] | None = None,
    ) -> tuple[object, str | None, bool, str]:
        if not isinstance(payload, dict):
            return payload, None, False, "not-json-object"
        original = payload.get("model")
        original_model = original if isinstance(original, str) else None
        route_model = route_model.strip() if isinstance(route_model, str) else ""
        allowed = set(route_models or ())

        if not original_model or not _payload_has_conversation_work(payload):
            return payload, original_model, False, "non-conversation"
        if _looks_internal_official_model(original_model):
            return payload, original_model, False, "internal-official"

        if route_official:
            if _looks_official_model(original_model):
                with self.lock:
                    self.last_official_user_model = original_model
                return payload, original_model, False, "official-selected-model"
            with self.lock:
                target = self.last_official_user_model
            if not target and _looks_official_model(route_model):
                target = route_model
            if not target:
                return payload, original_model, False, "official-route-model-unknown"
            rewritten = dict(payload)
            rewritten["model"] = target
            return rewritten, original_model, True, "stale-third-party-model-returning-official"

        # Third-party route. If Codex selected a concrete model exposed by the
        # current provider catalog, preserve it exactly so model-specific reasoning
        # effort/capabilities remain under the user's control.
        if not _looks_official_model(original_model):
            if not allowed or original_model in allowed:
                return payload, original_model, False, "third-party-selected-model"
            # The picker may still contain models learned from another provider.
            # Never send that model to the wrong route: rebound to this route's
            # default model exactly once instead of trying another upstream.
            if route_model and not _looks_official_model(route_model):
                rewritten = dict(payload)
                rewritten["model"] = route_model
                return rewritten, original_model, True, "third-party-route-model-mismatch"
            return payload, original_model, False, "third-party-route-model-unknown"

        # Stale Official model immediately after CC Switch moved to a third-party
        # route. This preserves restart-free switching even before the model picker
        # refreshes; once the user selects a provider model, the exact selection wins.
        if route_model and not _looks_official_model(route_model):
            rewritten = dict(payload)
            rewritten["model"] = route_model
            return rewritten, original_model, True, "stale-official-model-switching-third-party"
        return payload, original_model, False, "third-party-route-model-unknown"


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _is_gpt_56_model(model: object) -> bool:
    return isinstance(model, str) and model.lower().startswith("gpt-5.6")


def apply_stable_prompt_cache_breakpoints(
    payload: object,
    *,
    enabled: bool,
) -> tuple[object, int, int, bool]:
    """Add deterministic GPT-5.6 explicit cache boundaries to a full replay.

    GPT-5.6 allows explicit ``prompt_cache_breakpoint`` markers on content blocks.
    We deliberately do *not* mark the latest N messages: those positions move as
    history grows and can make an append-only prefix structurally unstable.

    Instead, cumulative serialized input size is tracked from the beginning of the
    canonical history.  The first eligible ``input_text`` block at or after each
    fixed checkpoint receives a marker.  If a later replay only appends history,
    the earlier markers therefore remain on the same blocks.

    The bridge does not send request-level ``prompt_cache_options``. The public
    Responses API supports that field, but the ChatGPT Codex backend can expose a
    narrower schema. Leaving the option absent preserves the backend's default
    implicit-cache behavior while explicit content-block markers are attempted.
    Existing caller-supplied breakpoints are preserved.
    """
    if not enabled or not isinstance(payload, dict):
        return payload, 0, 0, False
    if not _is_gpt_56_model(payload.get("model")):
        return payload, 0, 0, False
    items = payload.get("input")
    if not isinstance(items, list) or not _is_full_replay_input(items):
        return payload, 0, 0, False

    rewritten = dict(payload)
    rewritten_items: list[object] = []
    cumulative = 0
    next_checkpoint = 0
    added = 0
    existing = 0
    eligible = 0

    # Count existing explicit markers first so we never exceed the request budget.
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and "prompt_cache_breakpoint" in block:
                existing += 1

    # Keep one slot available for the backend's native implicit breakpoint.
    # We intentionally avoid request-level prompt_cache_options because the
    # ChatGPT Codex backend may reject that public-API field.
    explicit_budget = 3
    remaining = max(0, explicit_budget - existing)

    for item in items:
        item_size = _json_size(item)
        cumulative += item_size
        new_item = item
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, list):
                markable = [
                    idx for idx, block in enumerate(content)
                    if isinstance(block, dict)
                    and block.get("type") == "input_text"
                    and "prompt_cache_breakpoint" not in block
                ]
                eligible += len(markable)
                while (
                    remaining > 0
                    and next_checkpoint < len(PROMPT_CACHE_CHECKPOINT_BYTES)
                    and cumulative >= PROMPT_CACHE_CHECKPOINT_BYTES[next_checkpoint]
                ):
                    if not markable:
                        break
                    # One boundary per content block. If several thresholds are
                    # crossed by one large item, consume only one here; later
                    # thresholds remain pending for a later eligible block.
                    block_index = markable[-1]
                    new_item = dict(item)
                    new_content = list(content)
                    new_block = dict(new_content[block_index])
                    new_block["prompt_cache_breakpoint"] = {"mode": "explicit"}
                    new_content[block_index] = new_block
                    new_item["content"] = new_content
                    content = new_content
                    markable = []
                    added += 1
                    remaining -= 1
                    next_checkpoint += 1
                    break
        rewritten_items.append(new_item)

    if added == 0:
        return payload, 0, eligible, False

    rewritten["input"] = rewritten_items
    return rewritten, added, eligible, False


def _contains_prompt_cache_parameter_name(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return ("prompt_cache_breakpoint" in lowered or "prompt_cache_options" in lowered or "prompt_cache_key" in lowered or "prompt_cache_retention" in lowered)
    if isinstance(value, dict):
        return any(_contains_prompt_cache_parameter_name(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_prompt_cache_parameter_name(v) for v in value)
    return False


def is_prompt_cache_parameter_rejection_event(event: object) -> bool:
    """Recognize backend schema rejection for v2.5 cache-control fields."""
    if not isinstance(event, dict):
        return False
    event_type = str(event.get("type", "")).lower()
    if event_type not in {"error", "response.failed", "response.error"}:
        # Some Responses implementations wrap failures differently. Only accept
        # a non-standard shape if it explicitly names one of our cache fields.
        return _contains_prompt_cache_parameter_name(event) and any(
            marker in json.dumps(event, ensure_ascii=False).lower()
            for marker in ("unsupported parameter", "unknown parameter", "invalid parameter")
        )
    text = json.dumps(event, ensure_ascii=False).lower()
    return _contains_prompt_cache_parameter_name(event) and any(
        marker in text
        for marker in ("unsupported parameter", "unknown parameter", "invalid parameter", "not supported")
    )


def is_prompt_cache_parameter_rejection_body(status: int, body: bytes) -> bool:
    if status != 400 or not body:
        return False
    lowered = body.lower()
    names_field = (b"prompt_cache_breakpoint" in lowered or b"prompt_cache_options" in lowered or b"prompt_cache_key" in lowered or b"prompt_cache_retention" in lowered)
    return names_field and any(
        marker in lowered
        for marker in (b"unsupported parameter", b"unknown parameter", b"invalid parameter", b"not supported")
    )


def prepare_ws_response_create(
    payload: object,
    state: WebSocketContinuationState,
    model_override: str,
    prompt_cache_optimization: bool = False,
    switch_replay_compaction: bool = False,
    switch_replay_threshold_bytes: int = SWITCH_REPLAY_DEFAULT_THRESHOLD_BYTES,
    switch_replay_recent_user_turns: int = SWITCH_REPLAY_DEFAULT_RECENT_USER_TURNS,
    force_official_model_override: bool = True,
    checkpoint_store: ReplayPrefixCheckpointStore | None = None,
    continuation_store: ProviderContinuationStore | None = None,
    provider_continuation_enabled: bool = True,
    continuation_namespace: str = "route",
    live_continuation_store: LiveProviderContinuationStore | None = None,
    prompt_cache_key_enabled: bool = False,
    pin_live_restart_instructions: bool = False,
) -> tuple[object, dict[str, object]]:
    """Prepare a Responses-over-WebSocket request without replay-pruning by default.

    Same-turn ``previous_response_id`` requests remain native incremental requests.  A
    provider/model that supports durable response state is also asked to persist each
    accepted response (``store=true``).  When a later full canonical replay extends a
    saved provider timeline, only the not-yet-synchronized timeline suffix is sent with
    that provider's saved response id.  Changed current system/developer instructions
    are included in the catch-up delta instead of being silently pinned to an old copy.
    """
    meta: dict[str, object] = {
        "mode": "passthrough",
        "removed_item_ids": 0,
        "removed_previous_response_id": False,
        "cleared_reasoning_content": 0,
        "removed_encrypted_content": 0,
        "omitted_reasoning_items": 0,
        "omitted_compaction_items": 0,
        "omitted_item_references": 0,
        "model_rewritten": False,
        "original_model": None,
        "client_input_items": 0,
        "upstream_input_items": 0,
        "previous_response_id_state": "none",
        "prompt_cache_breakpoints_added": 0,
        "prompt_cache_eligible_blocks": 0,
        "prompt_cache_options_added": False,
        "prompt_cache_key_added": False,
        "switch_compaction_applied": False,
        "switch_replay_bytes_before": 0,
        "switch_replay_bytes_after": 0,
        "deduped_instruction_items": 0,
        "omitted_stale_tool_items": 0,
        "checkpoint_hit": False,
        "checkpoint_prefix_items": 0,
        "checkpoint_prefix_bytes": 0,
        "checkpoint_candidates": 0,
        "checkpoint_pinned_instruction_items": 0,
        "checkpoint_match_mode": "none",
        "checkpoint_key": "-",
        "cross_switch_continuation": False,
        "continuation_prefix_items": 0,
        "continuation_prefix_bytes": 0,
        "continuation_delta_items": 0,
        "continuation_delta_bytes": 0,
        "continuation_instruction_items": 0,
        "continuation_instruction_bytes": 0,
        "provider_state_key": "-",
        "provider_state_capability": "disabled",
        "durable_store_requested": False,
        "live_session_continuation": False,
        "restart_instruction_pin": False,
    }
    if not isinstance(payload, dict) or payload.get("type") != "response.create":
        return payload, meta

    rewritten = dict(payload)
    original_model = rewritten.get("model")
    meta["original_model"] = original_model if isinstance(original_model, str) else None
    if (
        force_official_model_override
        and model_override
        and isinstance(original_model, str)
        and original_model != model_override
        and not _looks_official_model(original_model)
    ):
        rewritten["model"] = model_override
        meta["model_rewritten"] = True

    items = rewritten.get("input")
    if isinstance(items, list):
        meta["client_input_items"] = len(items)
        meta["upstream_input_items"] = len(items)

    # Route config can switch to GLM while Codex still emits an internal GPT
    # background request.  Classify state by the actual payload model first so
    # Official-looking models never probe third-party durable store=true.
    effective_namespace = (
        "official"
        if continuation_namespace == "official" or _looks_official_model(rewritten.get("model"))
        else continuation_namespace
    )
    continuation_key = _provider_state_key(
        rewritten.get("model"), effective_namespace
    )
    meta["provider_state_key"] = continuation_key or "-"
    if continuation_store is not None and continuation_key and provider_continuation_enabled:
        meta["provider_state_capability"] = continuation_store.capability_state(
            continuation_key
        )

    previous_response_id = rewritten.get("previous_response_id")
    with state.lock:
        state.response_create_count += 1
        trusted_previous = (
            isinstance(previous_response_id, str)
            and previous_response_id in state.known_response_ids
        )

    if trusted_previous:
        meta["mode"] = "native-incremental"
        meta["previous_response_id_state"] = "trusted-live"
        with state.lock:
            state.native_incremental_count += 1

        # Official store=false continuation can still be tracked when the exact
        # upstream WebSocket is kept alive across provider switches.
        if (
            provider_continuation_enabled
            and live_continuation_store is not None
            and continuation_key
        ):
            canonical = live_continuation_store.extend_from_previous(
                continuation_key, previous_response_id, items
            )
            if canonical is not None:
                meta["_continuation_plan"] = {
                    "key": continuation_key,
                    "canonical_before": canonical,
                    "durable": False,
                    "live": True,
                }
                meta["live_session_continuation"] = True

        durable_allowed = bool(
            provider_continuation_enabled
            and effective_namespace != "official"
            and not _looks_official_model(rewritten.get("model"))
            and continuation_store is not None
            and continuation_key
            and continuation_store.should_request_durable(continuation_key)
        )
        if durable_allowed:
            stateless_fallback = dict(rewritten)
            stateless_fallback["store"] = False
            rewritten = dict(rewritten)
            rewritten["store"] = True
            meta["durable_store_requested"] = True
            meta["_durable_store_fallback_payload"] = stateless_fallback
            meta["_durable_store_key"] = continuation_key
            canonical = continuation_store.extend_from_previous(
                continuation_key, previous_response_id, items
            )
            if canonical is not None:
                meta["_continuation_plan"] = {
                    "key": continuation_key,
                    "canonical_before": canonical,
                    "durable": True,
                    "live": False,
                }
        return rewritten, meta

    # Preserve native Codex recovery for a tiny delta that references an unknown id.
    if previous_response_id is not None and not _is_full_replay_input(items):
        meta["mode"] = "unknown-previous-passthrough"
        meta["previous_response_id_state"] = "unknown"
        return rewritten, meta

    meta["mode"] = "native-full-replay"
    if previous_response_id is not None:
        meta["previous_response_id_state"] = "stale-or-cross-provider"
    with state.lock:
        state.full_replay_count += 1

    if previous_response_id is not None:
        rewritten.pop("previous_response_id", None)
        meta["removed_previous_response_id"] = True

    if isinstance(items, list):
        cleaned_items: list[object] = []
        for original in items:
            if not isinstance(original, dict):
                cleaned_items.append(original)
                continue

            item = dict(original)
            item_type = item.get("type")
            original_id = item.get("id")
            trusted_item = state.item_is_known(original_id)

            if item_type == "item_reference" and not trusted_item:
                meta["omitted_item_references"] = int(meta["omitted_item_references"]) + 1
                continue
            if item_type == "reasoning" and not trusted_item:
                meta["omitted_reasoning_items"] = int(meta["omitted_reasoning_items"]) + 1
                if "encrypted_content" in item:
                    meta["removed_encrypted_content"] = int(meta["removed_encrypted_content"]) + 1
                continue
            if item_type == "compaction" and not trusted_item:
                meta["omitted_compaction_items"] = int(meta["omitted_compaction_items"]) + 1
                if "encrypted_content" in item:
                    meta["removed_encrypted_content"] = int(meta["removed_encrypted_content"]) + 1
                continue
            if "id" in item and not trusted_item:
                item.pop("id", None)
                meta["removed_item_ids"] = int(meta["removed_item_ids"]) + 1
            cleaned_items.append(item)

        # v2.6 correctness default: no history pruning. The old conservative
        # compactor remains opt-in for users who explicitly want it.
        if switch_replay_compaction:
            cleaned_items, compact_meta = compact_switch_replay_items(
                cleaned_items,
                threshold_bytes=switch_replay_threshold_bytes,
                recent_user_turns=switch_replay_recent_user_turns,
            )
            meta["switch_compaction_applied"] = bool(compact_meta["applied"])
            meta["switch_replay_bytes_before"] = int(compact_meta["before_bytes"])
            meta["switch_replay_bytes_after"] = int(compact_meta["after_bytes"])
            meta["deduped_instruction_items"] = int(compact_meta["deduped_instruction_items"])
            meta["omitted_stale_tool_items"] = int(compact_meta["omitted_stale_tool_items"])
        else:
            replay_bytes = sum(_json_size(item) for item in cleaned_items)
            meta["switch_replay_bytes_before"] = replay_bytes
            meta["switch_replay_bytes_after"] = replay_bytes

        checkpoint_key = (
            rewritten.get("model").strip().lower()
            if isinstance(rewritten.get("model"), str)
            else ""
        )
        if checkpoint_store is not None and checkpoint_key:
            cleaned_items, checkpoint_meta = checkpoint_store.stabilize(
                checkpoint_key, cleaned_items
            )
            meta["checkpoint_key"] = checkpoint_key
            meta["checkpoint_hit"] = bool(checkpoint_meta["checkpoint_hit"])
            meta["checkpoint_prefix_items"] = int(checkpoint_meta["checkpoint_prefix_items"])
            meta["checkpoint_prefix_bytes"] = int(checkpoint_meta["checkpoint_prefix_bytes"])
            meta["checkpoint_candidates"] = int(checkpoint_meta.get("checkpoint_candidates", 0))
            # v2.6 exact-only checkpoint stabilization never pins old instructions.
            meta["checkpoint_pinned_instruction_items"] = 0
            meta["checkpoint_match_mode"] = str(checkpoint_meta.get("checkpoint_match_mode", "none"))

        canonical_items = _portableize_state_items(cleaned_items)
        stateless_full_payload = dict(rewritten)
        stateless_full_payload["input"] = cleaned_items
        stateless_full_payload["store"] = False

        # First prefer a socket-scoped Official continuation when this handler is
        # attached to the same persistent upstream WS that produced the response id.
        live_candidate = None
        if (
            provider_continuation_enabled
            and live_continuation_store is not None
            and continuation_key
        ):
            live_candidate = live_continuation_store.candidate(
                continuation_key,
                canonical_items,
                ignore_instruction_refresh=pin_live_restart_instructions,
            )
            meta["provider_state_capability"] = "live"
            meta["_continuation_plan"] = {
                "key": continuation_key,
                "canonical_before": canonical_items,
                "durable": False,
                "live": True,
            }

        if live_candidate is not None:
            (
                saved_response_id,
                suffix,
                prefix_items,
                prefix_bytes,
                instruction_items,
                instruction_bytes,
                candidate_instruction_pin,
            ) = live_candidate
            rewritten = dict(stateless_full_payload)
            rewritten["input"] = suffix
            rewritten["previous_response_id"] = saved_response_id
            rewritten["store"] = False
            meta["mode"] = "cross-switch-live-incremental"
            meta["previous_response_id_state"] = "saved-live-session-state"
            meta["cross_switch_continuation"] = True
            meta["live_session_continuation"] = True
            meta["restart_instruction_pin"] = bool(candidate_instruction_pin)
            meta["continuation_prefix_items"] = prefix_items
            meta["continuation_prefix_bytes"] = prefix_bytes
            meta["continuation_delta_items"] = len(suffix)
            meta["continuation_delta_bytes"] = sum(_json_size(item) for item in suffix)
            meta["continuation_instruction_items"] = instruction_items
            meta["continuation_instruction_bytes"] = instruction_bytes
            meta["upstream_input_items"] = len(suffix)
            meta["_cross_switch_fallback_payload"] = stateless_full_payload
            meta["_continuation_response_id"] = saved_response_id
            meta["_continuation_scope"] = "live"
        else:
            durable_allowed = bool(
                provider_continuation_enabled
                and effective_namespace != "official"
                and not _looks_official_model(rewritten.get("model"))
                and continuation_store is not None
                and continuation_key
                and continuation_store.should_request_durable(continuation_key)
            )

            if durable_allowed:
                durable_full_payload = dict(stateless_full_payload)
                durable_full_payload["store"] = True
                rewritten = durable_full_payload
                meta["durable_store_requested"] = True
                meta["_durable_store_fallback_payload"] = stateless_full_payload
                meta["_durable_store_key"] = continuation_key
                meta["_continuation_plan"] = {
                    "key": continuation_key,
                    "canonical_before": canonical_items,
                    "durable": True,
                    "live": False,
                }

                candidate = continuation_store.candidate(
                    continuation_key, canonical_items
                )
                if candidate is not None:
                    (
                        saved_response_id,
                        suffix,
                        prefix_items,
                        prefix_bytes,
                        instruction_items,
                        instruction_bytes,
                        candidate_instruction_pin,
                    ) = candidate
                    rewritten = dict(durable_full_payload)
                    rewritten["input"] = suffix
                    rewritten["previous_response_id"] = saved_response_id
                    meta["mode"] = "cross-switch-incremental"
                    meta["previous_response_id_state"] = "saved-provider-state"
                    meta["cross_switch_continuation"] = True
                    meta["continuation_prefix_items"] = prefix_items
                    meta["continuation_prefix_bytes"] = prefix_bytes
                    meta["continuation_delta_items"] = len(suffix)
                    meta["continuation_delta_bytes"] = sum(_json_size(item) for item in suffix)
                    meta["continuation_instruction_items"] = instruction_items
                    meta["continuation_instruction_bytes"] = instruction_bytes
                    meta["restart_instruction_pin"] = bool(candidate_instruction_pin)
                    meta["upstream_input_items"] = len(suffix)
                    meta["_cross_switch_fallback_payload"] = durable_full_payload
                    meta["_continuation_response_id"] = saved_response_id
                    meta["_continuation_scope"] = "durable"
            else:
                rewritten = stateless_full_payload
                if continuation_store is not None and continuation_key:
                    meta["provider_state_capability"] = continuation_store.capability_state(
                        continuation_key
                    )

        meta["upstream_input_items"] = len(rewritten.get("input", [])) if isinstance(rewritten, dict) and isinstance(rewritten.get("input"), list) else 0

    # Cache continuity is the safe Official cross-restart optimization. Keep a plain
    # fallback before adding any bridge cache-control fields because the ChatGPT Codex
    # backend can expose a narrower schema than the public Responses API.
    plain_cache_fallback_payload = rewritten
    rewritten, bp_added, bp_eligible, cache_options_added = apply_stable_prompt_cache_breakpoints(
        rewritten, enabled=prompt_cache_optimization
    )
    meta["prompt_cache_breakpoints_added"] = bp_added
    meta["prompt_cache_eligible_blocks"] = bp_eligible
    meta["prompt_cache_options_added"] = cache_options_added

    rewritten, cache_key_added = apply_prompt_cache_key(
        rewritten,
        enabled=prompt_cache_key_enabled,
        namespace=effective_namespace,
    )
    if cache_key_added:
        meta["prompt_cache_key_added"] = True

    if bp_added > 0 or cache_key_added:
        meta["_prompt_cache_fallback_payload"] = plain_cache_fallback_payload
    return rewritten, meta

def neutralize_responses_payload(payload: object) -> tuple[object, int, int, int, bool]:
    """Neutralize provider-owned fields without touching message or call data."""
    if not isinstance(payload, dict):
        return payload, 0, 0, 0, False

    cleaned = dict(payload)
    removed = 0
    cleared_reasoning_content = 0
    removed_foreign_encrypted_content = 0
    previous_removed = False

    items = cleaned.get("input")
    if isinstance(items, list):
        neutral_items = []
        for item in items:
            if isinstance(item, dict):
                item = dict(item)
                original_id = item.get("id")
                if "id" in item:
                    item.pop("id", None)
                    removed += 1

                # Some third-party providers serialize visible reasoning text
                # into reasoning.content. OpenAI accepts this field on replay
                # only as an empty array. Keep the reasoning item and all of
                # its other fields, but neutralize the provider-specific text.
                content = item.get("content")
                foreign_reasoning = item.get("type") == "reasoning" and (
                    (isinstance(content, list) and bool(content))
                    or (
                        isinstance(original_id, str)
                        and not original_id.startswith("rs_")
                    )
                )
                if foreign_reasoning:
                    if isinstance(content, list) and content:
                        item["content"] = []
                        cleared_reasoning_content += 1

                    # encrypted_content is opaque provider-owned state. If
                    # this reasoning item came from a provider that emitted
                    # visible reasoning content, its ciphertext cannot be
                    # verified by a different provider either.
                    if "encrypted_content" in item:
                        item.pop("encrypted_content", None)
                        removed_foreign_encrypted_content += 1
            neutral_items.append(item)
        cleaned["input"] = neutral_items

    # A response ID belongs to the provider that created it and cannot safely
    # be replayed after changing providers.
    if cleaned.get("previous_response_id") is not None:
        cleaned.pop("previous_response_id", None)
        previous_removed = True

    # With full input replay, store=false prevents the next provider from
    # requiring server-side state from the previous provider.
    cleaned["store"] = False
    return (
        cleaned,
        removed,
        cleared_reasoning_content,
        removed_foreign_encrypted_content,
        previous_removed,
    )


def override_responses_model(
    payload: object, model_override: str, *, force: bool = True
) -> tuple[object, str | None, bool]:
    """Replace a replay request's model when an explicit target is configured.

    The bridge never guesses a target model.  The manager/user must provide it
    explicitly, because model names and availability differ between accounts.
    Requests without a string ``model`` are left untouched rather than having
    a new field invented for an otherwise valid provider request.
    """
    if not force or not model_override or not isinstance(payload, dict):
        original_model = payload.get("model") if isinstance(payload, dict) else None
        return payload, original_model if isinstance(original_model, str) else None, False

    original_model = payload.get("model")
    if not isinstance(original_model, str) or original_model == model_override:
        return payload, original_model if isinstance(original_model, str) else None, False
    # Preserve an explicit Official model selection (e.g. gpt-5.6-luna). The
    # manager override is only a stale-model repair when returning from a
    # third-party route, not a reason to turn one Official model into another.
    if _looks_official_model(original_model):
        return payload, original_model, False

    rewritten = dict(payload)
    rewritten["model"] = model_override
    return rewritten, original_model, True


def make_portable_responses_payload(
    payload: object, *, error_body: bytes | None = None
) -> tuple[object, int, int, bool]:
    """Build a provider-neutral replay after a target rejects structured state.

    This is a guarded compatibility path, not the normal request path.  Human/user and
    assistant messages are preserved.  Complete plain function/custom-tool call+output
    pairs are preserved verbatim apart from provider item ids.  Opaque provider state,
    hosted-tool state, stale response ids, and incomplete tool chains are omitted rather
    than guessed or fabricated.

    ``error_body`` is accepted so future compatibility rules can remain tied to an
    explicit upstream rejection instead of becoming unconditional request rewriting.
    """
    if not isinstance(payload, dict):
        return payload, 0, 0, False

    cleaned = dict(payload)
    removed_item_ids = 0
    omitted_provider_items = 0
    previous_removed = False
    items = cleaned.get("input")

    if isinstance(items, list):
        portable_items = []
        for original in items:
            if not isinstance(original, dict):
                portable_items.append(original)
                continue

            item = dict(original)
            item_type = item.get("type")
            if item_type in PORTABLE_PROVIDER_OWNED_ITEM_TYPES:
                omitted_provider_items += 1
                continue

            if "id" in item:
                item.pop("id", None)
                removed_item_ids += 1
            # Defensive cleanup for providers that attach opaque state to a
            # non-reasoning output item.
            item.pop("encrypted_content", None)
            portable_items.append(item)

        # A visible call without its result (or result without its call) is not a
        # complete stateless transcript.  Preserve complete portable pairs and drop
        # only the dangling records.  Never synthesize a result.
        portable_items, omitted_unpaired_tools = _prune_unpaired_tool_items(portable_items)
        omitted_provider_items += omitted_unpaired_tools

        # Some strict adapters require a Chat-Completions-style tool transcript: every
        # assistant tool-call group must be followed immediately by all of its tool results.
        # Apply this stronger repair only after the upstream explicitly rejected that ordering.
        # Other portability retries keep their existing behavior unchanged.
        if _strict_tool_adjacency_error(error_body):
            portable_items, omitted_nonadjacent_tools = _prune_nonadjacent_tool_groups(portable_items)
            omitted_provider_items += omitted_nonadjacent_tools
        cleaned["input"] = portable_items

    if cleaned.get("previous_response_id") is not None:
        cleaned.pop("previous_response_id", None)
        previous_removed = True

    # Response-shaping/provider-cache hints are optional and frequently differ across
    # Responses-compatible adapters.  Remove them only on this post-rejection retry.
    for field in PORTABLE_OPTIONAL_TOP_LEVEL_FIELDS:
        cleaned.pop(field, None)

    # A stateless full replay must not depend on state created by another provider.
    cleaned["store"] = False
    return cleaned, removed_item_ids, omitted_provider_items, previous_removed


def is_portability_error(status: int, body: bytes) -> bool:
    """Recognize cross-provider Responses-state incompatibility conservatively.

    Authentication, quota, model availability, and generic provider failures are *not*
    portability errors.  A retry is allowed only for 400/422 responses that either match
    one of the known historical failure signatures or explicitly reject structured
    Responses state such as reasoning/tool/item-reference records.
    """
    if status not in {400, 422} or not body:
        return False
    lowered = body.lower()
    if any(marker in lowered for marker in PORTABILITY_ERROR_MARKERS):
        return True
    names_structured_state = any(term in lowered for term in PORTABILITY_STATE_TERMS)
    explicit_rejection = any(term in lowered for term in PORTABILITY_REJECTION_TERMS)
    return names_structured_state and explicit_rejection



def _remove_comp_hash_recursive(value: object) -> int:
    removed = 0
    if isinstance(value, dict):
        if "comp_hash" in value:
            value.pop("comp_hash", None)
            removed += 1
        for nested in value.values():
            removed += _remove_comp_hash_recursive(nested)
    elif isinstance(value, list):
        for nested in value:
            removed += _remove_comp_hash_recursive(nested)
    return removed



_MODEL_LIST_KEYS = ("models", "data", "items")


def _catalog_entry_identity(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in ("slug", "id", "model"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _catalog_model_list(payload: object) -> list[object] | None:
    """Return the first model-entry list in a Codex catalog without assuming one schema."""
    if isinstance(payload, list):
        if not payload or any(_catalog_entry_identity(item) for item in payload):
            return payload
        return None
    if not isinstance(payload, dict):
        return None
    for key in _MODEL_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and (not value or any(_catalog_entry_identity(item) for item in value)):
            return value
    # Some Codex builds wrap the list one level deeper (for example {"catalog":{"models":...}}).
    for value in payload.values():
        if isinstance(value, dict):
            nested = _catalog_model_list(value)
            if nested is not None:
                return nested
    return None


def _catalog_model_ids(payload: object) -> set[str]:
    items = _catalog_model_list(payload)
    if items is None:
        return set()
    return {
        identity
        for identity in (_catalog_entry_identity(item) for item in items)
        if identity
    }


def _clone_json(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _filter_model_catalog(payload: object, allowed_models: set[str]) -> object:
    """Clone a catalog while retaining only explicitly allowed model entries.

    This is a fallback for a provider route whose original CC Switch catalog is temporarily
    unavailable. The wrapper/schema is preserved verbatim; only the first recognized model
    entry list is filtered. Unknown schemas are returned unchanged rather than synthesized.
    """
    cloned = _clone_json(payload)
    items = _catalog_model_list(cloned)
    if items is None:
        return cloned
    allowed = {item for item in allowed_models if isinstance(item, str) and item}
    items[:] = [item for item in items if _catalog_entry_identity(item) in allowed]
    return cloned


def _merge_model_catalogs(base_payload: object, extra_payload: object) -> tuple[object, int, int]:
    """Merge model entries while preserving provider capability metadata verbatim.

    The bundled Official catalog is the structural base. Third-party entries are appended.
    If a non-Official model already exists, the newest provider entry replaces it so changes
    to supported reasoning efforts or context limits hot-reload correctly. Official entries
    are never replaced by a third-party catalog with an accidentally colliding identifier.
    Returns (merged_payload, added_entries, replaced_entries).
    """
    merged = _clone_json(base_payload)
    extra = _clone_json(extra_payload)
    target = _catalog_model_list(merged)
    incoming = _catalog_model_list(extra)
    if target is None:
        # A schema we do not understand is safer to leave as the newest provider catalog
        # than to synthesize an invalid wrapper. In normal Codex catalogs this path is not used.
        return extra, len(_catalog_model_ids(extra)), 0
    if incoming is None:
        return merged, 0, 0

    index: dict[str, int] = {}
    for i, item in enumerate(target):
        identity = _catalog_entry_identity(item)
        if identity and identity not in index:
            index[identity] = i

    added = 0
    replaced = 0
    for item in incoming:
        identity = _catalog_entry_identity(item)
        if not identity:
            # Preserve opaque entries only if they are not byte-identical to an existing one.
            if item not in target:
                target.append(item)
                added += 1
            continue
        existing = index.get(identity)
        if existing is None:
            index[identity] = len(target)
            target.append(item)
            added += 1
            continue
        if _looks_official_model(identity):
            continue
        if target[existing] != item:
            target[existing] = item
            replaced += 1
    return merged, added, replaced


class CatalogConfigGuard:
    """Maintain provider-scoped picker catalogs while retaining a private learned catalog.

    CC Switch may replace ``config.toml`` on each provider switch. The guard observes that
    transient rewrite *before* restoring the bridge config, records whether the upstream
    route is Official or third-party, and learns provider metadata into a bridge-owned
    internal catalog. The catalog exposed through ``model_catalog_json`` is different: it is
    an immutable hash-neutral snapshot scoped to the *current* provider only. Official routes
    therefore show only bundled Official models, while third-party routes show only models
    from that provider. Provider-managed catalog files are never modified in place.
    """

    def __init__(
        self,
        *,
        config_path: str,
        bundled_catalog_path: str,
        active_catalog_path: str,
        official_provider_id: str,
        bridge_provider_id: str,
        bridge_provider_name: str,
        bridge_base_url: str,
        realtime_ws_base_url: str,
        realtime_webrtc_call_base_url: str,
        interval: float = 0.25,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.bundled_catalog_path = Path(bundled_catalog_path).expanduser().resolve()
        self.active_catalog_path = Path(active_catalog_path).expanduser().resolve()
        self.scoped_catalog_path = self.active_catalog_path.with_name("cpb-provider-model-catalog.json")
        self.detach_flag_path = self.active_catalog_path.with_name("cpb-native-detach.flag")
        self.official_provider_id = official_provider_id
        self.bridge_provider_id = bridge_provider_id
        self.bridge_provider_name = bridge_provider_name
        self.bridge_base_url = bridge_base_url.rstrip("/")
        self.realtime_ws_base_url = realtime_ws_base_url
        self.realtime_webrtc_call_base_url = realtime_webrtc_call_base_url
        self.interval = max(0.10, interval)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_source_path: Path | None = None
        self.last_source_signature: tuple[int, int] | None = None
        self.last_error: str | None = None
        self.sidecar_path = self.active_catalog_path.with_suffix(
            self.active_catalog_path.suffix + ".source.json"
        )
        self.route_lock = threading.Lock()
        self.route_kind = ""
        self.route_model = ""
        self.route_models: set[str] = set()
        self.route_serial = 0
        self.last_merge_added = 0
        self.last_merge_replaced = 0
        self.published_catalog_path = self.scoped_catalog_path
        self.published_catalog_digest = ""
        self._load_sidecar()
        self._hydrate_route_models_from_source()

    @staticmethod
    def _decode_double_quoted(raw: str) -> str:
        try:
            value = json.loads('"' + raw + '"')
            return value if isinstance(value, str) else raw
        except json.JSONDecodeError:
            return raw.replace("\\\\", "\\").replace('\\"', '"')

    @staticmethod
    def _top_level_value(text: str, key: str) -> str | None:
        double = re.compile(
            r"^\s*" + re.escape(key) + r'\s*=\s*"((?:\\.|[^"\\])*)"\s*(?:#.*)?$'
        )
        single = re.compile(
            r"^\s*" + re.escape(key) + r"\s*=\s*'([^']*)'\s*(?:#.*)?$"
        )
        for line in text.splitlines():
            if re.match(r"^\s*\[", line):
                break
            match = double.match(line)
            if match:
                return CatalogConfigGuard._decode_double_quoted(match.group(1))
            match = single.match(line)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _provider_value(text: str, provider_id: str, key: str) -> str | None:
        escaped = re.escape(provider_id)
        header = re.compile(
            r'^\s*\[model_providers\.(?:' + escaped + r'|"' + escaped + r'")\]\s*$'
        )
        value_re = re.compile(
            r"^\s*" + re.escape(key) + r'\s*=\s*"((?:\\.|[^"\\])*)"\s*(?:#.*)?$'
        )
        inside = False
        for line in text.splitlines():
            if re.match(r"^\s*\[", line):
                inside = bool(header.match(line))
                continue
            if inside:
                match = value_re.match(line)
                if match:
                    return CatalogConfigGuard._decode_double_quoted(match.group(1))
        return None

    def _config_mode(self, text: str) -> str:
        provider = self._top_level_value(text, "model_provider")
        model = self._top_level_value(text, "model") or ""
        if provider == self.official_provider_id:
            return "official"
        if provider == self.bridge_provider_id:
            base_url = self._provider_value(text, self.bridge_provider_id, "base_url")
            if base_url and base_url.rstrip("/") == self.bridge_base_url:
                return "bridge"
            return "third-party"
        if provider is None and re.match(r"(?i)^(gpt-|o[0-9]|codex)", model):
            return "official"
        return "third-party"

    def _catalog_from_config(self, text: str) -> Path | None:
        raw = self._top_level_value(text, "model_catalog_json")
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path.resolve()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _load_sidecar(self) -> None:
        try:
            payload = json.loads(self.sidecar_path.read_text(encoding="utf-8"))
            raw = payload.get("source_path")
            if isinstance(raw, str) and raw:
                self.last_source_path = Path(raw).expanduser().resolve()
            sig = payload.get("source_signature")
            if (
                isinstance(sig, list)
                and len(sig) == 2
                and all(isinstance(item, int) for item in sig)
            ):
                self.last_source_signature = (sig[0], sig[1])
            route_kind = payload.get("route_kind")
            route_model = payload.get("route_model")
            if isinstance(route_kind, str):
                self.route_kind = route_kind
            if isinstance(route_model, str):
                self.route_model = route_model
            route_serial = payload.get("route_serial")
            if isinstance(route_serial, int) and route_serial >= 0:
                self.route_serial = route_serial
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return

    def _persist_sidecar(self) -> None:
        self.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        with self.route_lock:
            route_kind = self.route_kind
            route_model = self.route_model
            route_serial = self.route_serial
        payload = {
            "source_path": str(self.last_source_path) if self.last_source_path else "",
            "source_signature": list(self.last_source_signature) if self.last_source_signature else None,
            "route_kind": route_kind,
            "route_model": route_model,
            "route_serial": route_serial,
        }
        temporary = self.sidecar_path.with_name(
            f".{self.sidecar_path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.sidecar_path)

    def _save_sidecar(self, source: Path, signature: tuple[int, int] | None) -> None:
        self.last_source_path = source
        self.last_source_signature = signature
        self._persist_sidecar()

    def _hydrate_route_models_from_source(self) -> None:
        source = self.last_source_path
        if self.route_kind == "official":
            source = self.bundled_catalog_path
        if source is None or not source.is_file():
            return
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            models = _catalog_model_ids(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        with self.route_lock:
            self.route_models = models

    def _set_route_state(
        self, kind: str, model: str, models: set[str] | None = None
    ) -> None:
        normalized = kind if kind in {"official", "third-party"} else ""
        next_model = model.strip() if isinstance(model, str) else ""
        changed = False
        route_changed = False
        with self.route_lock:
            if self.route_kind != normalized:
                self.route_kind = normalized
                changed = True
                route_changed = True
            if self.route_model != next_model:
                self.route_model = next_model
                changed = True
                route_changed = True
            if route_changed:
                self.route_serial += 1
            if models is not None and self.route_models != set(models):
                self.route_models = set(models)
                changed = True
        if changed:
            self._persist_sidecar()

    def route_snapshot(self) -> tuple[str, str, set[str]]:
        with self.route_lock:
            return self.route_kind, self.route_model, set(self.route_models)

    def route_serial_snapshot(self) -> int:
        with self.route_lock:
            return int(self.route_serial)

    @staticmethod
    def _write_json_atomic(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _write_json_if_changed(path: Path, payload: object) -> bool:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            if path.read_text(encoding="utf-8") == serialized:
                return False
        except (OSError, UnicodeDecodeError):
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
        return True

    def _read_catalog(self, path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def _is_bridge_owned_catalog(self, path: Path | None) -> bool:
        if path is None:
            return False
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path
        if resolved in {
            self.bundled_catalog_path,
            self.active_catalog_path,
            self.scoped_catalog_path,
        }:
            return True
        if resolved.parent != self.active_catalog_path.parent:
            return False
        names = (
            self.active_catalog_path.stem + ".snapshot-",  # legacy unified snapshots
            self.scoped_catalog_path.stem + ".snapshot-",
        )
        return any(resolved.name.startswith(prefix) for prefix in names) and resolved.suffix == self.active_catalog_path.suffix

    def _publish_catalog_snapshot(self, payload: object) -> tuple[Path, bool]:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        snapshot = self.scoped_catalog_path.with_name(
            f"{self.scoped_catalog_path.stem}.snapshot-{digest}{self.scoped_catalog_path.suffix}"
        )
        changed_generation = digest != self.published_catalog_digest
        if not snapshot.is_file():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            temporary = snapshot.with_name(
                f".{snapshot.name}.tmp-{os.getpid()}-{threading.get_ident()}"
            )
            temporary.write_text(serialized, encoding="utf-8")
            os.replace(temporary, snapshot)
        self.published_catalog_path = snapshot
        self.published_catalog_digest = digest
        try:
            prefix = self.scoped_catalog_path.stem + ".snapshot-"
            candidates = sorted(
                (item for item in snapshot.parent.glob(prefix + "*" + self.scoped_catalog_path.suffix) if item != snapshot),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            for stale in candidates[6:]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError:
            pass
        return snapshot, changed_generation

    def _ensure_unified_catalog(self) -> tuple[int, int, int]:
        """Ensure active_catalog_path contains bundled Official + every learned provider model."""
        if not self.bundled_catalog_path.is_file():
            return 0, 0, 0
        bundled = self._read_catalog(self.bundled_catalog_path)
        _remove_comp_hash_recursive(bundled)
        existing: object = bundled
        if self.active_catalog_path.is_file():
            try:
                active = self._read_catalog(self.active_catalog_path)
                existing, _, _ = _merge_model_catalogs(bundled, active)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                existing = bundled
        removed = _remove_comp_hash_recursive(existing)
        self._write_json_if_changed(self.active_catalog_path, existing)
        return removed, len(_catalog_model_ids(existing)), 0

    def _mirror_external_catalog(self, source: Path) -> int:
        external = self._read_catalog(source)
        removed = _remove_comp_hash_recursive(external)
        if self.bundled_catalog_path.is_file():
            bundled = self._read_catalog(self.bundled_catalog_path)
            _remove_comp_hash_recursive(bundled)
        else:
            bundled = external
        base: object = bundled
        if self.active_catalog_path.is_file():
            try:
                active = self._read_catalog(self.active_catalog_path)
                base, _, _ = _merge_model_catalogs(bundled, active)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                base = bundled
        merged, added, replaced = _merge_model_catalogs(base, external)
        removed += _remove_comp_hash_recursive(merged)
        self._write_json_if_changed(self.active_catalog_path, merged)
        signature = self._signature(source)
        self.last_merge_added = added
        self.last_merge_replaced = replaced
        self._save_sidecar(source, signature)
        return removed

    @staticmethod
    def _first_section_index(lines: list[str]) -> int:
        for index, line in enumerate(lines):
            if re.match(r"^\s*\[", line):
                return index
        return len(lines)

    @staticmethod
    def _set_top_level(lines: list[str], key: str, value: str) -> None:
        end = CatalogConfigGuard._first_section_index(lines)
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
        for index in range(end):
            if pattern.match(lines[index]):
                lines[index] = f"{key} = {value}"
                return
        lines.insert(end, f"{key} = {value}")

    @staticmethod
    def _remove_top_level(lines: list[str], key: str) -> None:
        end = CatalogConfigGuard._first_section_index(lines)
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
        lines[:end] = [line for line in lines[:end] if not pattern.match(line)]

    @staticmethod
    def _set_section_key(
        lines: list[str],
        *,
        header_pattern: re.Pattern[str],
        new_header: str,
        key: str,
        value: str,
    ) -> None:
        start: int | None = None
        for index, line in enumerate(lines):
            if header_pattern.match(line):
                start = index
                break
        if start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend([new_header, f"{key} = {value}"])
            return
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if re.match(r"^\s*\[", lines[index]):
                end = index
                break
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
        for index in range(start + 1, end):
            if pattern.match(lines[index]):
                lines[index] = f"{key} = {value}"
                return
        lines.insert(end, f"{key} = {value}")

    def _detach_requested(self) -> bool:
        # Launcher/manager creates this latch before rewriting custom.base_url to the
        # direct Official ChatGPT Codex backend.  The resident guard must become read-only immediately,
        # otherwise its 250 ms reconciliation loop can race the detach write and
        # repin model_provider=custom / :15722 just before the Bridge is stopped.
        return self.detach_flag_path.exists()

    def _write_config_lines(self, original: str, lines: list[str]) -> bool:
        if self._detach_requested():
            return False
        newline = "\r\n" if "\r\n" in original else "\n"
        had_final_newline = original.endswith(("\n", "\r"))
        updated = newline.join(lines)
        if had_final_newline:
            updated += newline
        if updated == original:
            return False
        temporary = self.config_path.with_name(
            f".{self.config_path.name}.cpb-guard-tmp-{os.getpid()}-{threading.get_ident()}"
        )
        temporary.write_text(updated, encoding="utf-8", newline="")
        last_error: OSError | None = None
        for attempt in range(8):
            try:
                # Check again immediately before replace.  This closes the race
                # where guard_once started just before the detach latch appeared.
                if self._detach_requested():
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
                    return False
                os.replace(temporary, self.config_path)
                return True
            except PermissionError as exc:
                last_error = exc
                # CC Switch/Codex can briefly hold config.toml while atomically
                # replacing it. A short bounded retry avoids a noisy race without
                # ever touching CC Switch itself.
                import time
                time.sleep(0.025 * (attempt + 1))
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
        if last_error is not None:
            raise last_error
        return False

    def _ensure_bridge_config(
        self, catalog: Path | None, *, route_official: bool | None = None
    ) -> bool:
        text = self.config_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        quote = lambda value: json.dumps(value, ensure_ascii=False)
        self._set_top_level(lines, "model_provider", quote(self.bridge_provider_id))
        if catalog is not None:
            self._set_top_level(lines, "model_catalog_json", quote(str(catalog)))
        else:
            current_catalog = self._catalog_from_config(text)
            if self._is_bridge_owned_catalog(current_catalog):
                self._remove_top_level(lines, "model_catalog_json")
        self._remove_top_level(lines, "disable_response_storage")
        if self.realtime_ws_base_url:
            self._set_top_level(
                lines,
                "experimental_realtime_ws_base_url",
                quote(self.realtime_ws_base_url),
            )
        if self.realtime_webrtc_call_base_url:
            self._set_top_level(
                lines,
                "experimental_realtime_webrtc_call_base_url",
                quote(self.realtime_webrtc_call_base_url),
            )

        escaped = re.escape(self.bridge_provider_id)
        provider_header = re.compile(
            r'^\s*\[model_providers\.(?:' + escaped + r'|"' + escaped + r'")\]\s*$'
        )
        provider_name = f"[model_providers.{self.bridge_provider_id}]"
        self._set_section_key(
            lines,
            header_pattern=provider_header,
            new_header=provider_name,
            key="name",
            value=quote(self.bridge_provider_name),
        )
        self._set_section_key(
            lines,
            header_pattern=provider_header,
            new_header=provider_name,
            key="base_url",
            value=quote(self.bridge_base_url),
        )
        self._set_section_key(
            lines,
            header_pattern=provider_header,
            new_header=provider_name,
            key="wire_api",
            value=quote("responses"),
        )
        self._set_section_key(
            lines,
            header_pattern=provider_header,
            new_header=provider_name,
            key="requires_openai_auth",
            value="true",
        )
        selected_model = self._top_level_value(text, "model") or ""
        if route_official is None:
            with self.route_lock:
                known_route = self.route_kind
            if known_route:
                route_official = known_route == "official"
            else:
                route_official = _looks_official_model(selected_model)
        websocket_value = "true" if route_official else "false"
        self._set_section_key(
            lines,
            header_pattern=provider_header,
            new_header=provider_name,
            key="supports_websockets",
            value=websocket_value,
        )
        features_header = re.compile(r"^\s*\[features\]\s*$")
        self._set_section_key(
            lines,
            header_pattern=features_header,
            new_header="[features]",
            key="enable_request_compression",
            value="false",
        )
        return self._write_config_lines(text, lines)

    def _set_config_catalog(self, target: Path) -> bool:
        text = self.config_path.read_text(encoding="utf-8")
        current = self._catalog_from_config(text)
        if current == target:
            return False
        lines = text.splitlines()
        self._set_top_level(
            lines,
            "model_catalog_json",
            json.dumps(str(target), ensure_ascii=False),
        )
        return self._write_config_lines(text, lines)

    def _publish_official_catalog(self) -> Path:
        if not self.bundled_catalog_path.is_file():
            raise OSError(f"bundled Official model catalog does not exist: {self.bundled_catalog_path}")
        payload = self._read_catalog(self.bundled_catalog_path)
        _remove_comp_hash_recursive(payload)
        published, _ = self._publish_catalog_snapshot(payload)
        return published

    def _publish_third_party_catalog(
        self, source: Path | None, route_models: set[str]
    ) -> Path | None:
        payload: object | None = None
        if source is not None and source.is_file():
            candidate = self._read_catalog(source)
            ids = _catalog_model_ids(candidate)
            # Reuse a source only when it actually describes the active route. This
            # prevents a stale GLM catalog from appearing on a later DeepSeek route.
            if not route_models or not ids or bool(ids & route_models):
                payload = candidate
        if payload is None and self.active_catalog_path.is_file() and route_models:
            learned = self._read_catalog(self.active_catalog_path)
            payload = _filter_model_catalog(learned, route_models)
        if payload is None:
            return None
        _remove_comp_hash_recursive(payload)
        if route_models:
            ids = _catalog_model_ids(payload)
            if ids and not (ids & route_models):
                return None
        published, _ = self._publish_catalog_snapshot(payload)
        return published

    def guard_once(self) -> None:
        # Graceful Exit owns config.toml while this latch exists. Do not even
        # inspect/reconcile provider state until the manager has stopped us.
        if self._detach_requested():
            return
        if not self.config_path.is_file():
            return
        text = self.config_path.read_text(encoding="utf-8")
        mode = self._config_mode(text)
        current = self._catalog_from_config(text)
        selected_model = self._top_level_value(text, "model") or ""

        # Keep a private learned catalog for routing/capability memory. It is never
        # exposed directly to Codex's picker in provider-scoped mode.
        self._ensure_unified_catalog()

        if mode == "official":
            official_models: set[str] = set()
            if self.bundled_catalog_path.is_file():
                try:
                    official_models = _catalog_model_ids(self._read_catalog(self.bundled_catalog_path))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    official_models = set()
            self._set_route_state("official", selected_model, official_models)
            scoped_catalog = self._publish_official_catalog()
            changed = self._ensure_bridge_config(scoped_catalog, route_official=True)
            if changed:
                print(
                    "Provider-scoped catalog guard: Official route selected; Codex picker now "
                    "contains Official models only.",
                    flush=True,
                )
            return

        if mode == "third-party":
            route_models: set[str] = {selected_model} if selected_model else set()
            source: Path | None = None
            removed = 0
            if current and not self._is_bridge_owned_catalog(current):
                if not current.is_file():
                    raise OSError(f"configured model catalog does not exist: {current}")
                external_payload = self._read_catalog(current)
                route_models = _catalog_model_ids(external_payload) or route_models
                source = current
                removed = self._mirror_external_catalog(current)
            else:
                # In steady/rewrite races, prefer the last provider catalog only if it
                # contains the current route model. Otherwise fall back to filtering the
                # private learned catalog by the route model set.
                source = self.last_source_path
                with self.route_lock:
                    previous_models = set(self.route_models)
                if previous_models:
                    route_models |= previous_models

            self._set_route_state("third-party", selected_model, route_models)
            scoped_catalog = self._publish_third_party_catalog(source, route_models)
            changed_route = self._ensure_bridge_config(
                scoped_catalog, route_official=False
            )
            if changed_route or self.last_merge_added or self.last_merge_replaced:
                print(
                    "Provider-scoped catalog guard: third-party route selected; Codex picker "
                    f"contains current-provider models only; learned_added={self.last_merge_added}, "
                    f"learned_updated={self.last_merge_replaced}, removed_comp_hash={removed}, "
                    f"route_model={selected_model or '-'}.",
                    flush=True,
                )
            return

        # mode == bridge: normal steady state. The upstream route is preserved from
        # the most recent CC Switch rewrite. A picker change within that provider does
        # not become a provider change.
        with self.route_lock:
            known_route = self.route_kind
        if not known_route:
            if _looks_official_model(selected_model):
                models: set[str] = set()
                if self.bundled_catalog_path.is_file():
                    try:
                        models = _catalog_model_ids(self._read_catalog(self.bundled_catalog_path))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        pass
                self._set_route_state("official", selected_model, models)
            else:
                models = set()
                if self.last_source_path and self.last_source_path.is_file():
                    try:
                        models = _catalog_model_ids(self._read_catalog(self.last_source_path))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        pass
                if selected_model:
                    models.add(selected_model)
                self._set_route_state("third-party", selected_model, models)

        route_kind, _, route_models = self.route_snapshot()
        if route_kind == "official":
            scoped_catalog = self._publish_official_catalog()
        else:
            scoped_catalog = self._publish_third_party_catalog(self.last_source_path, route_models)

        if scoped_catalog is not None and current != scoped_catalog:
            if self._ensure_bridge_config(
                scoped_catalog, route_official=(route_kind == "official")
            ):
                print(
                    "Provider-scoped catalog guard: pinned Codex picker to the current provider "
                    "without changing the selected model.",
                    flush=True,
                )

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.guard_once()
                self.last_error = None
            except Exception as exc:
                message = str(exc)
                if message != self.last_error:
                    print(
                        f"Warning: CompHash resident catalog guard could not reconcile config: {message}",
                        file=sys.stderr,
                        flush=True,
                    )
                    self.last_error = message

    def start(self) -> None:
        self.guard_once()
        self.thread = threading.Thread(
            target=self._run,
            name="cpb-catalog-config-guard",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=max(1.0, self.interval * 4))

def neutralize_model_catalog_comp_hash(
    body: bytes, _target_model: str = ""
) -> tuple[bytes, int, int, bool]:
    """Recursively omit comp_hash from bridged /models JSON.

    When ``model_catalog_json`` is configured, Codex can bypass this endpoint
    entirely; the manager therefore neutralizes that static catalog before
    startup. This network guard remains defense in depth for configurations that
    still use remote discovery/cache paths.

    Returns (body, fields_removed, model_entries_seen, json_parsed).
    """
    if not body:
        return body, 0, 0, False
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body, 0, 0, False

    entries_seen = 0

    def count_entries(value: object) -> None:
        nonlocal entries_seen
        if isinstance(value, dict):
            identity = value.get("slug")
            if not isinstance(identity, str):
                identity = value.get("id")
            if not isinstance(identity, str):
                identity = value.get("model")
            if isinstance(identity, str):
                entries_seen += 1
            for nested in value.values():
                count_entries(nested)
        elif isinstance(value, list):
            for nested in value:
                count_entries(nested)

    count_entries(payload)
    removed = _remove_comp_hash_recursive(payload)
    if removed == 0:
        return body, 0, entries_seen, True
    rewritten = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return rewritten, removed, entries_seen, True


WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OFFICIAL_LIVE_SESSION_IDLE_TTL_SECONDS = 2 * 60 * 60


def _websocket_response_header_value(header_bytes: bytes, name: str) -> str:
    wanted = name.lower().encode("ascii") + b":"
    for line in header_bytes.split(b"\r\n"):
        if line.lower().startswith(wanted):
            return line.split(b":", 1)[1].strip().decode("latin-1", errors="replace")
    return ""


class PersistentOfficialSession:
    """One direct Official Responses WebSocket that can outlive Codex client sockets.

    A session starts as an isolated bootstrap socket.  It becomes resident only after a
    meaningful user conversation request is observed.  This prevents Codex restart probes
    and background sockets from replacing or hijacking the useful conversation socket.
    """

    def __init__(
        self,
        key: str,
        upstream_socket: socket.socket,
        upstream_reader: BufferedSocketReader,
        selected_protocol: str,
    ) -> None:
        self.key = key
        self.upstream_socket = upstream_socket
        self.upstream_reader = upstream_reader
        self.selected_protocol = selected_protocol
        self.state = WebSocketContinuationState()
        self.live_store = LiveProviderContinuationStore()
        self.continuation_tracker = ContinuationRequestTracker()
        self.cache_fallback_lock = threading.Lock()
        self.cache_fallbacks: deque[bytes] = deque()
        self.continuation_fallback_lock = threading.Lock()
        self.continuation_fallbacks: deque[tuple[bytes, str, str, str]] = deque()
        self.store_fallback_lock = threading.Lock()
        self.store_fallbacks: deque[tuple[bytes, str]] = deque()
        self.upstream_write_lock = threading.Lock()
        self.client_lock = threading.Lock()
        self.current_client: socket.socket | None = None
        self.detached_at = time.monotonic()
        self.closed = threading.Event()
        self.pump_thread: threading.Thread | None = None
        self.classification_lock = threading.Lock()
        self.classified = False
        self.conversation_fingerprint = ""
        self.models_seen: set[str] = set()
        self.inflight_lock = threading.Lock()
        self.inflight_responses = 0

    def attach(self, client: socket.socket) -> None:
        old: socket.socket | None = None
        with self.client_lock:
            old = self.current_client
            self.current_client = client
            self.detached_at = 0.0
        if old is not None and old is not client:
            try:
                old.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                old.close()
            except OSError:
                pass

    def detach(self, client: socket.socket) -> None:
        with self.client_lock:
            if self.current_client is client:
                self.current_client = None
                self.detached_at = time.monotonic()

    def client(self) -> socket.socket | None:
        with self.client_lock:
            return self.current_client

    def mark_conversation(self, model: object, fingerprint: str) -> None:
        with self.classification_lock:
            if isinstance(model, str) and model.strip():
                self.models_seen.add(model.strip().lower())
            if fingerprint and not self.conversation_fingerprint:
                self.conversation_fingerprint = fingerprint
            self.classified = True

    def note_request(self) -> None:
        with self.inflight_lock:
            self.inflight_responses += 1

    def note_completion(self) -> None:
        with self.inflight_lock:
            if self.inflight_responses > 0:
                self.inflight_responses -= 1

    def is_idle(self) -> bool:
        with self.inflight_lock:
            return self.inflight_responses == 0

    def is_expired(self) -> bool:
        if self.closed.is_set():
            return True
        with self.client_lock:
            if self.current_client is not None or self.detached_at <= 0:
                return False
            return (time.monotonic() - self.detached_at) > OFFICIAL_LIVE_SESSION_IDLE_TTL_SECONDS

    def send_upstream(self, frame: bytes) -> None:
        with self.upstream_write_lock:
            if self.closed.is_set():
                raise OSError("persistent Official upstream is closed")
            self.upstream_socket.sendall(frame)

    def send_client(self, frame: bytes) -> bool:
        client = self.client()
        if client is None:
            return False
        try:
            client.sendall(frame)
            return True
        except OSError:
            self.detach(client)
            return False

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        client = self.client()
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        try:
            self.upstream_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.upstream_socket.close()
        except OSError:
            pass


class OfficialLiveSessionPool:
    """Resident Official sockets indexed independently from transient Codex WS clients."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessions: dict[str, PersistentOfficialSession] = {}

    def put(self, session: PersistentOfficialSession) -> None:
        if not session.key:
            return
        old: PersistentOfficialSession | None = None
        with self.lock:
            old = self.sessions.get(session.key)
            self.sessions[session.key] = session
        if old is not None and old is not session:
            old.close()

    def remove(self, key: str, session: PersistentOfficialSession) -> None:
        with self.lock:
            if self.sessions.get(key) is session:
                self.sessions.pop(key, None)

    def find_match(
        self,
        continuation_key: str,
        current_items: list[object],
        selected_protocol: str,
        *,
        exclude: PersistentOfficialSession | None = None,
    ) -> PersistentOfficialSession | None:
        """Find the detached live socket whose completed provider state prefixes replay.

        A first-message hash is intentionally insufficient.  The match must be backed by
        LiveProviderContinuationStore.candidate(), which proves that the current portable
        timeline extends state actually completed on that exact upstream socket.
        """
        if not continuation_key or not current_items:
            return None
        stale: list[PersistentOfficialSession] = []
        with self.lock:
            sessions = list(self.sessions.values())
        best: PersistentOfficialSession | None = None
        best_score = (-1, -1)
        for session in sessions:
            if session is exclude:
                continue
            if session.is_expired():
                stale.append(session)
                continue
            if session.closed.is_set() or not session.classified:
                continue
            if session.client() is not None or not session.is_idle():
                continue
            if session.selected_protocol != selected_protocol:
                continue
            candidate = session.live_store.candidate(continuation_key, current_items)
            if candidate is None:
                continue
            # candidate = (response_id, suffix, prefix_items, prefix_bytes, ...)
            score = (int(candidate[3]), int(candidate[2]))
            if score > best_score:
                best = session
                best_score = score
        for session in stale:
            self.remove(session.key, session)
            session.close()
        return best

    def count(self) -> int:
        with self.lock:
            return len(self.sessions)

    def close_all(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CodexProviderBridge/2.9.4-http-error-sanitize"

    def _safe_send_error(self, code: int, message: str) -> None:
        # HTTP reason phrases are latin-1 in BaseHTTPRequestHandler. Localized
        # Windows socket errors can contain non-Latin text, so sanitize them.
        safe = str(message).encode("ascii", errors="backslashreplace").decode("ascii")
        if len(safe) > 240:
            safe = safe[:237] + "..."
        try:
            self.send_error(code, safe)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _upstream_path(self) -> str:
        upstream = self.server.upstream  # type: ignore[attr-defined]
        path = (upstream.path.rstrip("/") + "/" + self.path.lstrip("/")) or "/"
        if upstream.query:
            separator = "&" if "?" in path else "?"
            path += separator + upstream.query
        return path

    def _is_websocket_upgrade(self) -> bool:
        upgrade = (self.headers.get("Upgrade") or "").strip().lower()
        connection = (self.headers.get("Connection") or "").lower()
        return upgrade == "websocket" and "upgrade" in {part.strip() for part in connection.split(",")}

    def _is_responses_path(self) -> bool:
        return self.path.split("?", 1)[0].rstrip("/").endswith("/responses")

    def _is_models_path(self) -> bool:
        return self.path.split("?", 1)[0].rstrip("/").endswith("/models")

    def _configured_route_model(self) -> str:
        path = getattr(self.server, "codex_config_path", None)
        if not path:
            return ""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
        for line in text.splitlines():
            if re.match(r"^\s*\[", line):
                break
            match = re.match(r'^\s*model\s*=\s*"((?:\\.|[^"\\])*)"', line)
            if match:
                try:
                    value = json.loads('"' + match.group(1) + '"')
                except json.JSONDecodeError:
                    value = match.group(1).replace("\\\\", "\\").replace('\\"', '"')
                return value if isinstance(value, str) else ""
        return ""

    def _route_snapshot(self) -> tuple[str, str, set[str]]:
        guard = getattr(self.server, "catalog_guard", None)
        if guard is not None:
            try:
                kind, model, models = guard.route_snapshot()
                if kind in {"official", "third-party"}:
                    return kind, model, models
            except Exception:
                pass
        # Compatibility fallback if the catalog guard is disabled.
        configured = self._configured_route_model()
        if configured:
            return ("official" if _looks_official_model(configured) else "third-party", configured, {configured})
        return "", "", set()

    def _route_serial(self) -> int:
        guard = getattr(self.server, "catalog_guard", None)
        if guard is not None:
            try:
                return int(guard.route_serial_snapshot())
            except Exception:
                pass
        return 0

    def _route_looks_official(self) -> bool:
        kind, model, _ = self._route_snapshot()
        if kind:
            return kind == "official"
        return _looks_official_model(model) if model else False

    def _hot_switch_rewrite(self, payload: object) -> tuple[object, str | None, bool, str]:
        kind, route_model, route_models = self._route_snapshot()
        route_official = kind == "official"
        state = self.server.hot_switch_route_state  # type: ignore[attr-defined]
        return state.rewrite(payload, route_model, route_official, route_models)

    def _open_websocket_target(
        self, target: object, target_path: str
    ) -> tuple[socket.socket, bytes, bytes, int]:
        scheme = target.scheme  # type: ignore[attr-defined]
        hostname = target.hostname  # type: ignore[attr-defined]
        if not hostname:
            raise OSError("WebSocket upstream has no hostname")
        default_port = 443 if scheme == "https" else 80
        port = target.port or default_port  # type: ignore[attr-defined]

        raw_socket = _connect_outbound_socket(
            scheme, hostname, port, timeout=15
        )
        upstream_socket: socket.socket
        if scheme == "https":
            context = ssl.create_default_context()
            upstream_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
        elif scheme == "http":
            upstream_socket = raw_socket
        else:
            raw_socket.close()
            raise OSError(f"unsupported WebSocket upstream scheme: {scheme}")

        request = [f"{self.command} {target_path} HTTP/1.1\r\n".encode("ascii")]
        host_value = hostname
        if port != default_port:
            host_value = f"{host_value}:{port}"
        request.append(f"Host: {host_value}\r\n".encode("latin-1"))
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in {"host", "proxy-connection", "sec-websocket-extensions"}:
                continue
            request.append(f"{key}: {value}\r\n".encode("latin-1"))
        request.append(b"\r\n")
        upstream_socket.sendall(b"".join(request))

        response_head = bytearray()
        while b"\r\n\r\n" not in response_head:
            chunk = upstream_socket.recv(4096)
            if not chunk:
                upstream_socket.close()
                raise OSError("upstream closed during WebSocket handshake")
            response_head.extend(chunk)
            if len(response_head) > 65536:
                upstream_socket.close()
                raise OSError("WebSocket handshake response headers are too large")

        header_end = response_head.index(b"\r\n\r\n") + 4
        header_bytes = bytes(response_head[:header_end])
        buffered = bytes(response_head[header_end:])
        status_line = header_bytes.split(b"\r\n", 1)[0]
        try:
            status = int(status_line.split(b" ", 2)[1])
        except (IndexError, ValueError) as exc:
            upstream_socket.close()
            raise OSError(f"invalid WebSocket handshake response: {status_line!r}") from exc
        return upstream_socket, header_bytes, buffered, status

    def _direct_responses_ws_path(self) -> str:
        target = self.server.responses_ws_upstream  # type: ignore[attr-defined]
        path = target.path.rstrip("/") + "/responses"
        if not path.startswith("/"):
            path = "/" + path
        if "?" in self.path:
            path += "?" + self.path.split("?", 1)[1]
        return path

    def _make_http_connection(self, target) -> http.client.HTTPConnection:
        """Create an HTTP(S) connection for either CC Switch or direct Official."""
        if target.scheme == "https":
            return http.client.HTTPSConnection(
                target.hostname, target.port, timeout=600, context=ssl.create_default_context()
            )
        return http.client.HTTPConnection(target.hostname, target.port, timeout=600)

    def _open_websocket_upstream(
        self, responses_mode: bool
    ) -> tuple[socket.socket, bytes, bytes, int, str]:
        """Open exactly one provider route for a Responses WebSocket.

        Official Responses WS goes directly to ChatGPT first. This avoids the
        zero-token CC Switch 405 probe rows that older bridge versions generated
        before every successful Official WS. Third-party routes never fall through
        to Official: they stay on the local CC Switch route and may return 405 so
        Codex can use HTTP/SSE.
        """
        local = self.server.upstream  # type: ignore[attr-defined]
        direct = self.server.responses_ws_upstream  # type: ignore[attr-defined]
        route_official = self._route_looks_official()

        if responses_mode and route_official and direct is not None:
            try:
                sock, headers, buffered, status = self._open_websocket_target(
                    direct, self._direct_responses_ws_path()
                )
                if status == 101:
                    return sock, headers, buffered, status, "direct-official"
                sock.close()
                self.log_message(
                    "Direct Official Responses WS returned %s; trying CC Switch compatibility path",
                    status,
                )
            except OSError as exc:
                self.log_message(
                    "Direct Official Responses WS unavailable (%s); trying CC Switch compatibility path",
                    exc,
                )

        try:
            sock, headers, buffered, status = self._open_websocket_target(
                local, self._upstream_path()
            )
        except OSError:
            raise
        if not responses_mode or status == 101:
            return sock, headers, buffered, status, "cc-switch"
        if not route_official:
            self.log_message(
                "CC Switch Responses WS returned %s on third-party route; "
                "direct Official fallback suppressed",
                status,
            )
            return sock, headers, buffered, status, "cc-switch-http-fallback"
        # Official direct WS was already attempted above. Return the local response
        # so Codex can fall back without a second cross-provider network attempt.
        return sock, headers, buffered, status, "cc-switch-http-fallback"

    def _official_live_session_key(self) -> str:
        model = self._configured_route_model().strip().lower()
        return model if _looks_official_model(model) else ""

    def _send_local_websocket_accept(self, selected_protocol: str = "") -> None:
        key = (self.headers.get("Sec-WebSocket-Key") or "").strip()
        if not key:
            raise OSError("missing Sec-WebSocket-Key for local re-attach")
        accept = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        response = [
            b"HTTP/1.1 101 Switching Protocols\r\n",
            b"Upgrade: websocket\r\n",
            b"Connection: Upgrade\r\n",
            f"Sec-WebSocket-Accept: {accept}\r\n".encode("ascii"),
        ]
        if selected_protocol:
            response.append(
                f"Sec-WebSocket-Protocol: {selected_protocol}\r\n".encode("latin-1")
            )
        response.append(b"\r\n")
        self.connection.sendall(b"".join(response))

    def _official_live_client_pump(self, session: PersistentOfficialSession) -> None:
        client_reader = BufferedSocketReader(self.connection)
        fragmented_text: bytearray | None = None
        try:
            while not session.closed.is_set():
                fin, opcode, payload, rsv_bits = read_ws_frame(client_reader)
                if rsv_bits:
                    raise OSError(
                        "compressed/extended WebSocket frames are unsupported; "
                        "the bridge disables Sec-WebSocket-Extensions during handshake"
                    )
                if opcode == WS_CLOSE:
                    return
                if opcode == WS_PING:
                    try:
                        self.connection.sendall(
                            encode_ws_frame(True, WS_PONG, payload, masked=False)
                        )
                    except OSError:
                        return
                    continue
                if opcode == WS_PONG:
                    continue

                if opcode == WS_TEXT:
                    if fin:
                        message = payload
                    else:
                        fragmented_text = bytearray(payload)
                        continue
                elif opcode == WS_CONTINUATION and fragmented_text is not None:
                    fragmented_text.extend(payload)
                    if not fin:
                        continue
                    message = bytes(fragmented_text)
                    fragmented_text = None
                else:
                    session.send_upstream(
                        encode_ws_frame(
                            fin, opcode, payload, masked=True, rsv_bits=rsv_bits
                        )
                    )
                    continue

                outgoing = message
                try:
                    decoded = json.loads(message.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    decoded = None

                is_response_create = (
                    isinstance(decoded, dict)
                    and decoded.get("type") == "response.create"
                )

                # A restart can open the direct Official WS while the first empty
                # bootstrap request still carries the previously selected third-party
                # model. Never send that stale model name to ChatGPT Official.
                if is_response_create and isinstance(decoded, dict):
                    bootstrap_model = decoded.get("model")
                    if not _looks_official_model(bootstrap_model):
                        configured_bootstrap_model = self._configured_route_model()
                        if _looks_official_model(configured_bootstrap_model):
                            decoded = dict(decoded)
                            decoded["model"] = configured_bootstrap_model
                            outgoing = json.dumps(
                                decoded, ensure_ascii=False, separators=(",", ":")
                            ).encode("utf-8")
                            self.log_message(
                                "Repaired stale Official WS bootstrap model: %s -> %s",
                                bootstrap_model or "-",
                                configured_bootstrap_model,
                            )

                matched_restart_replay = False

                # v2.9 restart isolation: a new Codex WebSocket always begins on its
                # own bootstrap Official socket.  Only when a meaningful replay arrives
                # do we look for a detached resident socket whose *completed provider
                # state* is a semantic prefix of this replay.  Empty startup probes and
                # background requests can therefore never steal the conversation socket.
                if is_response_create and _payload_has_conversation_work(decoded):
                    raw_items = decoded.get("input")
                    raw_model = decoded.get("model")
                    configured_model = self._configured_route_model()
                    probe_model = raw_model if _looks_official_model(raw_model) else configured_model
                    if (
                        isinstance(raw_items, list)
                        and raw_items
                        and _looks_official_model(probe_model)
                        and not _looks_internal_official_model(probe_model)
                    ):
                        canonical_probe = _portableize_state_items(raw_items)
                        continuation_key = _provider_state_key(probe_model, "official")
                        fingerprint = _conversation_fingerprint(canonical_probe)
                        pool = self.server.official_live_sessions  # type: ignore[attr-defined]

                        if not session.classified and session.is_idle():
                            matched = pool.find_match(
                                continuation_key,
                                canonical_probe,
                                session.selected_protocol,
                                exclude=session,
                            )
                            if matched is not None:
                                bootstrap = session
                                bootstrap.detach(self.connection)
                                matched.attach(self.connection)
                                session = matched
                                bootstrap.close()
                                matched_restart_replay = True
                                self.log_message(
                                    "Matched restart replay to resident Official session; "
                                    "resident=%s; fingerprint=%s; provider_state=%s; "
                                    "resident_pool=%d",
                                    session.key,
                                    session.conversation_fingerprint or fingerprint or "-",
                                    continuation_key,
                                    pool.count(),
                                )
                            else:
                                session.mark_conversation(probe_model, fingerprint)
                                pool.put(session)
                                self.log_message(
                                    "Promoted bootstrap Official WS to resident conversation; "
                                    "resident=%s; fingerprint=%s; provider_state=%s; "
                                    "resident_pool=%d",
                                    session.key,
                                    session.conversation_fingerprint or "-",
                                    continuation_key,
                                    pool.count(),
                                )
                        elif session.classified:
                            session.mark_conversation(probe_model, fingerprint)

                if decoded is not None:
                    rewritten, meta = prepare_ws_response_create(
                        decoded,
                        session.state,
                        self.server.model_override,  # type: ignore[attr-defined]
                        self.server.prompt_cache_optimization and not self.server.explicit_cache_rejected,  # type: ignore[attr-defined]
                        self.server.switch_replay_compaction,  # type: ignore[attr-defined]
                        self.server.switch_replay_threshold_bytes,  # type: ignore[attr-defined]
                        self.server.switch_replay_recent_user_turns,  # type: ignore[attr-defined]
                        True,
                        self.server.replay_checkpoint_store,  # type: ignore[attr-defined]
                        self.server.provider_continuation_store,  # type: ignore[attr-defined]
                        self.server.provider_continuation_enabled,  # type: ignore[attr-defined]
                        "official",
                        session.live_store,
                        pin_live_restart_instructions=matched_restart_replay,
                    )
                    fallback_payload = meta.pop("_prompt_cache_fallback_payload", None)
                    continuation_fallback_payload = meta.pop("_cross_switch_fallback_payload", None)
                    continuation_response_id = meta.pop("_continuation_response_id", None)
                    continuation_scope = str(meta.pop("_continuation_scope", "live") or "live")
                    continuation_plan = meta.pop("_continuation_plan", None)
                    session.continuation_tracker.note(continuation_plan)
                    if rewritten is not decoded:
                        outgoing = json.dumps(
                            rewritten, ensure_ascii=False, separators=(",", ":")
                        ).encode("utf-8")
                    if fallback_payload is not None:
                        fallback_bytes = json.dumps(
                            fallback_payload, ensure_ascii=False, separators=(",", ":")
                        ).encode("utf-8")
                        with session.cache_fallback_lock:
                            session.cache_fallbacks.append(fallback_bytes)
                    if (
                        continuation_fallback_payload is not None
                        and isinstance(continuation_response_id, str)
                    ):
                        continuation_bytes = json.dumps(
                            continuation_fallback_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        key = str(meta.get("provider_state_key") or "")
                        with session.continuation_fallback_lock:
                            session.continuation_fallbacks.append(
                                (
                                    continuation_bytes,
                                    key,
                                    continuation_response_id,
                                    continuation_scope,
                                )
                            )
                    if is_response_create:
                        self.log_message(
                            "WS response.create mode=%s; client_input_items=%s; upstream_input_items=%s; "
                            "previous_response_id=%s; removed_item_ids=%s; removed_previous_response_id=%s; "
                            "omitted_reasoning_items=%s; omitted_compaction_items=%s; omitted_item_references=%s; "
                            "model_rewritten=%s; replay_bytes=%s->%s; checkpoint_hit=%s; "
                            "provider_state=%s; provider_state_capability=%s; durable_store=%s; "
                            "resident_session=%s; live_session=%s; cross_switch_continuation=%s; "
                            "continuation_prefix_items=%s; continuation_prefix_bytes=%s; "
                            "continuation_delta_items=%s; continuation_delta_bytes=%s; "
                            "instruction_delta_items=%s; instruction_delta_bytes=%s; "
                            "restart_instruction_pin=%s",
                            meta["mode"],
                            meta["client_input_items"],
                            meta["upstream_input_items"],
                            meta["previous_response_id_state"],
                            meta["removed_item_ids"],
                            str(meta["removed_previous_response_id"]).lower(),
                            meta["omitted_reasoning_items"],
                            meta["omitted_compaction_items"],
                            meta["omitted_item_references"],
                            str(meta["model_rewritten"]).lower(),
                            meta["switch_replay_bytes_before"],
                            meta["switch_replay_bytes_after"],
                            str(meta["checkpoint_hit"]).lower(),
                            meta["provider_state_key"],
                            meta["provider_state_capability"],
                            str(meta["durable_store_requested"]).lower(),
                            session.key if session.classified else "bootstrap",
                            str(meta["live_session_continuation"]).lower(),
                            str(meta["cross_switch_continuation"]).lower(),
                            meta["continuation_prefix_items"],
                            meta["continuation_prefix_bytes"],
                            meta["continuation_delta_items"],
                            meta["continuation_delta_bytes"],
                            meta["continuation_instruction_items"],
                            meta["continuation_instruction_bytes"],
                            str(meta["restart_instruction_pin"]).lower(),
                        )

                if is_response_create:
                    session.note_request()
                try:
                    session.send_upstream(
                        encode_ws_frame(True, WS_TEXT, outgoing, masked=True)
                    )
                except OSError:
                    if is_response_create:
                        session.note_completion()
                    raise
        except (EOFError, OSError) as exc:
            if not session.closed.is_set():
                self.log_message("Official live client detached: %s", exc)
        finally:
            session.detach(self.connection)
            # A bootstrap-only socket has no user conversation worth keeping alive.
            # Resident sockets survive the Codex restart and expire only by TTL/upstream.
            if not session.classified:
                session.close()
            self.close_connection = True

    def _official_live_server_pump(self, session: PersistentOfficialSession) -> None:
        fragmented_server_text: bytearray | None = None
        try:
            while not session.closed.is_set():
                if session.is_expired():
                    self.log_message(
                        "Persistent Official session expired after %ss idle: %s",
                        OFFICIAL_LIVE_SESSION_IDLE_TTL_SECONDS,
                        session.key,
                    )
                    break
                try:
                    ready, _, _ = select.select(
                        [session.upstream_socket], [], [], 1.0
                    )
                except (OSError, ValueError):
                    break
                if not ready:
                    continue
                fin, opcode, payload, rsv_bits = read_ws_frame(session.upstream_reader)
                if rsv_bits:
                    raise OSError(
                        "upstream sent compressed/extended WebSocket frames even though "
                        "Sec-WebSocket-Extensions was not negotiated"
                    )
                if opcode == WS_PING:
                    session.send_upstream(
                        encode_ws_frame(True, WS_PONG, payload, masked=True)
                    )
                    continue
                if opcode == WS_PONG:
                    continue

                suppress_frame = False
                complete_message: bytes | None = None
                if opcode == WS_TEXT:
                    if fin:
                        complete_message = payload
                    else:
                        fragmented_server_text = bytearray(payload)
                elif opcode == WS_CONTINUATION and fragmented_server_text is not None:
                    fragmented_server_text.extend(payload)
                    if fin:
                        complete_message = bytes(fragmented_server_text)
                        fragmented_server_text = None

                if complete_message is not None:
                    try:
                        event = json.loads(complete_message.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        event = None
                    if event is not None:
                        if (
                            fin
                            and opcode == WS_TEXT
                            and is_prompt_cache_parameter_rejection_event(event)
                        ):
                            fallback_bytes = None
                            with session.cache_fallback_lock:
                                if session.cache_fallbacks:
                                    fallback_bytes = session.cache_fallbacks.popleft()
                            if fallback_bytes is not None:
                                session.send_upstream(
                                    encode_ws_frame(
                                        True, WS_TEXT, fallback_bytes, masked=True
                                    )
                                )
                                suppress_frame = True
                                self.server.explicit_cache_rejected = True  # type: ignore[attr-defined]
                                self.server.prompt_cache_key_rejected = True  # type: ignore[attr-defined]
                                self.log_message(
                                    "Bridge prompt-cache control rejected by Official backend; retried without bridge cache-control fields"
                                )

                        if (
                            not suppress_frame
                            and fin
                            and opcode == WS_TEXT
                            and is_previous_response_rejection_event(event)
                        ):
                            continuation_entry = None
                            with session.continuation_fallback_lock:
                                if session.continuation_fallbacks:
                                    continuation_entry = session.continuation_fallbacks.popleft()
                            if continuation_entry is not None:
                                (
                                    fallback_bytes,
                                    continuation_key,
                                    stale_response_id,
                                    continuation_scope,
                                ) = continuation_entry
                                session.send_upstream(
                                    encode_ws_frame(
                                        True, WS_TEXT, fallback_bytes, masked=True
                                    )
                                )
                                if continuation_scope == "live":
                                    session.live_store.invalidate(
                                        continuation_key, stale_response_id
                                    )
                                else:
                                    self.server.provider_continuation_store.invalidate(  # type: ignore[attr-defined]
                                        continuation_key, stale_response_id
                                    )
                                suppress_frame = True
                                self.log_message(
                                    "Saved %s previous_response_id rejected; retried complete current replay; stale checkpoint invalidated for %s",
                                    continuation_scope,
                                    continuation_key or "unknown-provider-state",
                                )

                        if not suppress_frame:
                            session.state.record_server_event(event)
                            session.continuation_tracker.handle_event(
                                event,
                                self.server.provider_continuation_store,  # type: ignore[attr-defined]
                                session.live_store,
                            )
                            event_type = str(event.get("type", ""))
                            if event_type == "response.created":
                                with session.cache_fallback_lock:
                                    if session.cache_fallbacks:
                                        session.cache_fallbacks.popleft()
                                with session.continuation_fallback_lock:
                                    if session.continuation_fallbacks:
                                        session.continuation_fallbacks.popleft()
                            if _is_response_completion_event(event) or event_type in {
                                "response.failed", "response.error", "error"
                            }:
                                session.note_completion()

                if opcode == WS_CLOSE:
                    session.send_client(
                        encode_ws_frame(True, WS_CLOSE, payload, masked=False)
                    )
                    break
                if not suppress_frame:
                    session.send_client(
                        encode_ws_frame(
                            fin, opcode, payload, masked=False, rsv_bits=rsv_bits
                        )
                    )
        except (EOFError, OSError) as exc:
            if not session.closed.is_set():
                self.log_message("Persistent Official upstream closed: %s", exc)
        finally:
            session.close()
            self.server.official_live_sessions.remove(session.key, session)  # type: ignore[attr-defined]
            creates, full_replays, native_incremental, response_ids, item_ids = (
                session.state.snapshot_counts()
            )
            self.log_message(
                "Persistent Official session closed; key=%s; response_create=%d; "
                "native_full_replay=%d; native_incremental=%d; trusted_response_ids=%d; trusted_item_ids=%d",
                session.key,
                creates,
                full_replays,
                native_incremental,
                response_ids,
                item_ids,
            )

    def _proxy_persistent_official_websocket(self) -> None:
        """Start every Codex WS on an isolated Official bootstrap socket.

        The client pump promotes this socket only after it sees meaningful conversation
        work.  If that replay extends a detached resident session, the client is migrated
        to the old upstream before the replay is sent, so restart-generated history can
        become previous_response_id + delta without attaching startup/background probes.
        """
        upstream_socket: socket.socket | None = None
        try:
            upstream_socket, header_bytes, buffered, status, ws_upstream = (
                self._open_websocket_upstream(True)
            )
            header_bytes = strip_websocket_extensions(header_bytes)
            self.connection.sendall(header_bytes)
            if status != 101:
                if buffered:
                    self.connection.sendall(buffered)
                while True:
                    chunk = upstream_socket.recv(65536)
                    if not chunk:
                        break
                    self.connection.sendall(chunk)
                return

            self.connection.settimeout(None)
            upstream_socket.settimeout(None)
            reader = BufferedSocketReader(upstream_socket, buffered)
            selected_protocol = _websocket_response_header_value(
                header_bytes, "Sec-WebSocket-Protocol"
            )
            bootstrap_key = "bootstrap-" + os.urandom(8).hex()
            session = PersistentOfficialSession(
                bootstrap_key, upstream_socket, reader, selected_protocol
            )
            session.attach(self.connection)
            session.pump_thread = threading.Thread(
                target=self._official_live_server_pump,
                args=(session,),
                daemon=True,
                name=f"cpb-official-live-{bootstrap_key[-12:]}",
            )
            session.pump_thread.start()
            self.log_message(
                "%s %s -> 101; websocket_proxy=true; responses_adaptation=true; "
                "ws_upstream=%s; official_bootstrap_session=true; resident_pool=%d",
                self.command,
                self.path,
                ws_upstream,
                self.server.official_live_sessions.count(),  # type: ignore[attr-defined]
            )
            self._official_live_client_pump(session)
        except OSError as exc:
            if upstream_socket is not None:
                try:
                    upstream_socket.close()
                except OSError:
                    pass
            if not self.wfile.closed:
                try:
                    self._safe_send_error(502, f"Responses WebSocket upstream error: {exc}")
                except OSError:
                    pass
            else:
                self.log_message("Persistent Official WS proxy error: %s", exc)
        finally:
            self.close_connection = True

    def _proxy_websocket(self) -> None:
        if self._is_responses_path() and self._route_looks_official():
            self._proxy_persistent_official_websocket()
            return
        self._proxy_websocket_legacy()

    def _proxy_websocket_legacy(self) -> None:
        """Proxy WebSocket traffic while preserving native Codex token semantics.

        Full canonical-history frames are expected at the start of Codex turns
        and are sanitized deterministically. Same-turn incremental frames that carry
        a trusted upstream `previous_response_id` are passed through as-is. A guarded
        per-model cross-switch continuation may also replace a full replay with only
        its exact portable suffix; rejection falls back to the full replay.
        """
        upstream_socket: socket.socket | None = None
        sent_response = False
        stop_event = threading.Event()
        state = WebSocketContinuationState()
        try:
            responses_mode = self._is_responses_path()
            if responses_mode and not self._route_looks_official():
                body = b"Responses WebSocket disabled for third-party route; use HTTP /responses."
                response = (
                    b"HTTP/1.1 405 Method Not Allowed\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    b"Allow: POST\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode("ascii")
                    + b"Connection: close\r\n\r\n"
                    + body
                )
                self.connection.sendall(response)
                sent_response = True
                self.log_message(
                    "Third-party Responses WS skipped locally; HTTP /responses required"
                )
                return
            upstream_socket, header_bytes, buffered, status, ws_upstream = (
                self._open_websocket_upstream(responses_mode)
            )

            # The bridge intentionally declines per-message compression because it
            # needs to inspect client JSON frames. The upstream request omitted the
            # extension too, so a conforming peer will not compress frames.
            header_bytes = strip_websocket_extensions(header_bytes)
            self.connection.sendall(header_bytes)
            sent_response = True

            if status != 101:
                if buffered:
                    self.connection.sendall(buffered)
                while True:
                    chunk = upstream_socket.recv(65536)
                    if not chunk:
                        break
                    self.connection.sendall(chunk)
                self.log_message(
                    "%s %s -> %s; websocket_upgrade=false",
                    self.command,
                    self.path,
                    status,
                )
                return

            self.log_message(
                "%s %s -> 101; websocket_proxy=true; responses_adaptation=%s; ws_upstream=%s",
                self.command,
                self.path,
                str(responses_mode).lower(),
                ws_upstream,
            )
            self.connection.settimeout(None)
            upstream_socket.settimeout(None)
            client_reader = BufferedSocketReader(self.connection)
            upstream_reader = BufferedSocketReader(upstream_socket, buffered)
            cache_fallback_lock = threading.Lock()
            cache_fallbacks: deque[bytes] = deque()
            continuation_fallback_lock = threading.Lock()
            continuation_fallbacks: deque[tuple[bytes, str, str]] = deque()
            store_fallback_lock = threading.Lock()
            store_fallbacks: deque[tuple[bytes, str]] = deque()
            continuation_tracker = ContinuationRequestTracker()

            def stop_sockets() -> None:
                if stop_event.is_set():
                    return
                stop_event.set()
                for sock in (self.connection, upstream_socket):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            def client_to_upstream() -> None:
                fragmented_text: bytearray | None = None
                try:
                    while not stop_event.is_set():
                        fin, opcode, payload, rsv_bits = read_ws_frame(client_reader)
                        if rsv_bits:
                            raise OSError(
                                "compressed/extended WebSocket frames are unsupported; "
                                "the bridge disables Sec-WebSocket-Extensions during handshake"
                            )

                        if opcode == WS_TEXT:
                            if fin:
                                message = payload
                            else:
                                fragmented_text = bytearray(payload)
                                continue
                        elif opcode == WS_CONTINUATION and fragmented_text is not None:
                            fragmented_text.extend(payload)
                            if not fin:
                                continue
                            message = bytes(fragmented_text)
                            fragmented_text = None
                        else:
                            upstream_socket.sendall(
                                encode_ws_frame(
                                    fin,
                                    opcode,
                                    payload,
                                    masked=True,
                                    rsv_bits=rsv_bits,
                                )
                            )
                            if opcode == WS_CLOSE:
                                return
                            continue

                        outgoing = message
                        if responses_mode:
                            try:
                                decoded = json.loads(message.decode("utf-8"))
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                decoded = None
                            if decoded is not None:
                                route_official = self._route_looks_official()
                                # A direct Official WS cannot safely carry a request after
                                # CC Switch has moved to a third-party route. Close it before
                                # forwarding the stale frame; Codex then retries through the
                                # bridge and receives the local HTTP-only third-party policy.
                                if (
                                    responses_mode
                                    and isinstance(decoded, dict)
                                    and decoded.get("type") == "response.create"
                                    and ws_upstream == "direct-official"
                                    and not route_official
                                    and _payload_has_conversation_work(decoded)
                                ):
                                    self.log_message(
                                        "Hot provider switch detected Official -> third-party; closing stale Official WS before forwarding user request"
                                    )
                                    try:
                                        self.connection.sendall(
                                            encode_ws_frame(
                                                True, WS_CLOSE, (1012).to_bytes(2, "big") + b"provider route changed", masked=False
                                            )
                                        )
                                    except OSError:
                                        pass
                                    stop_sockets()
                                    return

                                decoded, hot_original_model, hot_rewritten, hot_reason = self._hot_switch_rewrite(decoded)
                                if hot_rewritten:
                                    self.log_message(
                                        "Hot provider switch rebound WS user request: %s -> %s (%s)",
                                        hot_original_model or "-",
                                        decoded.get("model", "-") if isinstance(decoded, dict) else "-",
                                        hot_reason,
                                    )
                                dynamic_model_override = self.server.model_override  # type: ignore[attr-defined]
                                # Explicit manager override remains a legacy stale-model
                                # fallback only; hot-switch routing above owns live selection.
                                if hot_rewritten:
                                    dynamic_model_override = ""
                                rewritten, meta = prepare_ws_response_create(
                                    decoded,
                                    state,
                                    dynamic_model_override,
                                    self.server.prompt_cache_optimization and not self.server.explicit_cache_rejected,  # type: ignore[attr-defined]
                                    self.server.switch_replay_compaction,  # type: ignore[attr-defined]
                                    self.server.switch_replay_threshold_bytes,  # type: ignore[attr-defined]
                                    self.server.switch_replay_recent_user_turns,  # type: ignore[attr-defined]
                                    route_official,
                                    self.server.replay_checkpoint_store,  # type: ignore[attr-defined]
                                    self.server.provider_continuation_store,  # type: ignore[attr-defined]
                                    self.server.provider_continuation_enabled,  # type: ignore[attr-defined]
                                    "official" if route_official else "third-party",
                                    None,
                                    route_official and not self.server.prompt_cache_key_rejected,  # type: ignore[attr-defined]
                                )
                                fallback_payload = meta.pop("_prompt_cache_fallback_payload", None)
                                continuation_fallback_payload = meta.pop("_cross_switch_fallback_payload", None)
                                continuation_response_id = meta.pop("_continuation_response_id", None)
                                store_fallback_payload = meta.pop("_durable_store_fallback_payload", None)
                                store_fallback_key = str(meta.pop("_durable_store_key", "") or "")
                                continuation_plan = meta.pop("_continuation_plan", None)
                                continuation_tracker.note(continuation_plan)
                                if rewritten is not decoded:
                                    outgoing = json.dumps(
                                        rewritten,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                if fallback_payload is not None:
                                    fallback_bytes = json.dumps(
                                        fallback_payload,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                    with cache_fallback_lock:
                                        cache_fallbacks.append(fallback_bytes)
                                if store_fallback_payload is not None and store_fallback_key:
                                    store_bytes = json.dumps(
                                        store_fallback_payload,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                    with store_fallback_lock:
                                        store_fallbacks.append((store_bytes, store_fallback_key))
                                if (
                                    continuation_fallback_payload is not None
                                    and isinstance(continuation_response_id, str)
                                ):
                                    continuation_bytes = json.dumps(
                                        continuation_fallback_payload,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                    key = str(meta.get("provider_state_key") or "")
                                    with continuation_fallback_lock:
                                        continuation_fallbacks.append(
                                            (continuation_bytes, key, continuation_response_id)
                                        )
                                if isinstance(decoded, dict) and decoded.get("type") == "response.create":
                                    self.log_message(
                                        "WS response.create mode=%s; client_input_items=%s; "
                                        "upstream_input_items=%s; previous_response_id=%s; "
                                        "removed_item_ids=%s; removed_previous_response_id=%s; "
                                        "omitted_reasoning_items=%s; omitted_compaction_items=%s; "
                                        "omitted_item_references=%s; model_rewritten=%s; "
                                        "prompt_cache_breakpoints=%s; prompt_cache_options_added=%s; prompt_cache_key_added=%s; "
                                        "switch_compaction=%s; replay_bytes=%s->%s; "
                                        "checkpoint_hit=%s; checkpoint_prefix_items=%s; checkpoint_prefix_bytes=%s; "
                                        "provider_state=%s; provider_state_capability=%s; durable_store=%s; "
                                        "cross_switch_continuation=%s; continuation_prefix_items=%s; "
                                        "continuation_prefix_bytes=%s; continuation_delta_items=%s; continuation_delta_bytes=%s; "
                                        "instruction_delta_items=%s; instruction_delta_bytes=%s",
                                        meta["mode"],
                                        meta["client_input_items"],
                                        meta["upstream_input_items"],
                                        meta["previous_response_id_state"],
                                        meta["removed_item_ids"],
                                        str(meta["removed_previous_response_id"]).lower(),
                                        meta["omitted_reasoning_items"],
                                        meta["omitted_compaction_items"],
                                        meta["omitted_item_references"],
                                        str(meta["model_rewritten"]).lower(),
                                        meta["prompt_cache_breakpoints_added"],
                                        str(meta["prompt_cache_options_added"]).lower(),
                                        str(meta.get("prompt_cache_key_added", False)).lower(),
                                        str(meta["switch_compaction_applied"]).lower(),
                                        meta["switch_replay_bytes_before"],
                                        meta["switch_replay_bytes_after"],
                                        str(meta["checkpoint_hit"]).lower(),
                                        meta["checkpoint_prefix_items"],
                                        meta["checkpoint_prefix_bytes"],
                                        meta["provider_state_key"],
                                        meta["provider_state_capability"],
                                        str(meta["durable_store_requested"]).lower(),
                                        str(meta["cross_switch_continuation"]).lower(),
                                        meta["continuation_prefix_items"],
                                        meta["continuation_prefix_bytes"],
                                        meta["continuation_delta_items"],
                                        meta["continuation_delta_bytes"],
                                        meta["continuation_instruction_items"],
                                        meta["continuation_instruction_bytes"],
                                    )
                        upstream_socket.sendall(
                            encode_ws_frame(True, WS_TEXT, outgoing, masked=True)
                        )
                except (EOFError, OSError) as exc:
                    if not stop_event.is_set():
                        self.log_message("WebSocket client->upstream closed: %s", exc)
                finally:
                    stop_sockets()

            worker = threading.Thread(target=client_to_upstream, daemon=True)
            worker.start()

            fragmented_server_text: bytearray | None = None
            try:
                while not stop_event.is_set():
                    fin, opcode, payload, rsv_bits = read_ws_frame(upstream_reader)
                    if rsv_bits:
                        raise OSError(
                            "upstream sent compressed/extended WebSocket frames even though "
                            "Sec-WebSocket-Extensions was not negotiated"
                        )
                    suppress_frame = False
                    if responses_mode:
                        complete_message: bytes | None = None
                        if opcode == WS_TEXT:
                            if fin:
                                complete_message = payload
                            else:
                                fragmented_server_text = bytearray(payload)
                        elif opcode == WS_CONTINUATION and fragmented_server_text is not None:
                            fragmented_server_text.extend(payload)
                            if fin:
                                complete_message = bytes(fragmented_server_text)
                                fragmented_server_text = None
                        if complete_message is not None:
                            try:
                                event = json.loads(complete_message.decode("utf-8"))
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                event = None
                            if event is not None:
                                # Explicit cache-control is optional in v2.6; if an
                                # opt-in backend rejects it, retry the same request
                                # without those fields before touching provider state.
                                if (
                                    fin
                                    and opcode == WS_TEXT
                                    and is_prompt_cache_parameter_rejection_event(event)
                                ):
                                    fallback_bytes = None
                                    with cache_fallback_lock:
                                        if cache_fallbacks:
                                            fallback_bytes = cache_fallbacks.popleft()
                                    if fallback_bytes is not None:
                                        upstream_socket.sendall(
                                            encode_ws_frame(True, WS_TEXT, fallback_bytes, masked=True)
                                        )
                                        suppress_frame = True
                                        self.server.explicit_cache_rejected = True  # type: ignore[attr-defined]
                                        self.server.prompt_cache_key_rejected = True  # type: ignore[attr-defined]
                                        self.log_message(
                                            "Bridge prompt-cache control rejected by upstream; retried without bridge cache-control fields"
                                        )

                                # If a saved provider response id expired, catch up by
                                # replaying the complete *current* canonical request with
                                # durable storage still enabled. This preserves continuity
                                # without pruning history.
                                if (
                                    not suppress_frame
                                    and fin
                                    and opcode == WS_TEXT
                                    and is_previous_response_rejection_event(event)
                                ):
                                    continuation_entry = None
                                    with continuation_fallback_lock:
                                        if continuation_fallbacks:
                                            continuation_entry = continuation_fallbacks.popleft()
                                    if continuation_entry is not None:
                                        fallback_bytes, continuation_key, stale_response_id = continuation_entry
                                        upstream_socket.sendall(
                                            encode_ws_frame(True, WS_TEXT, fallback_bytes, masked=True)
                                        )
                                        self.server.provider_continuation_store.invalidate(  # type: ignore[attr-defined]
                                            continuation_key, stale_response_id
                                        )
                                        suppress_frame = True
                                        self.log_message(
                                            "Saved provider previous_response_id rejected; retried complete current replay with durable storage; stale checkpoint invalidated for %s",
                                            continuation_key or "unknown-provider-state",
                                        )

                                # Some providers expose Responses but reject store=true.
                                # Remember that capability and immediately retry a
                                # stateless full/current request, so future switches do
                                # not repeatedly probe an unsupported optimization.
                                if (
                                    not suppress_frame
                                    and fin
                                    and opcode == WS_TEXT
                                    and is_store_parameter_rejection_event(event)
                                ):
                                    store_entry = None
                                    with store_fallback_lock:
                                        if store_fallbacks:
                                            store_entry = store_fallbacks.popleft()
                                    if store_entry is not None:
                                        fallback_bytes, provider_key = store_entry
                                        upstream_socket.sendall(
                                            encode_ws_frame(True, WS_TEXT, fallback_bytes, masked=True)
                                        )
                                        self.server.provider_continuation_store.mark_unsupported(  # type: ignore[attr-defined]
                                            provider_key
                                        )
                                        # Any pending cross-switch fallback for this
                                        # request is now obsolete because the stateless
                                        # full/current request supersedes it.
                                        with continuation_fallback_lock:
                                            if continuation_fallbacks:
                                                continuation_fallbacks.popleft()
                                        suppress_frame = True
                                        self.log_message(
                                            "Durable response storage rejected; provider state marked stateless for this bridge process: %s",
                                            provider_key,
                                        )

                                if not suppress_frame:
                                    state.record_server_event(event)
                                    continuation_tracker.handle_event(
                                        event, self.server.provider_continuation_store  # type: ignore[attr-defined]
                                    )
                                    event_type = str(event.get("type", ""))
                                    if event_type == "response.created":
                                        with cache_fallback_lock:
                                            if cache_fallbacks:
                                                cache_fallbacks.popleft()
                                        with continuation_fallback_lock:
                                            if continuation_fallbacks:
                                                continuation_fallbacks.popleft()
                                        with store_fallback_lock:
                                            if store_fallbacks:
                                                store_fallbacks.popleft()

                    if not suppress_frame:
                        # Preserve streaming latency for all accepted/non-cache-error frames.
                        self.connection.sendall(
                            encode_ws_frame(
                                fin,
                                opcode,
                                payload,
                                masked=False,
                                rsv_bits=rsv_bits,
                            )
                        )

                    if opcode == WS_CLOSE:
                        break
            except (EOFError, OSError) as exc:
                if not stop_event.is_set():
                    self.log_message("WebSocket upstream->client closed: %s", exc)
            finally:
                stop_sockets()
                worker.join(timeout=1.0)

            creates, full_replays, native_incremental, response_ids, item_ids = state.snapshot_counts()
            self.log_message(
                "WebSocket session closed; response_create=%d; native_full_replay=%d; "
                "native_incremental=%d; trusted_response_ids=%d; trusted_item_ids=%d",
                creates,
                full_replays,
                native_incremental,
                response_ids,
                item_ids,
            )
        except OSError as exc:
            if not sent_response:
                self._safe_send_error(502, f"Responses WebSocket upstream error: {exc}")
            else:
                self.log_message("WebSocket proxy error: %s", exc)
        finally:
            self.close_connection = True
            stop_event.set()
            if upstream_socket is not None:
                try:
                    upstream_socket.close()
                except OSError:
                    pass

    def _is_realtime_path(self) -> bool:
        path = self.path.split("?", 1)[0].rstrip("/")
        return path.endswith("/live") or path.endswith("/realtime")

    def _handle(self) -> None:
        # In the intended bridged configuration, realtime voice is routed directly
        # to native OpenAI by Codex and must never inherit this local provider URL.
        # Seeing /live or /realtime here means Codex has not reloaded the manager-
        # written experimental_realtime_* settings yet (or they were overwritten).
        if self._is_realtime_path():
            self.send_error(
                409,
                "Realtime voice must bypass the local bridge. Restart Codex/VS Code "
                "and verify experimental_realtime_ws_base_url and "
                "experimental_realtime_webrtc_call_base_url in user config.toml.",
            )
            return

        if self._is_websocket_upgrade():
            self._proxy_websocket()
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length else b""
        encoding = (self.headers.get("Content-Encoding") or "").lower().strip()

        if encoding and encoding != "identity":
            self.send_error(
                415,
                "Compressed request body is unsupported. Set "
                "[features] enable_request_compression = false in config.toml.",
            )
            return

        removed = 0
        cleared_reasoning_content = 0
        removed_foreign_encrypted_content = 0
        previous_removed = False
        original_payload: object | None = None
        original_model: str | None = None
        model_rewritten = False
        http_bp_added = 0
        http_cache_options_added = False
        http_cache_fallback_payload: object | None = None
        http_switch_compaction_applied = False
        http_replay_bytes_before = 0
        http_replay_bytes_after = 0
        http_deduped_instruction_items = 0
        http_omitted_stale_tool_items = 0
        http_checkpoint_hit = False
        http_checkpoint_prefix_items = 0
        http_checkpoint_prefix_bytes = 0
        http_checkpoint_candidates = 0
        http_checkpoint_pinned_instruction_items = 0
        http_checkpoint_match_mode = "none"
        http_checkpoint_key = "-"
        http_cross_switch_continuation = False
        http_continuation_prefix_items = 0
        http_continuation_prefix_bytes = 0
        http_continuation_delta_items = 0
        http_continuation_delta_bytes = 0
        http_continuation_instruction_items = 0
        http_continuation_instruction_bytes = 0
        http_continuation_fallback_payload: object | None = None
        http_continuation_stale_response_id: str | None = None
        http_continuation_plan_key = ""
        http_continuation_plan_items: list[object] | None = None
        http_continuation_plan_durable = False
        http_provider_state_key = "-"
        http_provider_shadow_fingerprint = "-"
        http_provider_shadow_scope_source = "fallback"
        http_provider_route_serial = self._route_serial()
        http_provider_return_instruction_pin = False
        http_shadow_cursor_committed = False
        http_shadow_safety_reason = "not-evaluated"
        http_shadow_tool_history = False
        http_shadow_tool_chain_closed = True
        http_shadow_instruction_drift = False
        http_shadow_completion_verified = False
        http_provider_state_capability = "disabled"
        http_durable_store_requested = False
        http_store_fallback_payload: object | None = None
        http_prompt_cache_key_added = False
        http_strict_tool_preflight = False
        http_strict_tool_preflight_omitted = 0
        direct_official_internal_http = False
        content_type = (self.headers.get("Content-Type") or "").lower()
        if body and "json" in content_type and self.path.rstrip("/").endswith("responses"):
            try:
                original_payload = json.loads(body.decode("utf-8"))
                route_official = self._route_looks_official()
                original_payload, original_model, hot_rewritten, hot_reason = self._hot_switch_rewrite(
                    original_payload
                )
                model_rewritten = hot_rewritten
                if not hot_rewritten:
                    original_payload, fallback_original_model, fallback_rewritten = override_responses_model(
                        original_payload,
                        self.server.model_override,  # type: ignore[attr-defined]
                        force=route_official,
                    )
                    if original_model is None:
                        original_model = fallback_original_model
                    model_rewritten = fallback_rewritten
                if hot_rewritten:
                    self.log_message(
                        "Hot provider switch rebound HTTP user request: %s -> %s (%s)",
                        original_model or "-",
                        original_payload.get("model", "-") if isinstance(original_payload, dict) else "-",
                        hot_reason,
                    )
                direct_official_internal_http = bool(
                    not route_official
                    and isinstance(original_payload, dict)
                    and _looks_internal_official_model(original_payload.get("model"))
                    and self._is_responses_path()
                )
                if direct_official_internal_http:
                    self.log_message(
                        "Routing internal Official HTTP model directly to ChatGPT backend; "
                        "CC Switch third-party route will not receive model=%s",
                        original_payload.get("model", "-"),
                    )
                (
                    payload,
                    removed,
                    cleared_reasoning_content,
                    removed_foreign_encrypted_content,
                    previous_removed,
                ) = neutralize_responses_payload(original_payload)

                full_replay = (
                    isinstance(payload, dict)
                    and isinstance(payload.get("input"), list)
                    and _is_full_replay_input(payload.get("input"))
                )

                if full_replay and isinstance(payload, dict):
                    current_items = payload["input"]
                    if self.server.switch_replay_compaction:  # type: ignore[attr-defined]
                        compacted_items, compact_meta = compact_switch_replay_items(
                            current_items,
                            threshold_bytes=self.server.switch_replay_threshold_bytes,  # type: ignore[attr-defined]
                            recent_user_turns=self.server.switch_replay_recent_user_turns,  # type: ignore[attr-defined]
                        )
                        payload = dict(payload)
                        payload["input"] = compacted_items
                        current_items = compacted_items
                        http_switch_compaction_applied = bool(compact_meta["applied"])
                        http_replay_bytes_before = int(compact_meta["before_bytes"])
                        http_replay_bytes_after = int(compact_meta["after_bytes"])
                        http_deduped_instruction_items = int(compact_meta["deduped_instruction_items"])
                        http_omitted_stale_tool_items = int(compact_meta["omitted_stale_tool_items"])
                    else:
                        http_replay_bytes_before = sum(_json_size(item) for item in current_items)
                        http_replay_bytes_after = http_replay_bytes_before

                    effective_model = payload.get("model")
                    checkpoint_key = (
                        effective_model.strip().lower()
                        if isinstance(effective_model, str)
                        else ""
                    )
                    if checkpoint_key:
                        # Exact-only prefix stabilization remains available for native
                        # implicit caches; v2.6 no longer pins stale instructions.
                        stabilized_items, checkpoint_meta = self.server.replay_checkpoint_store.stabilize(  # type: ignore[attr-defined]
                            checkpoint_key, payload["input"]
                        )
                        payload = dict(payload)
                        payload["input"] = stabilized_items
                        current_items = stabilized_items
                        http_checkpoint_key = checkpoint_key
                        http_checkpoint_hit = bool(checkpoint_meta["checkpoint_hit"])
                        http_checkpoint_prefix_items = int(checkpoint_meta["checkpoint_prefix_items"])
                        http_checkpoint_prefix_bytes = int(checkpoint_meta["checkpoint_prefix_bytes"])
                        http_checkpoint_candidates = int(checkpoint_meta.get("checkpoint_candidates", 0))
                        http_checkpoint_pinned_instruction_items = 0
                        http_checkpoint_match_mode = str(checkpoint_meta.get("checkpoint_match_mode", "none"))

                    namespace = (
                        "official"
                        if route_official or _looks_official_model(payload.get("model"))
                        else "third-party"
                    )
                    canonical_items = _portableize_state_items(payload["input"])
                    request_scope, http_provider_shadow_scope_source = _codex_thread_scope(self.headers)
                    shadow_key, shadow_fingerprint = _provider_shadow_state_key(
                        payload.get("model"),
                        namespace,
                        canonical_items,
                        request_scope=request_scope,
                    )
                    http_provider_state_key = shadow_key or "-"
                    http_provider_shadow_fingerprint = shadow_fingerprint or "-"
                    if http_provider_state_key != "-":
                        http_provider_state_capability = self.server.provider_continuation_store.capability_state(  # type: ignore[attr-defined]
                            http_provider_state_key
                        )

                    learned_strict_tool_adjacency = bool(
                        namespace == "third-party"
                        and http_provider_state_key != "-"
                        and _timeline_contains_tool_state(canonical_items)
                        and self.server.strict_tool_adjacency_store.requires(  # type: ignore[attr-defined]
                            http_provider_state_key, http_provider_route_serial
                        )
                    )

                    if learned_strict_tool_adjacency:
                        (
                            payload,
                            _strict_removed_ids,
                            http_strict_tool_preflight_omitted,
                            _strict_previous_removed,
                        ) = make_learned_strict_tool_payload(original_payload)
                        http_strict_tool_preflight = True
                        http_shadow_safety_reason = "learned-strict-tool-adjacency"
                        http_shadow_tool_history = _timeline_contains_tool_state(canonical_items)
                        http_shadow_tool_chain_closed = True
                        strict_items = payload.get("input") if isinstance(payload, dict) else None
                        if isinstance(strict_items, list):
                            http_replay_bytes_before = sum(_json_size(item) for item in current_items)
                            http_replay_bytes_after = sum(_json_size(item) for item in strict_items)
                    else:
                        stateless_full_payload = dict(payload)
                        stateless_full_payload["input"] = payload["input"]
                        stateless_full_payload["store"] = False

                        durable_allowed = bool(
                            self.server.provider_continuation_enabled  # type: ignore[attr-defined]
                            and not route_official
                            and not _looks_official_model(payload.get("model"))
                            and http_provider_state_key != "-"
                            and self.server.provider_continuation_store.should_request_durable(  # type: ignore[attr-defined]
                                http_provider_state_key
                            )
                        )
                        if durable_allowed:
                            durable_full_payload = dict(stateless_full_payload)
                            durable_full_payload["store"] = True
                            payload = durable_full_payload
                            http_durable_store_requested = True
                            http_store_fallback_payload = stateless_full_payload
                            http_continuation_plan_key = http_provider_state_key
                            http_continuation_plan_items = canonical_items
                            http_continuation_plan_durable = True

                            shadow_diagnostics: dict[str, object] = {}
                            candidate = self.server.provider_continuation_store.candidate(  # type: ignore[attr-defined]
                                http_provider_state_key,
                                canonical_items,
                                current_route_serial=http_provider_route_serial,
                                allow_provider_return_instruction_pin=(namespace == "third-party"),
                                diagnostics=shadow_diagnostics,
                            )
                            http_shadow_safety_reason = str(shadow_diagnostics.get("reason", "unknown"))
                            http_shadow_tool_history = bool(shadow_diagnostics.get("tool_history", False))
                            http_shadow_tool_chain_closed = bool(shadow_diagnostics.get("tool_chain_closed", True))
                            http_shadow_instruction_drift = bool(shadow_diagnostics.get("instruction_drift", False))
                            http_shadow_completion_verified = bool(shadow_diagnostics.get("completion_verified", False))
                            if candidate is not None:
                                (
                                    saved_response_id,
                                    suffix,
                                    prefix_items,
                                    prefix_bytes,
                                    instruction_items,
                                    instruction_bytes,
                                    candidate_instruction_pin,
                                ) = candidate
                                http_continuation_fallback_payload = durable_full_payload
                                payload = dict(durable_full_payload)
                                payload["input"] = suffix
                                payload["previous_response_id"] = saved_response_id
                                payload["store"] = True
                                http_cross_switch_continuation = True
                                http_continuation_stale_response_id = saved_response_id
                                http_continuation_prefix_items = prefix_items
                                http_continuation_prefix_bytes = prefix_bytes
                                http_continuation_delta_items = len(suffix)
                                http_continuation_delta_bytes = sum(_json_size(item) for item in suffix)
                                http_continuation_instruction_items = instruction_items
                                http_continuation_instruction_bytes = instruction_bytes
                                http_provider_return_instruction_pin = bool(candidate_instruction_pin)
                        else:
                            payload = stateless_full_payload

                if http_strict_tool_preflight:
                    # The successful firewall retry is provider-neutral and stateless. Reuse
                    # exactly that shape on later turns of this conversation instead of first
                    # sending the already-proven-to-fail transcript again.
                    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                else:
                    http_cache_fallback_payload = payload
                    payload, http_bp_added, _http_bp_eligible, http_cache_options_added = apply_stable_prompt_cache_breakpoints(
                        payload,
                        enabled=(
                            self.server.prompt_cache_optimization  # type: ignore[attr-defined]
                            and not self.server.explicit_cache_rejected  # type: ignore[attr-defined]
                        ),
                    )
                    http_namespace = (
                        "official"
                        if route_official or _looks_official_model(payload.get("model") if isinstance(payload, dict) else None)
                        else "third-party"
                    )
                    payload, http_prompt_cache_key_added = apply_prompt_cache_key(
                        payload,
                        enabled=(
                            http_namespace == "official"
                            and not self.server.prompt_cache_key_rejected  # type: ignore[attr-defined]
                        ),
                        namespace=http_namespace,
                    )
                    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.send_error(400, f"Invalid JSON request body: {exc}")
                return

        upstream = self.server.upstream  # type: ignore[attr-defined]
        if direct_official_internal_http:
            upstream = self.server.responses_ws_upstream  # type: ignore[attr-defined]
        comp_hash_guard = (
            self._is_models_path()
            and not self.server.preserve_comp_hash  # type: ignore[attr-defined]
        )
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP or lower in {"host", "content-length", "accept-encoding"}:
                continue
            # Force a fresh /models body while the v2.4 comp-hash guard is
            # active. Reusing an upstream 304 could retain a pre-v2.4 cached
            # catalog that still carries the old Official comp_hash.
            if comp_hash_guard and lower in {"if-none-match", "if-modified-since"}:
                continue
            headers[key] = value
        # Error bodies must remain inspectable so the bridge can decide whether
        # a portable retry is appropriate.
        headers["Accept-Encoding"] = "identity"

        upstream_path = (
            self._direct_responses_ws_path()
            if direct_official_internal_http
            else self._upstream_path()
        )

        connection: http.client.HTTPConnection | None = None
        response_started = False
        buffered_response: bytes | None = None
        portable_retry = False
        omitted_provider_items = 0
        comp_hash_neutralized = 0
        comp_hash_model_entries = 0
        model_catalog_json_parsed = False
        catalog_body_modified = False
        try:
            request_headers = dict(headers)
            if body:
                request_headers["Content-Length"] = str(len(body))
            connection = self._make_http_connection(upstream)
            connection.request(
                self.command,
                upstream_path,
                body=body or None,
                headers=request_headers,
            )
            response = connection.getresponse()

            # A rejected request has not produced a model response, so guarded
            # compatibility retries are safe. v2.6 resolves errors from least semantic
            # to most stateful: cache syntax -> stale provider response id -> durable
            # store capability -> generic provider-portability fallback.
            if original_payload is not None and response.status in {400, 422}:
                if http_strict_tool_preflight:
                    if self.server.strict_tool_adjacency_store.forget(  # type: ignore[attr-defined]
                        http_provider_state_key, http_provider_route_serial
                    ):
                        self.log_message(
                            "Learned strict-tool preflight was rejected; capability forgotten for %s at route_serial=%s",
                            http_provider_state_key,
                            http_provider_route_serial,
                        )
                first_error = response.read()

                if (
                    response.status == 400
                    and (http_bp_added > 0 or http_prompt_cache_key_added)
                    and http_cache_fallback_payload is not None
                    and is_prompt_cache_parameter_rejection_body(response.status, first_error)
                ):
                    connection.close()
                    fallback_body = json.dumps(
                        http_cache_fallback_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    retry_headers = dict(headers)
                    retry_headers["Content-Length"] = str(len(fallback_body))
                    connection = self._make_http_connection(upstream)
                    connection.request(
                        self.command, upstream_path, body=fallback_body, headers=retry_headers
                    )
                    response = connection.getresponse()
                    if http_bp_added > 0:
                        self.server.explicit_cache_rejected = True  # type: ignore[attr-defined]
                    if http_prompt_cache_key_added:
                        self.server.prompt_cache_key_rejected = True  # type: ignore[attr-defined]
                    self.log_message(
                        "Prompt-cache control rejected by upstream; HTTP retry sent without bridge cache fields"
                    )
                    first_error = (
                        response.read() if response.status in {400, 422} else b""
                    )

                if (
                    response.status in {400, 422}
                    and http_cross_switch_continuation
                    and http_continuation_fallback_payload is not None
                    and is_previous_response_rejection_body(response.status, first_error)
                ):
                    connection.close()
                    fallback_body = json.dumps(
                        http_continuation_fallback_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    retry_headers = dict(headers)
                    retry_headers["Content-Length"] = str(len(fallback_body))
                    connection = self._make_http_connection(upstream)
                    connection.request(
                        self.command, upstream_path, body=fallback_body, headers=retry_headers
                    )
                    response = connection.getresponse()
                    self.server.provider_continuation_store.invalidate(  # type: ignore[attr-defined]
                        http_continuation_plan_key,
                        http_continuation_stale_response_id,
                    )
                    self.log_message(
                        "Saved provider previous_response_id rejected; retried complete current replay with durable storage; stale checkpoint invalidated for %s",
                        http_continuation_plan_key or "unknown-provider-state",
                    )
                    first_error = (
                        response.read() if response.status in {400, 422} else b""
                    )
                    http_cross_switch_continuation = False

                if (
                    response.status in {400, 422}
                    and http_durable_store_requested
                    and http_store_fallback_payload is not None
                    and is_store_parameter_rejection_body(response.status, first_error)
                ):
                    connection.close()
                    fallback_body = json.dumps(
                        http_store_fallback_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    retry_headers = dict(headers)
                    retry_headers["Content-Length"] = str(len(fallback_body))
                    connection = self._make_http_connection(upstream)
                    connection.request(
                        self.command, upstream_path, body=fallback_body, headers=retry_headers
                    )
                    response = connection.getresponse()
                    if http_continuation_plan_key:
                        self.server.provider_continuation_store.mark_unsupported(  # type: ignore[attr-defined]
                            http_continuation_plan_key
                        )
                    http_provider_state_capability = "unsupported"
                    http_continuation_plan_durable = False
                    http_cross_switch_continuation = False
                    self.log_message(
                        "Durable response storage rejected by upstream; provider state marked stateless for this bridge process: %s",
                        http_continuation_plan_key or http_provider_state_key,
                    )
                    first_error = (
                        response.read() if response.status in {400, 422} else b""
                    )

                if response.status in {400, 422} and is_portability_error(response.status, first_error):
                    rejected_status = response.status
                    strict_tool_rejection = _strict_tool_adjacency_error(first_error)
                    connection.close()
                    portable_payload, _, omitted_provider_items, _ = (
                        make_portable_responses_payload(
                            original_payload, error_body=first_error
                        )
                    )
                    portable_body = json.dumps(
                        portable_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    retry_headers = dict(headers)
                    retry_headers["Content-Length"] = str(len(portable_body))
                    connection = self._make_http_connection(upstream)
                    connection.request(
                        self.command,
                        upstream_path,
                        body=portable_body,
                        headers=retry_headers,
                    )
                    response = connection.getresponse()
                    portable_retry = True
                    http_continuation_plan_durable = False
                    if (
                        strict_tool_rejection
                        and 200 <= response.status < 300
                        and http_provider_state_key != "-"
                    ):
                        learned_now = self.server.strict_tool_adjacency_store.mark_required(  # type: ignore[attr-defined]
                            http_provider_state_key, http_provider_route_serial
                        )
                        if learned_now:
                            self.log_message(
                                "Strict tool adjacency capability learned for %s at route_serial=%s; future turns in this conversation will use the proven portable repair directly",
                                http_provider_state_key,
                                http_provider_route_serial,
                            )
                    self.log_message(
                        "Compatibility firewall activated after upstream HTTP %s; "
                        "sent one provider-neutral stateless replay; omitted_provider_items=%s; retry_status=%s",
                        rejected_status,
                        omitted_provider_items,
                        response.status,
                    )
                elif response.status in {400, 422}:
                    buffered_response = first_error

            if comp_hash_guard and response.status == 200:
                catalog_body = response.read()
                (
                    patched_catalog_body,
                    comp_hash_neutralized,
                    comp_hash_model_entries,
                    model_catalog_json_parsed,
                ) = neutralize_model_catalog_comp_hash(catalog_body)
                catalog_body_modified = patched_catalog_body != catalog_body
                buffered_response = patched_catalog_body

            continuation_collector = None
            if (
                response.status == 200
                and http_continuation_plan_key
                and http_continuation_plan_items is not None
                and self._is_responses_path()
            ):
                continuation_collector = HttpContinuationCollector(
                    http_continuation_plan_key,
                    http_continuation_plan_items,
                    self.server.provider_continuation_store,  # type: ignore[attr-defined]
                    durable=http_continuation_plan_durable,
                    route_serial=http_provider_route_serial,
                )

            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                lower = key.lower()
                if lower in HOP_BY_HOP or lower == "content-length":
                    continue
                if catalog_body_modified and lower in {"etag", "content-md5", "digest"}:
                    continue
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            response_started = True

            if buffered_response is not None:
                if continuation_collector is not None:
                    continuation_collector.feed(buffered_response)
                self.wfile.write(buffered_response)
                self.wfile.flush()
            else:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    if continuation_collector is not None:
                        continuation_collector.feed(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            if continuation_collector is not None:
                continuation_collector.finish()
                http_shadow_cursor_committed = bool(continuation_collector.committed)
            if http_provider_state_key != "-":
                http_provider_state_capability = self.server.provider_continuation_store.capability_state(  # type: ignore[attr-defined]
                    http_provider_state_key
                )
            self.close_connection = True
            self.log_message(
                "%s %s -> %s; removed_item_ids=%d; "
                "model_override=%s; model_rewritten=%s; original_model=%s; "
                "cleared_reasoning_content=%d; removed_foreign_encrypted_content=%d; "
                "removed_previous_response_id=%s; portable_retry=%s; omitted_provider_items=%d; "
                "strict_tool_preflight=%s; strict_tool_preflight_omitted=%d; "
                "comp_hash_guard=%s; comp_hash_model_entries=%d; comp_hash_neutralized=%d; "
                "switch_compaction=%s; replay_bytes=%d->%d; "
                "checkpoint_hit=%s; checkpoint_prefix_items=%d; checkpoint_prefix_bytes=%d; prompt_cache_key_added=%s; "
                "provider_state=%s; shadow_fingerprint=%s; shadow_scope_source=%s; route_serial=%d; provider_state_capability=%s; durable_store=%s; shadow_cursor_committed=%s; "
                "shadow_safety_reason=%s; shadow_tool_history=%s; shadow_tool_chain_closed=%s; shadow_instruction_drift=%s; shadow_completion_verified=%s; "
                "cross_switch_continuation=%s; provider_return_instruction_pin=%s; continuation_prefix_items=%d; continuation_prefix_bytes=%d; "
                "continuation_delta_items=%d; continuation_delta_bytes=%d; "
                "instruction_delta_items=%d; instruction_delta_bytes=%d; http_upstream=%s",
                self.command,
                self.path,
                response.status,
                removed,
                self.server.model_override or "-",  # type: ignore[attr-defined]
                str(model_rewritten).lower(),
                original_model or "-",
                cleared_reasoning_content,
                removed_foreign_encrypted_content,
                str(previous_removed).lower(),
                str(portable_retry).lower(),
                omitted_provider_items,
                str(http_strict_tool_preflight).lower(),
                http_strict_tool_preflight_omitted,
                str(comp_hash_guard).lower(),
                comp_hash_model_entries,
                comp_hash_neutralized,
                str(http_switch_compaction_applied).lower(),
                http_replay_bytes_before,
                http_replay_bytes_after,
                str(http_checkpoint_hit).lower(),
                http_checkpoint_prefix_items,
                http_checkpoint_prefix_bytes,
                str(http_prompt_cache_key_added).lower(),
                http_provider_state_key,
                http_provider_shadow_fingerprint,
                http_provider_shadow_scope_source,
                http_provider_route_serial,
                http_provider_state_capability,
                str(http_durable_store_requested).lower(),
                str(http_shadow_cursor_committed).lower(),
                http_shadow_safety_reason,
                str(http_shadow_tool_history).lower(),
                str(http_shadow_tool_chain_closed).lower(),
                str(http_shadow_instruction_drift).lower(),
                str(http_shadow_completion_verified).lower(),
                str(http_cross_switch_continuation).lower(),
                str(http_provider_return_instruction_pin).lower(),
                http_continuation_prefix_items,
                http_continuation_prefix_bytes,
                http_continuation_delta_items,
                http_continuation_delta_bytes,
                http_continuation_instruction_items,
                http_continuation_instruction_bytes,
                "direct-official-internal" if direct_official_internal_http else "cc-switch",
            )
        except (OSError, http.client.HTTPException) as exc:
            upstream_label = "Direct Official" if direct_official_internal_http else "CC Switch"
            if response_started:
                self.log_message("%s upstream/stream reset after response started: %s", upstream_label, exc)
                self.close_connection = True
            else:
                self._safe_send_error(502, f"{upstream_label} upstream error: {exc}")
        finally:
            if connection is not None:
                connection.close()

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_OPTIONS = _handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adapt Codex Responses history across providers before forwarding "
            "to CC Switch."
        )
    )
    parser.add_argument("--listen", default="127.0.0.1:15722", help="listen host:port")
    parser.add_argument(
        "--upstream",
        default="http://127.0.0.1:15721",
        help="CC Switch proxy base URL",
    )
    parser.add_argument(
        "--responses-ws-upstream",
        default="https://chatgpt.com/backend-api/codex",
        help=(
            "Direct OpenAI Official base URL used when the local CC Switch route "
            "does not accept Responses WebSocket upgrades"
        ),
    )
    parser.add_argument(
        "--model-override",
        default="",
        help=(
            "Optional official model to write into every JSON /responses "
            "replay request (for example gpt-5.6-sol)"
        ),
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--enable-prompt-cache-optimization",
        action="store_true",
        help="Opt in to legacy explicit GPT-5.6 cache-control breakpoints; native implicit caching is always available",
    )
    cache_group.add_argument(
        "--disable-prompt-cache-optimization",
        action="store_true",
        help="Compatibility alias; explicit cache-control is already disabled by default in v2.6",
    )
    compact_group = parser.add_mutually_exclusive_group()
    compact_group.add_argument(
        "--enable-switch-replay-compaction",
        action="store_true",
        help="Opt in to conservative replay pruning; disabled by default in v2.6",
    )
    compact_group.add_argument(
        "--disable-switch-replay-compaction",
        action="store_true",
        help="Compatibility alias; replay pruning is already disabled by default in v2.6",
    )
    parser.add_argument(
        "--disable-provider-continuation",
        action="store_true",
        help="Disable provider-local continuation fallback; hot model routing remains enabled",
    )
    parser.add_argument(
        "--switch-replay-threshold-bytes",
        type=int,
        default=SWITCH_REPLAY_DEFAULT_THRESHOLD_BYTES,
        help="Apply replay compaction only when portable input items reach this serialized size",
    )
    parser.add_argument(
        "--switch-replay-recent-user-turns",
        type=int,
        default=SWITCH_REPLAY_DEFAULT_RECENT_USER_TURNS,
        help="Always preserve tool records associated with this many most recent user turns",
    )
    parser.add_argument(
        "--preserve-comp-hash",
        action="store_true",
        help=(
            "Disable the v2.4 cross-provider CompHashChanged guard and pass "
            "all upstream /models comp_hash values through unchanged"
        ),
    )
    parser.add_argument("--codex-config", default="", help="Codex config.toml watched for provider-switch catalog rewrites")
    parser.add_argument("--bundled-neutral-catalog", default="", help="Bridge-owned hash-neutral bundled model catalog")
    parser.add_argument("--active-neutral-catalog", default="", help="Bridge-owned neutral mirror for provider-managed catalogs")
    parser.add_argument("--official-provider-id", default="cc-switch-official", help="Provider ID treated as the Official route")
    parser.add_argument("--bridge-provider-id", default="custom", help="Provider ID used by the local bridge route")
    parser.add_argument("--bridge-provider-name", default="OpenAI", help="Display name for the local bridge provider table")
    parser.add_argument("--bridge-base-url", default="", help="Expected local bridge provider base URL used to identify bridge mode")
    parser.add_argument("--realtime-ws-base-url", default="https://api.openai.com/v1", help="Realtime sideband URL restored for Official bridge config")
    parser.add_argument("--realtime-webrtc-call-base-url", default="https://chatgpt.com/backend-api/codex", help="Realtime call-creation URL restored for Official bridge config")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    listen_host, listen_port_text = args.listen.rsplit(":", 1)
    upstream = urlsplit(args.upstream)
    if upstream.scheme != "http" or not upstream.hostname:
        raise SystemExit("--upstream must be an http:// URL")
    if upstream.port is None:
        upstream = urlsplit(f"http://{upstream.hostname}:80{upstream.path}")

    responses_ws_upstream = urlsplit(args.responses_ws_upstream)
    if responses_ws_upstream.scheme not in {"http", "https"} or not responses_ws_upstream.hostname:
        raise SystemExit("--responses-ws-upstream must be an http:// or https:// URL")
    direct_host = responses_ws_upstream.hostname.lower()
    direct_is_loopback = direct_host in {"127.0.0.1", "localhost", "::1"}
    if not direct_is_loopback and not (
        responses_ws_upstream.scheme == "https" and direct_host == "chatgpt.com"
    ):
        raise SystemExit(
            "--responses-ws-upstream may target only https://chatgpt.com/... "
            "(loopback http(s) is allowed for local tests) because Codex auth "
            "headers are forwarded to this endpoint"
        )

    server = ThreadingHTTPServer((listen_host, int(listen_port_text)), BridgeHandler)
    server.daemon_threads = True
    server.upstream = upstream  # type: ignore[attr-defined]
    server.responses_ws_upstream = responses_ws_upstream  # type: ignore[attr-defined]
    server.model_override = args.model_override.strip()  # type: ignore[attr-defined]
    server.codex_config_path = args.codex_config.strip()  # type: ignore[attr-defined]
    server.replay_checkpoint_store = ReplayPrefixCheckpointStore()  # type: ignore[attr-defined]
    server.provider_continuation_store = ProviderContinuationStore()  # type: ignore[attr-defined]
    server.strict_tool_adjacency_store = StrictToolAdjacencyCapabilityStore()  # type: ignore[attr-defined]
    server.official_live_sessions = OfficialLiveSessionPool()  # type: ignore[attr-defined]
    server.hot_switch_route_state = HotSwitchRouteState()  # type: ignore[attr-defined]
    server.provider_continuation_enabled = not bool(args.disable_provider_continuation)  # type: ignore[attr-defined]
    server.prompt_cache_optimization = bool(args.enable_prompt_cache_optimization) and not bool(args.disable_prompt_cache_optimization)  # type: ignore[attr-defined]
    server.explicit_cache_rejected = False  # type: ignore[attr-defined]
    server.prompt_cache_key_rejected = False  # type: ignore[attr-defined]
    server.switch_replay_compaction = bool(args.enable_switch_replay_compaction) and not bool(args.disable_switch_replay_compaction)  # type: ignore[attr-defined]
    server.switch_replay_threshold_bytes = max(0, int(args.switch_replay_threshold_bytes))  # type: ignore[attr-defined]
    server.switch_replay_recent_user_turns = max(1, int(args.switch_replay_recent_user_turns))  # type: ignore[attr-defined]
    server.preserve_comp_hash = bool(args.preserve_comp_hash)  # type: ignore[attr-defined]
    server.catalog_guard = None  # type: ignore[attr-defined]

    catalog_guard: CatalogConfigGuard | None = None
    if (
        not args.preserve_comp_hash
        and args.codex_config
        and args.bundled_neutral_catalog
        and args.active_neutral_catalog
        and args.bridge_base_url
    ):
        catalog_guard = CatalogConfigGuard(
            config_path=args.codex_config,
            bundled_catalog_path=args.bundled_neutral_catalog,
            active_catalog_path=args.active_neutral_catalog,
            official_provider_id=args.official_provider_id,
            bridge_provider_id=args.bridge_provider_id,
            bridge_provider_name=args.bridge_provider_name,
            bridge_base_url=args.bridge_base_url,
            realtime_ws_base_url=args.realtime_ws_base_url,
            realtime_webrtc_call_base_url=args.realtime_webrtc_call_base_url,
        )
        try:
            catalog_guard.start()
            server.catalog_guard = catalog_guard  # type: ignore[attr-defined]
        except Exception as exc:
            print(
                f"Warning: provider-scoped model-catalog guard could not start: {exc}",
                file=sys.stderr,
                flush=True,
            )
            catalog_guard = None
            server.catalog_guard = None  # type: ignore[attr-defined]

    def stop(_signum: int, _frame: object) -> None:
        # shutdown must run outside the signal handler's serve_forever frame.
        import threading

        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    print(f"Codex bridge listening on http://{listen_host}:{listen_port_text}")
    print(f"HTTP /responses upstream: {args.upstream}")
    print(f"Direct Official Responses WebSocket: {args.responses_ws_upstream}")
    print("Realtime voice should bypass this bridge: call creation uses ChatGPT backend; sideband uses OpenAI realtime.")
    print("Auth-aware restart continuity enabled: v2.15.1 keeps Official resident-WS restart continuity and correctness-first third-party shadow guards while Windows/macOS use repository-ZIP quick-start bootstraps. Cross-provider tool-bearing histories, unverified completions, and instruction drift fall back to complete portable replay instead of reusing stale provider cursors.")
    print("Provider routing persistence enabled: CC Switch selects the upstream provider, while the concrete model selected in Codex is preserved whenever it belongs to that provider. Stale models are rebound once to the route default.")
    print("Replay prefix checkpoints enabled in exact-only mode: no stale system/developer instruction is substituted.")
    if server.provider_continuation_enabled:  # type: ignore[attr-defined]
        print("Provider continuation enabled: Official uses guarded resident-WS continuation; third-party HTTP routes reuse durable shadow cursors only for completion-verified, tool-free, instruction-stable provider returns. Unsafe returns use complete portable replay. No conversation history is pruned.")
    else:
        print("Provider continuation disabled: provider switches use portable full replay/native caching only.")
    print("Restart token policy: Codex may restart for authentication/model UI refresh; restart-generated full history is a verification envelope. Official and supported third-party returns send only provider-unseen conversation delta; stale/unsupported third-party cursors fall back once to the complete portable replay. Internal Official HTTP models never fall through to a third-party CC Switch route.")
    print("HTTP /responses remains the conservative compatibility fallback if WebSocket transport is unavailable.")
    if server.switch_replay_compaction:  # type: ignore[attr-defined]
        print(
            "Switch replay compaction enabled: exact duplicate system/developer items and stale fully paired tool records may be omitted; "
            f"threshold={server.switch_replay_threshold_bytes} bytes; recent_user_turns={server.switch_replay_recent_user_turns}; visible user/assistant text is preserved verbatim."  # type: ignore[attr-defined]
        )
    else:
        print("Switch replay compaction disabled: portable full replays remain unpruned.")
    if server.prompt_cache_optimization:  # type: ignore[attr-defined]
        print(
            "Prompt-cache optimization enabled: GPT-5.6 full replays receive stable explicit content-block cache breakpoints at deterministic prefix-size checkpoints; request-level prompt_cache_options is intentionally omitted for ChatGPT Codex backend compatibility, and rejected breakpoints fall back once to the v2.4 request."
        )
    else:
        print("Prompt-cache optimization disabled: using native implicit prompt caching only.")
    if server.model_override:  # type: ignore[attr-defined]
        print(f"Rewriting request model to {server.model_override}")  # type: ignore[attr-defined]
        if server.preserve_comp_hash:  # type: ignore[attr-defined]
            print("CompHash switch guard disabled: upstream /models comp_hash is preserved.")
        else:
            print(
                "CompHash /models fallback guard enabled: returned model metadata omits comp_hash. "
                "The resident catalog guard keeps model_catalog_json pointed at the current provider-only hash-neutral snapshot across provider switches."
            )
    elif server.preserve_comp_hash:  # type: ignore[attr-defined]
        print("CompHash switch guard disabled: upstream /models comp_hash is preserved.")
    else:
        print(
            "CompHash /models fallback guard enabled: returned model metadata omits comp_hash. "
            "The resident catalog guard keeps model_catalog_json pointed at the current provider-only hash-neutral snapshot across provider switches."
        )
    if catalog_guard is not None:
        print(
            "Provider-scoped model-catalog guard active: Codex sees only the current provider's "
            "hash-neutral snapshot; a private learned catalog retains routing/capability metadata; "
            "provider-managed files are never modified in place."
        )
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    finally:
        if catalog_guard is not None:
            catalog_guard.stop()
        server.official_live_sessions.close_all()  # type: ignore[attr-defined]
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
