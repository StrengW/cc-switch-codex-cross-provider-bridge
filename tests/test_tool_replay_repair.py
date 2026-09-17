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


if __name__ == "__main__":
    unittest.main()
