"""An install finishes before caramos-ota stops at a shutdown (stopping.py; tickets H-1218, H-1221)."""

from __future__ import annotations

import os
import signal
import unittest
from unittest import mock

from caramos_ota import stopping


class FinishingBeforeStoppingTests(unittest.TestCase):
    def test_sigterm_during_the_install_waits_for_it_then_stops(self) -> None:
        done = []
        with mock.patch.object(stopping, "log_warn") as warn:
            with self.assertRaises(SystemExit) as stopped:
                with stopping.finishing_before_stopping("installing the update engine"):
                    os.kill(os.getpid(), signal.SIGTERM)
                    done.append("the install went on")
        self.assertEqual(["the install went on"], done)
        self.assertEqual(stopping.EXIT_STOPPED, stopped.exception.code)
        self.assertEqual(143, stopping.EXIT_STOPPED)
        self.assertIn("finishing first", warn.call_args_list[0].args[0])
        self.assertIn("Stopping now", warn.call_args_list[-1].args[0])

    def test_without_sigterm_nothing_changes(self) -> None:
        before = signal.getsignal(signal.SIGTERM)
        with stopping.finishing_before_stopping("installing"):
            self.assertNotEqual(before, signal.getsignal(signal.SIGTERM))
        self.assertEqual(before, signal.getsignal(signal.SIGTERM))

    def test_an_error_in_the_block_goes_through_and_the_handler_comes_back(self) -> None:
        before = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(SystemExit) as failed:
            with stopping.finishing_before_stopping("installing"):
                raise SystemExit(5)
        self.assertEqual(5, failed.exception.code)
        self.assertEqual(before, signal.getsignal(signal.SIGTERM))


if __name__ == "__main__":
    unittest.main()
