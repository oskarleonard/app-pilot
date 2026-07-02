#!/usr/bin/env python3
"""Failure-surfacing tests for idb_ui — run headless (NO simulator, NO idb).

The tap/tree path must never lie or die: a tap idb could not deliver returns
False (and says why on stderr) instead of masquerading as delivered, and a
hung companion / missing idb binary comes back as a clean failure — never an
uncaught TimeoutExpired/OSError traceback that kills the whole command mid-run.

We stub `target` in sys.modules (IDB → a path that does not exist) so the real
idb_ui imports without a sim; _run_idb's timeout branch is driven with sleep.

Run:  python3 mobile/core/test_idb_ui.py    (or `python3 -m pytest -q`)
"""
import contextlib
import io
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_target = types.ModuleType("target")
_target.IDB = "/nonexistent/idb-for-tests"
_target.UDID = "TEST-UDID"
sys.modules["target"] = _target
sys.modules.pop("idb_ui", None)  # drop any stub a sibling test file installed
import idb_ui  # noqa: E402  (the REAL module, bound to the stub target)


class RunIdbTests(unittest.TestCase):
    def test_timeout_is_failure_not_traceback(self):
        out = idb_ui._run_idb(["/bin/sleep", "5"], timeout=0.2)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("timed out", out.stderr)

    def test_missing_binary_is_failure_not_traceback(self):
        out = idb_ui._run_idb(["/nonexistent/idb-for-tests", "ui"], timeout=5)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("cannot run", out.stderr)


class TapDeliveryTests(unittest.TestCase):
    def test_failed_tap_returns_false_and_reports(self):
        # THE regression this file exists for: a tap idb never delivered used
        # to be swallowed (rc ignored) and logged upstream as success.
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            ok = idb_ui.tap_point("TEST-UDID", 10, 20)
        self.assertIs(ok, False)
        self.assertIn("idb tap failed", buf.getvalue())

    def test_tap_frac_propagates_failure(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIs(idb_ui.tap_frac("TEST-UDID", 0.5, 0.5), False)

    def test_type_text_counts_undeliverable_chars(self):
        # A missing binary / hung companion counts per-char failures instead
        # of raising — the caller surfaces "N chars FAILED".
        self.assertEqual(idb_ui.type_text("TEST-UDID", "1.50"), 4)


class DescribeFailureTests(unittest.TestCase):
    def test_describe_failure_is_empty_tree_with_stderr_note(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            els = idb_ui.describe("TEST-UDID")
        self.assertEqual(els, [])
        self.assertIn("describe-all failed", buf.getvalue())

    def test_companion_alive_false_on_failure(self):
        self.assertFalse(idb_ui.companion_alive("TEST-UDID", timeout=2))

    def test_screen_size_falls_back_on_failure(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(idb_ui.screen_size("TEST-UDID"), (402, 874))


if __name__ == "__main__":
    unittest.main(verbosity=2)
