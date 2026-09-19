import importlib.util
import sys
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "src" / "bridge" / "codex_provider_bridge.py"
spec = importlib.util.spec_from_file_location("codex_provider_bridge_tool_repair", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
sys.modules["codex_provider_bridge_tool_repair"] = bridge
assert spec.loader is not None
spec.loader.exec_module(bridge)


class ToolReplayRepairTests(unittest.TestCase):
    def test_deepseek_missing_tool_output_error_is_portability_error(self):
        body = (
            b"CC Switch local proxy failed while handling Codex endpoint /responses. "
            b"Provider: DeepSeek; upstream_status: HTTP 400; cause: "
            b"No tool output found for tool call call_abc123."
        )
        self.assertTrue(bridge.is_portability_error(400, body))

    def test_portable_retry_drops_dangling_call_but_keeps_complete_pair(self):
        payload = {
            "model": "deepseek-v4-flash",
            "previous_response_id": "resp_foreign",
            "store": True,
            "input": [
                {"type": "message", "role": "user", "content": "run"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "name": "shell",
                    "call_id": "call_complete",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "id": "out_1",
                    "call_id": "call_complete",
                    "output": "ok",
                },
                {
                    "type": "function_call",
                    "id": "fc_2",
                    "name": "shell",
                    "call_id": "call_missing_output",
                    "arguments": "{}",
                },
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
                {"type": "message", "role": "assistant", "content": "done"},
            ],
        }
        portable, removed_ids, omitted_items, previous_removed = bridge.make_portable_responses_payload(payload)
        self.assertTrue(previous_removed)
        self.assertFalse(portable["store"])
        self.assertNotIn("previous_response_id", portable)
        self.assertEqual(3, removed_ids)  # ids removed from both complete tool records and the dangling call before prune
        self.assertEqual(2, omitted_items)  # reasoning + dangling tool call
        call_ids = [
            item.get("call_id")
            for item in portable["input"]
            if isinstance(item, dict) and item.get("type") in bridge.TOOL_CALL_TYPES | bridge.TOOL_OUTPUT_TYPES
        ]
        self.assertEqual(["call_complete", "call_complete"], call_ids)

    def test_strict_tool_call_adjacency_error_is_portability_error(self):
        body = (
            b"CC Switch local proxy failed while handling Codex endpoint /responses. "
            b"Provider: provider-x; model: deepseek-flash; upstream_status: HTTP 400; cause: "
            b"An assistant message with 'tool_calls' must be followed by tool messages "
            b"responding to each 'tool_call_id'. (insufficient tool messages following tool_calls message)"
        )
        self.assertTrue(bridge.is_portability_error(400, body))
        self.assertTrue(bridge._strict_tool_adjacency_error(body))

    def test_non_tool_portability_error_does_not_enable_adjacency_repair(self):
        body = b"encrypted content could not be verified"
        self.assertTrue(bridge.is_portability_error(400, body))
        self.assertFalse(bridge._strict_tool_adjacency_error(body))

    def test_strict_retry_keeps_adjacent_parallel_tool_group(self):
        error = (
            b"An assistant message with 'tool_calls' must be followed by tool messages "
            b"responding to each 'tool_call_id'."
        )
        payload = {
            "input": [
                {"type": "message", "role": "user", "content": "run both"},
                {"type": "function_call", "call_id": "call_a", "name": "a", "arguments": "{}"},
                {"type": "function_call", "call_id": "call_b", "name": "b", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_b", "output": "B"},
                {"type": "function_call_output", "call_id": "call_a", "output": "A"},
                {"type": "message", "role": "assistant", "content": "done"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(payload, error_body=error)
        self.assertEqual(0, omitted_items)
        self.assertEqual(
            ["message", "function_call", "function_call", "function_call_output", "function_call_output", "message"],
            [item["type"] for item in portable["input"]],
        )

    def test_strict_retry_drops_complete_but_nonadjacent_tool_group(self):
        error = (
            b"An assistant message with 'tool_calls' must be followed by tool messages "
            b"responding to each 'tool_call_id'."
        )
        payload = {
            "input": [
                {"type": "message", "role": "user", "content": "run both"},
                {"type": "function_call", "call_id": "call_a", "name": "a", "arguments": "{}"},
                {"type": "function_call", "call_id": "call_b", "name": "b", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_a", "output": "A"},
                {"type": "message", "role": "assistant", "content": "interleaved"},
                {"type": "function_call_output", "call_id": "call_b", "output": "B"},
                {"type": "message", "role": "user", "content": "continue"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(payload, error_body=error)
        self.assertEqual(4, omitted_items)
        self.assertEqual(
            ["message", "message", "message"],
            [item["type"] for item in portable["input"]],
        )
        self.assertEqual(
            ["run both", "interleaved", "continue"],
            [item["content"] for item in portable["input"]],
        )

    def test_non_tool_retry_preserves_complete_nonadjacent_pair_behavior(self):
        payload = {
            "input": [
                {"type": "function_call", "call_id": "call_a", "name": "a", "arguments": "{}"},
                {"type": "message", "role": "assistant", "content": "interleaved"},
                {"type": "function_call_output", "call_id": "call_a", "output": "A"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(
            payload, error_body=b"encrypted content could not be verified"
        )
        self.assertEqual(0, omitted_items)
        self.assertEqual(
            ["function_call", "message", "function_call_output"],
            [item["type"] for item in portable["input"]],
        )

    def test_strict_retry_drops_output_before_matching_call(self):
        error = b"tool_calls must be followed by tool messages for each tool_call_id"
        payload = {
            "input": [
                {"type": "function_call_output", "call_id": "call_a", "output": "A"},
                {"type": "function_call", "call_id": "call_a", "name": "a", "arguments": "{}"},
                {"type": "message", "role": "user", "content": "continue"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(payload, error_body=error)
        self.assertEqual(2, omitted_items)
        self.assertEqual(["message"], [item["type"] for item in portable["input"]])

    def test_portable_retry_drops_orphan_output_too(self):
        payload = {
            "input": [
                {"type": "function_call_output", "call_id": "orphan", "output": "x"},
                {"type": "message", "role": "user", "content": "continue"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(payload)
        self.assertEqual(1, omitted_items)
        self.assertEqual(1, len(portable["input"]))
        self.assertEqual("message", portable["input"][0]["type"])

    def test_strict_capability_learning_is_conversation_and_route_scoped(self):
        store = bridge.StrictToolAdjacencyCapabilityStore()
        broken_thread = "third-party|deepseek-flash|thread:broken"
        healthy_thread = "third-party|deepseek-flash|thread:healthy"

        self.assertTrue(store.mark_required(broken_thread, 3))
        self.assertTrue(store.requires(broken_thread, 3))
        # A second Codex conversation using the same model keeps the normal path.
        self.assertFalse(store.requires(healthy_thread, 3))
        # A later route epoch also starts clean rather than inheriting stale capability.
        self.assertFalse(store.requires(broken_thread, 4))

    def test_strict_capability_can_be_forgotten_after_preflight_rejection(self):
        store = bridge.StrictToolAdjacencyCapabilityStore()
        key = "third-party|deepseek-flash|thread:broken"
        store.mark_required(key, 3)
        self.assertTrue(store.forget(key, 3))
        self.assertFalse(store.requires(key, 3))
        self.assertFalse(store.forget(key, 3))

    def test_learned_preflight_reuses_exact_strict_firewall_shape(self):
        error = (
            b"An assistant message with 'tool_calls' must be followed by tool messages "
            b"responding to each 'tool_call_id'."
        )
        payload = {
            "model": "deepseek-flash",
            "store": True,
            "previous_response_id": "resp_foreign",
            "input": [
                {"type": "message", "role": "user", "content": "run"},
                {"type": "function_call", "call_id": "call_a", "name": "a", "arguments": "{}"},
                {"type": "message", "role": "assistant", "content": "interleaved"},
                {"type": "function_call_output", "call_id": "call_a", "output": "A"},
                {"type": "message", "role": "user", "content": "continue"},
            ],
        }
        retry_shape = bridge.make_portable_responses_payload(payload, error_body=error)
        learned_shape = bridge.make_learned_strict_tool_payload(payload)
        self.assertEqual(retry_shape, learned_shape)
        self.assertFalse(learned_shape[0]["store"])
        self.assertNotIn("previous_response_id", learned_shape[0])


if __name__ == "__main__":
    unittest.main()
