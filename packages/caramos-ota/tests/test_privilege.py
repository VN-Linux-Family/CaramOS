"""Tests for OTA process locking."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota import privilege


class PrivilegeTests(unittest.TestCase):
    def tearDown(self) -> None:
        if privilege._lock_handle is not None:
            privilege._lock_handle.close()
            privilege._lock_handle = None

    def test_inherited_lock_fd_is_reused_and_competitor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            lock_file = state_dir / "lock"
            with (
                patch.object(privilege, "STATE_DIR", state_dir),
                patch.object(privilege, "LOCK_FILE", lock_file),
            ):
                lock_fd = privilege.acquire_lock()

                script = (
                    "import pathlib, sys; "
                    "from caramos_ota import privilege; "
                    "privilege.STATE_DIR = pathlib.Path(sys.argv[1]); "
                    "privilege.LOCK_FILE = privilege.STATE_DIR / 'lock'; "
                    "privilege.acquire_lock(int(sys.argv[2]) if len(sys.argv) > 2 else None)"
                )
                inherited = subprocess.run(
                    [sys.executable, "-c", script, str(state_dir), str(lock_fd)],
                    check=False,
                    pass_fds=(lock_fd,),
                )
                competitor = subprocess.run(
                    [sys.executable, "-c", script, str(state_dir)],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                self.assertEqual(0, inherited.returncode)
                self.assertEqual(7, competitor.returncode)
                self.assertIn("Another CaramOS OTA operation", competitor.stdout)

    def test_rejects_inherited_fd_for_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            lock_file = state_dir / "lock"
            lock_file.touch()
            other_file = state_dir / "other"
            with other_file.open("w", encoding="utf-8") as handle:
                with (
                    patch.object(privilege, "STATE_DIR", state_dir),
                    patch.object(privilege, "LOCK_FILE", lock_file),
                ):
                    with self.assertRaisesRegex(SystemExit, "7"):
                        privilege.acquire_lock(handle.fileno())


if __name__ == "__main__":
    unittest.main()
