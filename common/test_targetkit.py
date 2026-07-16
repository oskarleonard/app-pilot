#!/usr/bin/env python3
"""ensure_product_mount — the product.pin → symlink lifecycle.

A pin file redirects product/ to a shared checkout (env override wins); the
first redirect migrates the committed real dir to product.local/, a missing
pin target degrades to that fallback with a stderr hint, and pin-less
projects are never touched.

Run:  python3 common/test_targetkit.py     (or `python3 -m pytest -q`)
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import targetkit  # noqa: E402


class EnsureProductMount(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="targetkit-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.adapter = os.path.join(self.root, "proj", "scripts", "app-pilot")
        os.makedirs(self.adapter)
        self.target_py = os.path.join(self.adapter, "target.py")
        open(self.target_py, "w").write("# pin\n")
        os.environ.pop("APP_PILOT_PRODUCT_DIR", None)

    def _shared(self, name, marker):
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "FIGMA_MAP.md"), "w").write(marker + "\n")
        return d

    def _local(self, dirname, marker):
        d = os.path.join(self.adapter, dirname)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "FIGMA_MAP.md"), "w").write(marker + "\n")

    def _pin(self, line):
        open(os.path.join(self.adapter, "product.pin"), "w").write(line + "\n")

    def _mount(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            targetkit.ensure_product_mount(self.target_py)
        return os.path.join(self.adapter, "product"), err.getvalue()

    def _marker(self, mount):
        return open(os.path.join(mount, "FIGMA_MAP.md")).read().strip()

    def test_no_pin_is_a_noop(self):
        self._local("product", "local")
        mount, err = self._mount()
        self.assertTrue(os.path.isdir(mount))
        self.assertFalse(os.path.islink(mount))
        self.assertEqual(err, "")

    def test_pin_migrates_real_dir_and_symlinks(self):
        self._shared("qa", "shared")
        self._local("product", "local")
        self._pin(os.path.join("..", "..", "..", "qa"))
        mount, _ = self._mount()
        self.assertTrue(os.path.islink(mount))
        self.assertEqual(self._marker(mount), "shared")
        self.assertEqual(
            open(os.path.join(self.adapter, "product.local", "FIGMA_MAP.md")).read().strip(),
            "local",
        )

    def test_missing_pin_target_falls_back_to_local(self):
        self._local("product.local", "fallback")
        self._pin("../nowhere")
        mount, err = self._mount()
        self.assertTrue(os.path.islink(mount))
        self.assertEqual(self._marker(mount), "fallback")
        self.assertIn("product pin target missing", err)

    def test_missing_pin_target_without_fallback_mounts_nothing(self):
        self._pin("../nowhere")
        mount, err = self._mount()
        self.assertFalse(os.path.lexists(mount))
        self.assertIn("product pin target missing", err)

    def test_repoint_when_pin_changes(self):
        qa1 = self._shared("qa1", "qa1")
        self._shared("qa2", "qa2")
        self._pin(qa1)  # absolute pins work too
        mount, _ = self._mount()
        self.assertEqual(self._marker(mount), "qa1")
        self._pin(os.path.join(self.root, "qa2"))
        mount, _ = self._mount()
        self.assertEqual(self._marker(mount), "qa2")

    def test_env_var_beats_pin(self):
        env_dir = self._shared("qa-env", "env")
        self._local("product.local", "fallback")
        self._pin("../nowhere")
        os.environ["APP_PILOT_PRODUCT_DIR"] = env_dir
        try:
            mount, err = self._mount()
        finally:
            del os.environ["APP_PILOT_PRODUCT_DIR"]
        self.assertEqual(self._marker(mount), "env")
        self.assertEqual(err, "")

    def test_pin_local_beats_committed_pin(self):
        self._shared("qa-team", "team")
        self._shared("qa-mine", "mine")
        self._pin(os.path.join(self.root, "qa-team"))
        open(os.path.join(self.adapter, "product.pin.local"), "w").write(
            os.path.join(self.root, "qa-mine") + "\n"
        )
        mount, err = self._mount()
        self.assertEqual(self._marker(mount), "mine")
        self.assertEqual(err, "")

    def test_empty_pin_local_falls_back_to_committed_pin(self):
        self._shared("qa-team2", "team")
        self._pin(os.path.join(self.root, "qa-team2"))
        open(os.path.join(self.adapter, "product.pin.local"), "w").write("\n")
        mount, _ = self._mount()
        self.assertEqual(self._marker(mount), "team")

    def test_env_var_beats_pin_local(self):
        env_dir = self._shared("qa-env2", "env")
        self._shared("qa-mine2", "mine")
        open(os.path.join(self.adapter, "product.pin.local"), "w").write(
            os.path.join(self.root, "qa-mine2") + "\n"
        )
        self._pin("../nowhere")
        os.environ["APP_PILOT_PRODUCT_DIR"] = env_dir
        try:
            mount, _ = self._mount()
        finally:
            del os.environ["APP_PILOT_PRODUCT_DIR"]
        self.assertEqual(self._marker(mount), "env")

    def test_both_real_dirs_refuses(self):
        self._shared("qa3", "shared")
        self._local("product", "local")
        self._local("product.local", "fallback")
        self._pin(os.path.join(self.root, "qa3"))
        mount, err = self._mount()
        self.assertTrue(os.path.isdir(mount))
        self.assertFalse(os.path.islink(mount))
        self.assertIn("not mounting", err)


class ApplyLocal(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="targetkit-local-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.target_py = os.path.join(self.root, "target.py")
        open(self.target_py, "w").write("# pin\n")

    def _overlay(self, src):
        open(os.path.join(self.root, "target.local.py"), "w").write(src)

    def test_missing_overlay_is_a_noop(self):
        ns = {"TESTER_PORT": 3002}
        targetkit.apply_local(ns, self.target_py)
        self.assertEqual(ns["TESTER_PORT"], 3002)

    def test_overlay_overrides_knobs(self):
        self._overlay("TESTER_PORT = 3103\nDEVICE_NAME = 'iPhone 15'\n")
        ns = {"TESTER_PORT": 3002}
        targetkit.apply_local(ns, self.target_py)
        self.assertEqual(ns["TESTER_PORT"], 3103)
        self.assertEqual(ns["DEVICE_NAME"], "iPhone 15")

    def test_overlay_can_use_prior_knobs(self):
        # exec'd into the SAME namespace — an override may derive from team values.
        self._overlay("TESTER_PORT = TESTER_PORT + 100\n")
        ns = {"TESTER_PORT": 3002}
        targetkit.apply_local(ns, self.target_py)
        self.assertEqual(ns["TESTER_PORT"], 3102)

    def test_overlay_errors_carry_its_path(self):
        self._overlay("TESTER_PORT = \n")
        with self.assertRaises(SyntaxError) as ctx:
            targetkit.apply_local({}, self.target_py)
        self.assertIn("target.local.py", ctx.exception.filename or "")


class TesterPort(unittest.TestCase):
    """tester_port — the uniform APP_PILOT_PORT override at the knob site."""

    def setUp(self):
        os.environ.pop("APP_PILOT_PORT", None)
        self.addCleanup(os.environ.pop, "APP_PILOT_PORT", None)

    def test_default_without_env(self):
        self.assertEqual(targetkit.tester_port(3002), 3002)

    def test_env_override_wins(self):
        os.environ["APP_PILOT_PORT"] = "3207"
        self.assertEqual(targetkit.tester_port(3002), 3207)

    def test_blank_env_keeps_default(self):
        os.environ["APP_PILOT_PORT"] = "  "
        self.assertEqual(targetkit.tester_port(3002), 3002)

    def test_junk_env_exits_loudly(self):
        os.environ["APP_PILOT_PORT"] = "not-a-port"
        with self.assertRaises(SystemExit):
            targetkit.tester_port(3002)

    def test_out_of_range_env_exits_loudly(self):
        # int()-parseable but unusable: 0 makes lsof/APP_URL match nothing, so
        # stop/kill_port silently no-op. The parse guard must reject these too.
        for raw in ("0", "-1", "65536", "99999"):
            os.environ["APP_PILOT_PORT"] = raw
            with self.assertRaises(SystemExit, msg=f"{raw} should exit"):
                targetkit.tester_port(3002)


class ResolveUdidPrecedence(unittest.TestCase):
    """resolve_udid — rig env > APP_PILOT_UDID (uniform) > target.local pin.

    Discovery never runs here: every case satisfies an earlier rung, so the
    tests stay hermetic (no simctl)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="targetkit-udid-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.near = os.path.join(self.root, "target.py")
        open(self.near, "w").write("# pin\n")
        for var in ("X_QA_UDID", "APP_PILOT_UDID"):
            os.environ.pop(var, None)
            self.addCleanup(os.environ.pop, var, None)

    def _pin(self, udid):
        open(os.path.join(self.root, "target.local"), "w").write(udid + "\n")

    def test_rig_env_beats_uniform_env(self):
        os.environ["X_QA_UDID"] = "RIG-UDID"
        os.environ["APP_PILOT_UDID"] = "UNIFORM-UDID"
        self.assertEqual(
            targetkit.resolve_udid("iPhone 16 Pro", "X_QA_UDID", self.near),
            "RIG-UDID",
        )

    def test_uniform_env_beats_pin_file(self):
        os.environ["APP_PILOT_UDID"] = "UNIFORM-UDID"
        self._pin("PINNED-UDID")
        self.assertEqual(
            targetkit.resolve_udid("iPhone 16 Pro", "X_QA_UDID", self.near),
            "UNIFORM-UDID",
        )

    def test_pin_file_when_no_env(self):
        self._pin("PINNED-UDID")
        self.assertEqual(
            targetkit.resolve_udid("iPhone 16 Pro", "X_QA_UDID", self.near),
            "PINNED-UDID",
        )

    def test_blank_env_falls_through_to_pin(self):
        # Same "blank = unset" rule as tester_port — an orchestrator emitting
        # an empty APP_PILOT_UDID must not hand whitespace to simctl/idb.
        os.environ["APP_PILOT_UDID"] = "   "
        self._pin("PINNED-UDID")
        self.assertEqual(
            targetkit.resolve_udid("iPhone 16 Pro", "X_QA_UDID", self.near),
            "PINNED-UDID",
        )


if __name__ == "__main__":
    unittest.main()
