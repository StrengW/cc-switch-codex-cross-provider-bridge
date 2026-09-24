"""Official-route HTTP upstream selection and the config keys derived from the route.

The WebSocket path has always gone straight to the ChatGPT backend on an Official
route. These tests hold the plain HTTP path to the same rule, because the two
disagreeing is what turned a closed CC Switch into a 502 on the one route that is
documented as not needing CC Switch at all.

They also cover the two ways ``supports_websockets`` could go stale on an Official
route, which is what makes Codex pick that HTTP path in the first place.
"""

import http.client
import http.server
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

BRIDGE = Path(__file__).resolve().parents[1] / "src" / "bridge" / "codex_provider_bridge.py"
spec = importlib.util.spec_from_file_location("codex_provider_bridge_official_route", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
sys.modules["codex_provider_bridge_official_route"] = bridge
assert spec.loader is not None
spec.loader.exec_module(bridge)

BRIDGE_BASE_URL = "http://127.0.0.1:15722/v1"
OFFICIAL_MODEL = "gpt-5.6-sol"

CONFIG_TEMPLATE = """\
model_provider = "custom"
model = "{model}"

[model_providers.custom]
name = "OpenAI"
wire_api = "responses"
requires_openai_auth = true
base_url = "{base_url}"
model_catalog_json = "{catalog}"
supports_websockets = {websockets}
"""


def make_guard(root: Path, *, model: str, catalog: str, websockets: str):
    """Build a guard over a temp Codex config that is already in bridge mode."""
    bundled = root / "cpb-bundled-model-catalog.json"
    bundled.write_text(
        json.dumps({"models": [{"slug": OFFICIAL_MODEL}]}), encoding="utf-8"
    )
    config = root / "config.toml"
    config.write_text(
        CONFIG_TEMPLATE.format(
            model=model, base_url=BRIDGE_BASE_URL, catalog=catalog, websockets=websockets
        ),
        encoding="utf-8",
    )
    guard = bridge.CatalogConfigGuard(
        config_path=str(config),
        bundled_catalog_path=str(bundled),
        active_catalog_path=str(root / "cpb-active-model-catalog.json"),
        official_provider_id="cc-switch-official",
        bridge_provider_id="custom",
        bridge_provider_name="OpenAI",
        bridge_base_url=BRIDGE_BASE_URL,
        realtime_ws_base_url="https://api.openai.com/v1",
        realtime_webrtc_call_base_url="https://chatgpt.com/backend-api/codex",
    )
    return guard, config


def section_value(text: str, key: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(key + " "):
            return stripped.split("=", 1)[1].strip()
    return ""


class HttpUpstreamSelectionTests(unittest.TestCase):
    def test_official_route_responses_goes_direct(self):
        self.assertTrue(
            bridge._http_upstream_is_direct_official(
                route_official=True,
                internal_official_model=False,
                is_responses_path=True,
            )
        )

    def test_third_party_route_responses_still_uses_cc_switch(self):
        self.assertFalse(
            bridge._http_upstream_is_direct_official(
                route_official=False,
                internal_official_model=False,
                is_responses_path=True,
            )
        )

    def test_internal_official_model_stays_direct_on_a_third_party_route(self):
        # Pre-existing behaviour worth pinning: Codex-owned background models must
        # never be handed to a third-party proxy, whatever the route says.
        self.assertTrue(
            bridge._http_upstream_is_direct_official(
                route_official=False,
                internal_official_model=True,
                is_responses_path=True,
            )
        )

    def test_non_responses_paths_never_go_direct(self):
        # The direct upstream path is built for /backend-api/codex/responses, so
        # every other path has to keep using the configured HTTP upstream.
        for route_official in (True, False):
            for internal in (True, False):
                with self.subTest(route_official=route_official, internal=internal):
                    self.assertFalse(
                        bridge._http_upstream_is_direct_official(
                            route_official=route_official,
                            internal_official_model=internal,
                            is_responses_path=False,
                        )
                    )

    def test_user_facing_official_model_is_not_an_internal_model(self):
        # The whole bug rests on this pair: gpt-5.6-sol is Official, but it is not
        # "internal", so the narrow internal-only flag never fired for it.
        self.assertTrue(bridge._looks_official_model(OFFICIAL_MODEL))
        self.assertFalse(bridge._looks_internal_official_model(OFFICIAL_MODEL))
        self.assertTrue(bridge._looks_internal_official_model("gpt-5.3-terra"))


class HandlerConsumesTheSharedFlagTests(unittest.TestCase):
    """The decision has to reach every place the upstream is used, or they drift."""

    @classmethod
    def setUpClass(cls):
        cls.text = BRIDGE.read_text(encoding="utf-8")

    def test_route_official_is_visible_where_the_upstream_is_chosen(self):
        selection = self.text[
            self.text.index("direct_official_http = _http_upstream_is_direct_official(") :
        ]
        selection = selection[: selection.index("comp_hash_guard = (")]
        self.assertIn("route_official=route_official", selection)
        self.assertIn("if direct_official_http:", selection)
        self.assertIn("self.server.responses_ws_upstream", selection)
        # The narrow internal-model flag may feed the predicate, but it must no
        # longer be the gate that decides where the request goes.
        self.assertNotIn("if direct_official_internal_http:", selection)

    def test_route_is_resolved_before_the_json_body_branch(self):
        # The root cause, pinned directly: the route used to be read inside the
        # JSON-body try block, so any request without a JSON Responses body got no
        # route at all and the upstream selection could not see an Official one.
        region = self.text[self.text.index("    def _handle(self) -> None:") :]
        resolved = region.index("route_official = self._route_looks_official()")
        body_branch = region.index('if body and "json" in content_type')
        self.assertLess(resolved, body_branch)

    def test_upstream_path_uses_the_same_flag(self):
        self.assertIn(
            "self._direct_responses_ws_path()\n            if direct_official_http",
            self.text,
        )

    def test_failure_label_names_the_upstream_that_actually_failed(self):
        # A 502 blamed on "CC Switch" while the request was really going to the
        # ChatGPT backend sends whoever reads the log to the wrong component.
        label = self.text[self.text.index("except (OSError, http.client.HTTPException) as exc:"):]
        label = label[: label.index("finally:")]
        self.assertIn('"Direct Official" if direct_official_http else "CC Switch"', label)

    def test_log_field_keeps_internal_and_route_direct_apart(self):
        field = self.text[self.text.index('"direct-official-internal"'):]
        field = field[: field.index("except (OSError, http.client.HTTPException) as exc:")]
        self.assertIn('"direct-official"', field)
        self.assertIn('"cc-switch"', field)


class SupportsWebsocketsStalenessTests(unittest.TestCase):
    def test_guard_reasserts_websockets_when_the_catalog_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard, config = make_guard(
                root, model=OFFICIAL_MODEL, catalog="", websockets="false"
            )

            # First pass publishes the Official snapshot and pins the picker.
            guard.guard_once()
            published = section_value(config.read_text(encoding="utf-8"), "model_catalog_json")
            self.assertTrue(published, "expected the guard to pin a catalog path")

            # Now reproduce the stale state: the route is Official and the catalog
            # already matches, but supports_websockets says false. This is what a
            # CC Switch config template rewrite or one failed write leaves behind.
            config.write_text(
                CONFIG_TEMPLATE.format(
                    model=OFFICIAL_MODEL,
                    base_url=BRIDGE_BASE_URL,
                    catalog=json.loads(published),
                    websockets="false",
                ),
                encoding="utf-8",
            )

            guard.guard_once()

            after = config.read_text(encoding="utf-8")
            self.assertEqual(section_value(after, "supports_websockets"), "true")
            self.assertEqual(guard.route_kind, "official")

    def test_guard_leaves_websockets_false_on_a_third_party_route(self):
        # The mirror image: re-asserting every pass must not flip a third-party
        # route into claiming WebSocket support it does not have.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard, config = make_guard(
                root, model="glm-5.3-flash", catalog="", websockets="true"
            )
            guard.guard_once()
            guard.guard_once()
            after = config.read_text(encoding="utf-8")
            self.assertEqual(guard.route_kind, "third-party")
            self.assertEqual(section_value(after, "supports_websockets"), "false")


class TransientLockTests(unittest.TestCase):
    def test_config_read_retries_through_a_sharing_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard, config = make_guard(
                root, model=OFFICIAL_MODEL, catalog="", websockets="false"
            )
            original = Path.read_text
            denied = {"count": 0}

            def flaky(self, *args, **kwargs):
                if self == config and denied["count"] < 2:
                    denied["count"] += 1
                    raise PermissionError(13, "Permission denied", str(self))
                return original(self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", flaky):
                self.assertEqual(
                    guard._read_text_with_retry(config),
                    original(config, encoding="utf-8"),
                )
            self.assertEqual(denied["count"], 2)

    def test_config_read_still_fails_when_the_lock_never_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard, config = make_guard(
                root, model=OFFICIAL_MODEL, catalog="", websockets="false"
            )

            original = Path.read_text

            def always_deny(self, *args, **kwargs):
                if self == config:
                    raise PermissionError(13, "Permission denied", str(self))
                return original(self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", always_deny), mock.patch.object(
                bridge.time, "sleep", lambda _seconds: None
            ):
                with self.assertRaises(PermissionError):
                    guard._read_text_with_retry(config)

    def test_guard_pass_survives_a_transient_lock_on_config(self):
        # The user-visible symptom was a "could not reconcile config" warning and a
        # skipped pass, so the pass itself has to ride through the contention.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard, config = make_guard(
                root, model=OFFICIAL_MODEL, catalog="", websockets="false"
            )
            original = Path.read_text
            denied = {"count": 0}

            def flaky(self, *args, **kwargs):
                if self == config and denied["count"] < 3:
                    denied["count"] += 1
                    raise PermissionError(13, "Permission denied", str(self))
                return original(self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", flaky):
                guard.guard_once()
            self.assertEqual(guard.route_kind, "official")
            self.assertEqual(
                section_value(config.read_text(encoding="utf-8"), "supports_websockets"),
                "true",
            )

    def test_guard_reads_config_through_the_retrying_reader(self):
        text = BRIDGE.read_text(encoding="utf-8")
        body = text[text.index("def guard_once"):]
        body = body[: body.index("def _run")]
        self.assertIn("self._read_text_with_retry(self.config_path)", body)
        self.assertNotIn("self.config_path.read_text(", body)


class RecordingUpstream(http.server.ThreadingHTTPServer):
    """Stands in for one upstream and remembers every request it received."""

    def __init__(self, label: str, *, base_path: str = ""):
        self.label = label
        self.base_path = base_path.rstrip("/")
        self.requests: list[tuple[str, str]] = []
        self.torn_down = False
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8", "replace")
                outer.requests.append((self.path, body))
                payload = json.dumps({"marker": outer.label, "path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.daemon_threads = True
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}{self.base_path}"

    def close(self) -> None:
        # Idempotent: a test may need an upstream to be gone before the bridge
        # even starts, and the cleanup must then be a no-op instead of closing an
        # already-closed socket under a still-running serve_forever.
        if self.torn_down:
            return
        self.torn_down = True
        self.shutdown()
        self.server_close()


def start_bridge(*, config: Path, cc_switch: str, direct: str):
    """Run the real handler in-process, wired exactly the way main() wires it."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
    server.daemon_threads = True
    server.upstream = urlsplit(cc_switch)
    server.responses_ws_upstream = urlsplit(direct)
    server.model_override = ""
    server.codex_config_path = str(config)
    server.replay_checkpoint_store = bridge.ReplayPrefixCheckpointStore()
    server.provider_continuation_store = bridge.ProviderContinuationStore()
    server.strict_tool_adjacency_store = bridge.StrictToolAdjacencyCapabilityStore()
    server.official_live_sessions = bridge.OfficialLiveSessionPool()
    server.hot_switch_route_state = bridge.HotSwitchRouteState()
    server.provider_continuation_enabled = True
    server.prompt_cache_optimization = False
    server.explicit_cache_rejected = False
    server.prompt_cache_key_rejected = False
    server.switch_replay_compaction = False
    server.switch_replay_threshold_bytes = bridge.SWITCH_REPLAY_DEFAULT_THRESHOLD_BYTES
    server.switch_replay_recent_user_turns = bridge.SWITCH_REPLAY_DEFAULT_RECENT_USER_TURNS
    server.preserve_comp_hash = False
    # No catalog guard: the route then comes from the Codex config on disk, which
    # is what a user actually edits when CC Switch changes provider.
    server.catalog_guard = None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class EndToEndRouteSelectionTests(unittest.TestCase):
    """Prove where the bytes go, not just which flag a code path reads."""

    def setUp(self):
        # The direct target keeps the production path shape, so the request path
        # the bridge builds is the real /backend-api/codex/responses.
        self.cc_switch = RecordingUpstream("cc-switch")
        self.direct = RecordingUpstream("direct", base_path="/backend-api/codex")
        self.addCleanup(self.cc_switch.close)
        self.addCleanup(self.direct.close)

    def post_responses(self, config: Path, model: str) -> int:
        server = start_bridge(
            config=config, cc_switch=self.cc_switch.url, direct=self.direct.url
        )
        # Cleanups run last-in-first-out: stop serve_forever before the socket goes.
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        payload = json.dumps(
            {
                "model": model,
                "stream": False,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    }
                ],
            }
        ).encode()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        connection.request(
            "POST",
            "/v1/responses",
            body=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer test"},
        )
        status = connection.getresponse().status
        connection.close()
        return status

    def test_official_route_reaches_the_chatgpt_backend_and_not_cc_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(f'model = "{OFFICIAL_MODEL}"\n', encoding="utf-8")

            status = self.post_responses(config, OFFICIAL_MODEL)

            self.assertEqual(status, 200)
            self.assertEqual(
                [path for path, _ in self.direct.requests],
                ["/backend-api/codex/responses"],
            )
            self.assertEqual(self.cc_switch.requests, [])

    def test_official_route_survives_cc_switch_being_closed(self):
        # The reported symptom: CC Switch not listening used to mean a 502 on the
        # one route documented as not needing it.
        self.cc_switch.close()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(f'model = "{OFFICIAL_MODEL}"\n', encoding="utf-8")

            self.assertEqual(self.post_responses(config, OFFICIAL_MODEL), 200)
            self.assertEqual(len(self.direct.requests), 1)

    def test_third_party_route_still_goes_through_cc_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('model = "glm-5.3-flash"\n', encoding="utf-8")

            status = self.post_responses(config, "glm-5.3-flash")

            self.assertEqual(status, 200)
            self.assertEqual(self.direct.requests, [])
            self.assertEqual(len(self.cc_switch.requests), 1)

    def test_internal_official_model_stays_direct_on_a_third_party_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('model = "glm-5.3-flash"\n', encoding="utf-8")

            self.post_responses(config, "gpt-5.3-terra")

            self.assertEqual(len(self.direct.requests), 1)
            self.assertEqual(self.cc_switch.requests, [])


if __name__ == "__main__":
    unittest.main()
