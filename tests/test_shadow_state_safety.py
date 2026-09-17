import importlib.util
import sys
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "src" / "bridge" / "codex_provider_bridge.py"
spec = importlib.util.spec_from_file_location("codex_provider_bridge", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
sys.modules["codex_provider_bridge"] = bridge
assert spec.loader is not None
spec.loader.exec_module(bridge)


def message(role: str, text: str) -> dict:
    block_type = "output_text" if role == "assistant" else "input_text"
    return {"type": "message", "role": role, "content": [{"type": block_type, "text": text}]}


class ThirdPartyShadowSafetyTests(unittest.TestCase):
    key = "third-party|glm-5.3-flash|conv:test"

    def test_pure_message_stable_instruction_can_continue(self):
        store = bridge.ProviderContinuationStore()
        saved = [message("developer", "stable policy"), message("user", "A"), message("assistant", "A-ok")]
        store.commit(self.key, "resp_a", saved, durable=True, route_serial=1, completion_verified=True)
        current = saved + [message("user", "B")]
        diagnostics = {}
        candidate = store.candidate(
            self.key,
            current,
            current_route_serial=3,
            allow_provider_return_instruction_pin=True,
            diagnostics=diagnostics,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual("matched", diagnostics["reason"])
        self.assertEqual(["user"], [x.get("role") for x in candidate[1] if isinstance(x, dict)])

    def test_instruction_drift_forces_full_replay(self):
        store = bridge.ProviderContinuationStore()
        saved = [message("developer", "stable policy"), message("user", "A"), message("assistant", "A-ok")]
        store.commit(self.key, "resp_a", saved, durable=True, route_serial=1, completion_verified=True)
        current = [message("developer", "changed task policy"), message("user", "A"), message("assistant", "A-ok"), message("user", "B")]
        diagnostics = {}
        candidate = store.candidate(
            self.key,
            current,
            current_route_serial=3,
            allow_provider_return_instruction_pin=True,
            diagnostics=diagnostics,
        )
        self.assertIsNone(candidate)
        self.assertEqual("instruction-drift-full-replay", diagnostics["reason"])

    def test_tool_history_forces_full_replay_even_same_route(self):
        store = bridge.ProviderContinuationStore()
        saved = [
            message("developer", "stable"),
            message("user", "run task"),
            {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
            message("assistant", "done"),
        ]
        store.commit(self.key, "resp_tool", saved, durable=True, route_serial=1, completion_verified=True)
        diagnostics = {}
        candidate = store.candidate(
            self.key,
            saved + [message("user", "continue")],
            current_route_serial=1,
            allow_provider_return_instruction_pin=True,
            diagnostics=diagnostics,
        )
        self.assertIsNone(candidate)
        self.assertEqual("tool-history-full-replay", diagnostics["reason"])

    def test_different_branch_cannot_reuse_cursor(self):
        store = bridge.ProviderContinuationStore()
        saved = [message("developer", "stable"), message("user", "A"), message("assistant", "branch one")]
        store.commit(self.key, "resp_branch", saved, durable=True, route_serial=1, completion_verified=True)
        current = [message("developer", "stable"), message("user", "A"), message("assistant", "branch two"), message("user", "continue")]
        diagnostics = {}
        candidate = store.candidate(
            self.key,
            current,
            current_route_serial=3,
            allow_provider_return_instruction_pin=True,
            diagnostics=diagnostics,
        )
        self.assertIsNone(candidate)
        self.assertEqual("timeline-prefix-mismatch", diagnostics["reason"])


    def test_thread_scope_separates_same_first_user_across_chats(self):
        items = [message("user", "same first prompt")]
        key_a, fp_a = bridge._provider_shadow_state_key(
            "glm-5.3-flash", "third-party", items, request_scope="thread-a"
        )
        key_b, fp_b = bridge._provider_shadow_state_key(
            "glm-5.3-flash", "third-party", items, request_scope="thread-b"
        )
        self.assertNotEqual(key_a, key_b)
        self.assertEqual(fp_a, fp_b)
        self.assertEqual(
            bridge.ProviderContinuationStore._capability_key(key_a),
            bridge.ProviderContinuationStore._capability_key(key_b),
        )

    def test_unverified_checkpoint_cannot_be_reused(self):
        store = bridge.ProviderContinuationStore()
        saved = [message("developer", "stable"), message("user", "A"), message("assistant", "A-ok")]
        store.commit(self.key, "resp_old", saved, durable=True, route_serial=1, completion_verified=False)
        diagnostics = {}
        candidate = store.candidate(
            self.key,
            saved + [message("user", "B")],
            current_route_serial=3,
            allow_provider_return_instruction_pin=True,
            diagnostics=diagnostics,
        )
        self.assertIsNone(candidate)
        self.assertEqual("unverified-completion", diagnostics["reason"])


if __name__ == "__main__":
    unittest.main()
