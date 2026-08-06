from __future__ import annotations

import unittest

from caramos_ota_audit.redaction import redact_text, redact_value


class RedactionTest(unittest.TestCase):
    def test_redact_text_masks_common_secrets(self) -> None:
        text = (
            "user=alice@example.com token=abc1234567890abcdef password: hunter2\n"
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature\n"
            "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
        )
        redacted = redact_text(text)
        self.assertNotIn("alice@example.com", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", redacted)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("[REDACTED_PRIVATE_KEY]", redacted)

    def test_redact_network_identifiers_and_wifi_secret(self) -> None:
        redacted = redact_text("wifi AA:BB:CC:DD:EE:FF ip 192.168.1.23 psk=top-secret")
        self.assertNotIn("AA:BB:CC:DD:EE:FF", redacted)
        self.assertNotIn("192.168.1.23", redacted)
        self.assertNotIn("top-secret", redacted)

    def test_redact_value_handles_nested_mappings(self) -> None:
        payload = {
            "email": "alice@example.com",
            "password": "secret123",
            "nested": [{"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz0123456789"}],
        }
        redacted = redact_value(payload)
        self.assertEqual(redacted["email"], "[REDACTED_EMAIL]")
        self.assertEqual(redacted["password"], "[REDACTED]")
        self.assertEqual(redacted["nested"][0]["Authorization"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
