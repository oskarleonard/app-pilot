#!/usr/bin/env python3
"""Verdict-reliability tests for the mobile engine — run headless (NO simulator).

Covers the ways `health` could report a verdict greener (or redder) than reality:
  1. crashlog.fatal_hits() — only the high-confidence FATAL subset gates health,
     soft/advisory markers do not (no false FAIL on a healthy app).
  2. app_state() — springboard/launcher checked BEFORE the app, springboard by
     exact (badge-tolerant) icon match, so a missed launch (home screen frontmost,
     any locale) doesn't read as the app and an in-app "Open in Safari" button
     doesn't read as the home screen.
  3. verdict() — the pure pass/fail decision, tested directly (no monkeypatching).
  4. cmd_health() exit code folds the crash gate + verdict in.

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

    def test_missed_launch_home_screen_beats_colliding_app_label(self):
        # Home screen is checked BEFORE the app, so even an APP_LABEL that collides
        # with a system-app icon ("settings"/"home") can't make a missed launch
        # read as the app. Regression: the old order returned "app" here — the
        # worst-class false PASS.
        self.assertEqual(
            self._state("Phone", "Safari", "Settings", "Home", "Messages"),
            "springboard")

    def test_badged_springboard_icon_still_detected(self):
        # iOS icon a11y labels carry a badge suffix (", N new items"); the exact
        # icon match is anchored at the label head, so it still matches.
        self.assertEqual(
            self._state("Phone", "Safari, 3 new items", "Settings"), "springboard")

    def test_app_screen_with_open_in_safari_is_not_springboard(self):
        # "safari" is a substring of "Open in Safari", but springboard is an EXACT
        # icon match, so a real app screen with that button is NOT misread as the
        # home screen. Regression: the substring check returned "springboard"
        # (a false FAIL). Legacy rig → falls through to the optimistic 'app'.
        _target.APP_LABELS = []
        self.assertEqual(self._state("My Feed", "Open in Safari", "Compose"), "app")

    def test_app_exclusive_label_absent_on_home_screen_is_not_app(self):
        # The real protection against a false PASS is app-EXCLUSIVE labels: a home
        # screen never carries them, so even with no Safari icon visible it reads
        # 'unknown', never 'app'.
        _target.APP_LABELS = ["my feed", "compose"]
        self.assertEqual(self._state("Phone", "Calendar", "Photos"), "unknown")

    def test_none_label_config_degrades_without_crashing(self):
        # A rig may PIN a label var to None rather than omit it — getattr's default
        # only fires when the attr is ABSENT, so app_state must still not TypeError.
        for attr in ("LAUNCHER_LABELS", "SPRINGBOARD_LABELS", "APP_LABELS"):
            self.addCleanup(setattr, _target, attr, getattr(_target, attr))
            setattr(_target, attr, None)
        # Nothing can match → falls through to the legacy optimistic default, no crash.
        self.assertEqual(self._state("Mystery", "Screen"), "app")


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

    def test_empty_patterns_matches_nothing_not_all(self):
        # hits(patterns=[]) means "match nothing" — it must NOT silently fall back
        # to the full advisory PATTERNS set (the `[] or PATTERNS` trap).
        _, total, _ = crashlog.hits(patterns=[])
        self.assertEqual(total, 0)

    def test_fatal_hits_zero_when_no_log(self):
        _target.CRASHLOG = "/tmp/this-file-does-not-exist-xyz.log"
        self.assertEqual(crashlog.fatal_hits(), ([], 0, 0))


class HealthGateTests(unittest.TestCase):
    """cmd_health exit code = the verdict. All pillars up + no fatal → 0; a fatal
    crash flips it to 1 even when everything else is green."""

    def setUp(self):
        # Restore the real module callables after each test so these patches (and
        # the per-test crashlog.fatal_hits stubs below) can't leak into another
        # test class by execution order. getattr is read here, pre-patch.
        for mod, name in ((devserver, "metro_ok"), (devserver, "app_state"),
                          (crashlog, "fatal_hits"), (_idb, "companion_alive")):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
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


class VerdictTests(unittest.TestCase):
    """The pure pass/fail policy — green iff every pillar is up, the app is
    frontmost, and no fatal crash. Tested directly: no monkeypatching, no stdout
    capture, no SystemExit, so the engine's most safety-critical line is the one
    thing that's trivially and exhaustively checkable."""

    def test_all_green_is_pass(self):
        self.assertTrue(devserver.verdict(True, True, True, "app", 0))

    def test_each_pillar_down_fails(self):
        self.assertFalse(devserver.verdict(False, True, True, "app", 0))  # metro
        self.assertFalse(devserver.verdict(True, False, True, "app", 0))  # backend
        self.assertFalse(devserver.verdict(True, True, False, "app", 0))  # companion

    def test_non_app_state_fails(self):
        for state in ("springboard", "launcher", "unknown"):
            self.assertFalse(devserver.verdict(True, True, True, state, 0))

    def test_fatal_crash_fails_even_when_all_else_green(self):
        self.assertFalse(devserver.verdict(True, True, True, "app", 1))

    def test_returns_strict_bool(self):
        self.assertIs(devserver.verdict(True, True, True, "app", 0), True)
        self.assertIs(devserver.verdict(True, True, True, "app", 5), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
