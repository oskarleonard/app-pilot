#!/usr/bin/env python3
"""Verdict-reliability tests for the mobile engine — run headless (NO simulator).

Covers the two ways `health` could report a verdict greener than reality:
  1. crashlog.fatal_hits() — only the high-confidence FATAL subset gates health,
     soft/advisory markers do not (no false FAIL on a healthy app).
  2. app_state() — POSITIVE app detection + locale-safe springboard, so a missed
     launch (home screen frontmost, any locale) never reads as the running app.
  3. cmd_health() exit code folds the crash gate in (a crashed app fails health).

We stub `target`/`idb_ui`/`common` in sys.modules so the real `crashlog` and
`devserver` import without a sim, then drive the pure classification/gate logic.

Run:  python3 mobile/core/test_verdict.py    (or `python3 -m unittest` from core/)
"""
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so `import crashlog` / `import devserver` find the real modules

# ── stub the sim-bound deps BEFORE importing the engine ──────────────────────
_target = types.ModuleType("target")
_target.UDID = "ABC12345-0000-0000-0000-000000000000"
_target.PORT = 8092
_target.MODE = "mock"
_target.BUNDLE = "com.example.myapp.dev"
_target.SCHEME = "myapp"
_target.METRO_LOG = "/tmp/test-verdict-metro.log"
_target.PIDFILE = "/tmp/test-verdict-metro.pid"
_target.CRASHLOG = "/tmp/test-verdict-crash.log"
_target.CRASHLOG_PID = "/tmp/test-verdict-crash.pid"
_target.IDB = "/tmp/idb-does-not-exist"
_target.LAUNCHER_LABELS = ["development servers", "failed to load app"]
_target.APP_LABELS = ["home", "settings"]
_target.SPRINGBOARD_LABELS = ["safari"]
# no BACKEND_URL → LOCAL_BACKEND_URL is None → backend pillar is a no-op
sys.modules["target"] = _target

_idb = types.ModuleType("idb_ui")
_idb.labelled = lambda udid: []          # tests override per-case
_idb.companion_alive = lambda udid, timeout=5: True
sys.modules["idb_ui"] = _idb

sys.modules["common"] = types.ModuleType("common")

import crashlog   # noqa: E402  (real module, uses the stub target)
import devserver  # noqa: E402  (real module, uses the stubs)


def _els(*labels):
    return [types.SimpleNamespace(label=l) for l in labels]


class AppStateTests(unittest.TestCase):
    def setUp(self):
        _target.APP_LABELS = ["home", "settings"]
        _target.SPRINGBOARD_LABELS = ["safari"]

    def _state(self, *labels):
        _idb.labelled = lambda udid, _l=labels: _els(*_l)
        return devserver.app_state()

    def test_empty_tree_is_unknown(self):
        _idb.labelled = lambda udid: []
        self.assertEqual(devserver.app_state(), "unknown")

    def test_launcher_detected(self):
        self.assertEqual(self._state("Development servers", "Enter URL manually"), "launcher")

    def test_app_positive_match(self):
        self.assertEqual(self._state("Home", "Profile", "Some content"), "app")

    def test_swedish_home_screen_is_springboard_not_app(self):
        # THE regression the brief flagged: old code required "messages" (English)
        # so a Swedish dock ("Meddelanden") fell through to a false 'app'.
        self.assertEqual(self._state("Telefon", "Safari", "Meddelanden", "Musik"), "springboard")

    def test_english_home_screen_is_springboard(self):
        self.assertEqual(self._state("Phone", "Safari", "Messages", "Music"), "springboard")

    def test_configured_rig_no_signal_is_unknown_not_app(self):
        # APP_LABELS set + none visible + not launcher/springboard → 'unknown'
        # (a missed launch can never read as the running app).
        self.assertEqual(self._state("Mystery", "Screen"), "unknown")

    def test_legacy_rig_without_app_labels_keeps_optimistic_default(self):
        _target.APP_LABELS = []  # legacy rig
        self.assertEqual(self._state("Mystery", "Screen"), "app")

    def test_legacy_rig_still_catches_home_screen(self):
        _target.APP_LABELS = []
        self.assertEqual(self._state("Phone", "Safari", "Messages"), "springboard")


class CrashGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".log")
        self.tmp.write("\n".join([
            "10:00 app[1]: RCTFatal: redbox shown",                 # FATAL + advisory
            "10:00 app[1]: Thread 0 crashed EXC_BAD_ACCESS",        # FATAL + advisory
            "10:00 app[1]: Possible Unhandled Promise Rejection",   # advisory only
            "10:00 app[1]: ExceptionsManager soft report",          # advisory only
            "10:00 app[1]: Running application MyApp",              # neither
        ]) + "\n")
        self.tmp.close()
        _target.CRASHLOG = self.tmp.name

    def tearDown(self):
        os.unlink(self.tmp.name)
        _target.CRASHLOG = "/tmp/test-verdict-crash.log"

    def test_advisory_hits_count_all_patterns(self):
        _, total, _ = crashlog.hits()
        self.assertEqual(total, 4)

    def test_fatal_hits_count_only_fatal_subset(self):
        _, fatal, _ = crashlog.fatal_hits()
        self.assertEqual(fatal, 2)

    def test_fatal_hits_zero_when_no_log(self):
        _target.CRASHLOG = "/tmp/this-file-does-not-exist-xyz.log"
        self.assertEqual(crashlog.fatal_hits(), ([], 0, 0))


class HealthGateTests(unittest.TestCase):
    """cmd_health exit code = the verdict. All pillars up + no fatal → 0; a fatal
    crash flips it to 1 even when everything else is green."""

    def setUp(self):
        devserver.metro_ok = lambda: True
        _idb.companion_alive = lambda udid, timeout=5: True
        devserver.app_state = lambda: "app"

    def _exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                devserver.cmd_health(None)
                return 0
            except SystemExit as e:
                return e.code or 0

    def test_all_green_no_crash_passes(self):
        crashlog.fatal_hits = lambda: ([], 0, 0)
        self.assertEqual(self._exit_code(), 0)

    def test_fatal_crash_fails_even_when_all_else_green(self):
        crashlog.fatal_hits = lambda: (["RCTFatal: boom"], 1, 9)
        self.assertEqual(self._exit_code(), 1)

    def test_app_not_frontmost_fails(self):
        crashlog.fatal_hits = lambda: ([], 0, 0)
        devserver.app_state = lambda: "springboard"
        self.assertEqual(self._exit_code(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
