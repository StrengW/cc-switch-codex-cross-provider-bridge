"""Contract tests for the unified diagnostic-log sanitizer.

Two layers are locked here:

* Python behavior: the bridge's ``_sanitize_log_text`` / ``_log`` must strip the
  credential / personal-path samples from the redaction spec while preserving the
  diagnostic fields we intentionally keep (route, provider/model, HTTP status,
  retry, ports, counts, fingerprint).
* C# structure: the high-risk Windows launcher must funnel every persisted
  ``launcher.log`` line (including captured manager stdout/stderr and exception
  detail) through ``Sanitize(...)`` at its single ``Log(...)`` chokepoint, and
  that sanitizer must cover the same credential / path patterns.
"""

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src" / "bridge" / "codex_provider_bridge.py"
LAUNCHER_CS = ROOT / "src" / "launcher" / "CodexBridgeLauncher.cs"

_spec = importlib.util.spec_from_file_location(
    "codex_provider_bridge_sanitizer_contract", BRIDGE
)
bridge = importlib.util.module_from_spec(_spec)
sys.modules["codex_provider_bridge_sanitizer_contract"] = bridge
assert _spec.loader is not None
_spec.loader.exec_module(bridge)


class PythonLogSanitizerBehaviorTests(unittest.TestCase):
    """The bridge sanitizer must redact secrets and keep honest diagnostics."""

    def sanitize(self, text):
        return bridge._sanitize_log_text(text)

    def test_authorization_bearer_header_is_redacted(self):
        out = self.sanitize("Authorization: Bearer super-secret-token")
        self.assertNotIn("super-secret-token", out)
        self.assertIn("Authorization", out)

    def test_proxy_authorization_basic_header_is_redacted(self):
        out = self.sanitize("Proxy-Authorization: Basic c2VjcmV0OnBhc3N3b3Jk")
        self.assertNotIn("c2VjcmV0OnBhc3N3b3Jk", out)

    def test_api_key_sk_value_is_redacted(self):
        out = self.sanitize("request api_key=sk-test123 accepted")
        self.assertNotIn("sk-test123", out)
        self.assertNotIn("test123", out)

    def test_url_token_query_param_is_redacted(self):
        out = self.sanitize("GET https://example.com?token=abc123 200")
        self.assertNotIn("abc123", out)

    def test_macos_personal_path_is_masked(self):
        out = self.sanitize(
            "state at /Users/kelen/Library/Application Support/CodexProviderBridge"
        )
        self.assertNotIn("kelen", out)
        self.assertIn("/Users/<user>", out)

    def test_windows_personal_path_is_masked(self):
        out = self.sanitize(r"log dir C:\Users\Streng\AppData\Local\CodexProviderBridge")
        self.assertNotIn("Streng", out)
        self.assertIn(r"C:\Users\<user>", out)

    def test_cookie_value_is_redacted(self):
        out = self.sanitize("Cookie: session=abcdef")
        self.assertNotIn("abcdef", out)

    def test_jwt_shaped_string_is_redacted(self):
        out = self.sanitize(
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijk1234567"
        )
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", out)

    def test_url_embedded_credentials_are_redacted(self):
        out = self.sanitize("upstream https://alice:s3cr3tpass@example.com/v1")
        self.assertNotIn("s3cr3tpass", out)
        self.assertNotIn("alice:", out)

    def test_email_is_redacted(self):
        out = self.sanitize("contact user@example.com for support")
        self.assertNotIn("user@example.com", out)

    def test_diagnostic_fields_are_preserved(self):
        line = (
            "route=Third-party provider=deepseek model=deepseek-chat "
            "http_status=200 retry=2/5 port=15722 proxy=15721 "
            "fingerprint=9f2c1a tokens=15"
        )
        out = self.sanitize(line)
        for kept in (
            "route=Third-party",
            "provider=deepseek",
            "deepseek-chat",
            "http_status=200",
            "retry=2/5",
            "15722",
            "15721",
            "fingerprint=9f2c1a",
            "tokens=15",
        ):
            self.assertIn(kept, out)

    def test_log_helper_routes_through_sanitizer(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bridge._log("Authorization: Bearer super-secret-token")
        self.assertNotIn("super-secret-token", buf.getvalue())

    def test_log_helper_error_routes_to_stderr_sanitized(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            bridge._log("api_key=sk-test123", error=True)
        self.assertNotIn("sk-test123", buf.getvalue())


class CSharpLogSanitizerStructuralContractTests(unittest.TestCase):
    """The Windows launcher must sanitize at its single Log(...) chokepoint."""

    @classmethod
    def setUpClass(cls):
        cls.text = LAUNCHER_CS.read_text(encoding="utf-8-sig")

    def test_sanitize_method_is_defined(self):
        self.assertIn("private static string Sanitize(string message)", self.text)

    def test_log_append_goes_through_sanitize(self):
        self.assertIn(
            'DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + Sanitize(message)',
            self.text,
        )

    def test_sanitize_covers_authorization_headers(self):
        self.assertIn("proxy-authorization|authorization", self.text)

    def test_sanitize_covers_bearer_and_basic(self):
        self.assertIn("bearer|basic", self.text)

    def test_sanitize_covers_sk_keys(self):
        self.assertIn("sk-[A-Za-z0-9_-]", self.text)

    def test_sanitize_covers_cookie(self):
        self.assertIn("set-cookie|cookie", self.text)

    def test_sanitize_covers_kv_secrets(self):
        self.assertIn("access[_-]?token", self.text)

    def test_sanitize_covers_macos_and_windows_personal_paths(self):
        self.assertIn("/Users/", self.text)
        self.assertIn("Users\\\\", self.text)


if __name__ == "__main__":
    unittest.main()
