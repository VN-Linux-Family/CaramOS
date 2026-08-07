"""Tests for OTA state schema upgrade."""

from __future__ import annotations

import unittest

from caramos_ota.state import _upgrade_state


class StateTests(unittest.TestCase):
    def test_v1_state_upgrades_without_losing_history(self) -> None:
        transaction = {"id": "old", "status": "failed"}
        state = {
            "schema": 1,
            "installed_release": "1.0.12",
            "available_update": {"release": "1.0.13"},
            "transactions": [transaction],
        }

        upgraded = _upgrade_state(state)

        self.assertEqual(2, upgraded["schema"])
        self.assertEqual("1.0.12", upgraded["installed_release"])
        self.assertEqual([transaction], upgraded["transactions"])
        self.assertIn("transaction", upgraded)


if __name__ == "__main__":
    unittest.main()
