import copy
import importlib.util
import sys
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "src" / "bridge" / "codex_provider_bridge.py"
spec = importlib.util.spec_from_file_location("codex_provider_bridge_compat_firewall", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
sys.modules["codex_provider_bridge_compat_firewall"] = bridge
assert spec.loader is not None
spec.loader.exec_module(bridge)


class ThirdPartyCompatibilityFirewallTests(unittest.TestCase):
    def test_known_cross_provider_state_failures_trigger_guarded_retry(self):
        cases = [
            (400, b"Invalid input[6].id: resp_deadbeef. Expected an ID that begins with msg_"),
            (400, b"encrypted content could not be verified"),
            (400, b"Invalid input[105].content: array too long"),
            (400, b"No tool output found for tool call call_123"),
            (400, b"No tool call found for tool output call_123"),
            (422, b"reasoning item is not supported by this provider"),
            (422, b"unsupported item_reference in input"),
            (400, b"compaction item is invalid for this endpoint"),
            (400, b"function_call_output call_id was not found"),
        ]
        for status, body in cases:
            with self.subTest(status=status, body=body):
                self.assertTrue(bridge.is_portability_error(status, body))

    def test_unrelated_provider_failures_do_not_trigger_history_rewrite(self):
        cases = [
            (400, b"RESPONSES_MODEL_NOT_SUPPORTED: deepseek-v4-flash"),
            (400, b"model deepseek-v4-flash is not supported"),
            (401, b"unauthorized"),
            (403, b"forbidden"),
            (429, b"rate limit exceeded"),
            (500, b"internal server error"),
            (400, b"invalid api key"),
            (422, b"invalid temperature value"),
        ]
        for status, body in cases:
            with self.subTest(status=status, body=body):
                self.assertFalse(bridge.is_portability_error(status, body))

    def test_portable_retry_preserves_conversation_and_plain_tool_pairs(self):
        payload = {
            "model": "third-party-model",
            "instructions": "Keep working on the same task.",
            "tools": [{"type": "function", "name": "shell"}],
            "tool_choice": "auto",
            "temperature": 0.2,
            "previous_response_id": "resp_foreign",
            "store": True,
            "reasoning": {"effort": "high"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": "foreign-cache",
            "input": [
                {"type": "message", "role": "user", "content": "continue"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "name": "shell",
                    "call_id": "call_ok",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "id": "out_1",
                    "call_id": "call_ok",
                    "output": "ok",
                },
                {"type": "message", "role": "assistant", "content": "done"},
            ],
        }
        original = copy.deepcopy(payload)
        portable, removed_ids, omitted_items, previous_removed = bridge.make_portable_responses_payload(
            payload, error_body=b"reasoning item is not supported"
        )

        self.assertEqual(original, payload)  # retry construction must not mutate the client payload
        self.assertTrue(previous_removed)
        self.assertEqual(2, removed_ids)
        self.assertEqual(0, omitted_items)
        self.assertFalse(portable["store"])
        self.assertNotIn("previous_response_id", portable)
        self.assertNotIn("reasoning", portable)
        self.assertNotIn("include", portable)
        self.assertNotIn("prompt_cache_key", portable)
        self.assertEqual("Keep working on the same task.", portable["instructions"])
        self.assertEqual(payload["tools"], portable["tools"])
        self.assertEqual("auto", portable["tool_choice"])
        self.assertEqual(0.2, portable["temperature"])
        self.assertEqual(
            ["message", "function_call", "function_call_output", "message"],
            [item["type"] for item in portable["input"]],
        )

    def test_portable_retry_omits_opaque_hosted_tool_state_and_dangling_calls(self):
        payload = {
            "input": [
                {"type": "message", "role": "user", "content": "continue"},
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
                {"type": "item_reference", "id": "item_1"},
                {"type": "web_search_call", "id": "ws_1", "call_id": "search_1"},
                {"type": "web_search_call_output", "id": "wso_1", "call_id": "search_1"},
                {"type": "computer_call", "id": "cc_1", "call_id": "computer_1"},
                {"type": "computer_call_output", "id": "cco_1", "call_id": "computer_1"},
                {
                    "type": "function_call",
                    "id": "fc_missing",
                    "name": "shell",
                    "call_id": "call_missing",
                    "arguments": "{}",
                },
                {"type": "message", "role": "assistant", "content": "visible transcript remains"},
            ]
        }
        portable, _, omitted_items, _ = bridge.make_portable_responses_payload(payload)
        self.assertEqual(7, omitted_items)
        self.assertEqual(
            ["message", "message"],
            [item["type"] for item in portable["input"]],
        )


if __name__ == "__main__":
    unittest.main()
