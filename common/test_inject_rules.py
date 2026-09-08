#!/usr/bin/env python3
"""inject_rules — the two managed AGENTS.md blocks + the mobile ios-pin assertion.

Covers: both blocks inserted into a marker-less AGENTS.md; refresh is idempotent;
the pre-release/live variant is chosen from target.py's RELEASE; the ios-pin
assertion passes/fails on a synthetic package.json; --fix preserves existing
flags (and replaces a hardcoded --device / adds a missing script); web rigs skip
the pin check; a hand-pasted stray copy of the release rule is reported.

Run:  python3 -m pytest -q   (or `python3 common/test_inject_rules.py`)
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import inject_rules  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="inject-rules-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.agents = os.path.join(self.root, "AGENTS.md")
        self.write(self.agents, "# My App\n\nSome prose.\n")
        self.rig = os.path.join(self.root, "scripts", "app-pilot")
        os.makedirs(self.rig)

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def target(self, text):
        self.write(os.path.join(self.rig, "target.py"), text)

    def pkg(self, scripts, name="myapp"):
        self.write(os.path.join(self.root, "package.json"),
                   json.dumps({"name": name, "scripts": scripts}, indent=2) + "\n")

    def ios_of(self):
        return json.loads(self.read(os.path.join(self.root, "package.json")))["scripts"].get("ios")

    def read_agents(self):
        return self.read(self.agents)

    def run_main(self, *argv):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf):
            try:
                inject_rules.main([self.root, *argv])
            except SystemExit as e:
                code = e.code or 0
        return code, buf.getvalue()


class Blocks(Base):
    def test_both_blocks_inserted_when_none(self):
        self.target('DEVICE_NAME = "iPhone 16 Pro"\n')
        self.pkg({"ios": inject_rules.IOS_CANONICAL})
        code, out = self.run_main()
        agents = self.read_agents()
        self.assertIn(inject_rules.RULES_BEGIN, agents)
        self.assertIn(inject_rules.RULES_END, agents)
        self.assertIn(inject_rules.RELEASE_BEGIN, agents)
        self.assertIn(inject_rules.RELEASE_END, agents)
        self.assertIn("PRE-RELEASE", agents)  # default when RELEASE is absent
        self.assertIn("Some prose.", agents)  # original content preserved
        self.assertEqual(code, 0)
        self.assertNotIn("hand-pasted", out.lower())  # no false stray report

    def test_refresh_is_idempotent(self):
        self.target('DEVICE_NAME = "iPhone 16 Pro"\nRELEASE = "pre-release"\n')
        self.pkg({"ios": inject_rules.IOS_CANONICAL})
        self.run_main()
        first = self.read_agents()
        self.run_main()
        second = self.read_agents()
        self.assertEqual(first, second)
        self.assertEqual(first.count(inject_rules.RELEASE_BEGIN), 1)  # not duplicated

    def test_live_variant_selected(self):
        self.target('DEVICE_NAME = "iPhone 16 Pro"\nRELEASE = "live"\n')
        self.pkg({"ios": inject_rules.IOS_CANONICAL})
        _, out = self.run_main()
        agents = self.read_agents()
        self.assertIn("LIVE", agents)
        self.assertIn("forward-only", agents)
        self.assertNotIn("PRE-RELEASE", agents)
        self.assertIn("RELEASE=live", out)

    def test_stray_release_copy_reported_but_untouched(self):
        prose = "# App\n\nWe keep no legacy fallbacks (wipe-and-reinstall dev data).\n"
        self.write(self.agents, prose)
        self.target('DEVICE_NAME = "iPhone 16 Pro"\n')
        self.pkg({"ios": inject_rules.IOS_CANONICAL})
        _, out = self.run_main()
        self.assertIn("hand-pasted", out.lower())
        self.assertIn("wipe-and-reinstall dev data", self.read_agents())  # left alone


class IosPin(Base):
    def test_pass_when_pinned(self):
        self.pkg({"ios": "expo run:ios --device $(python3 scripts/app-pilot/target.py --udid)"})
        mark, _ = inject_rules.check_ios_pin(self.root)
        self.assertEqual(mark, "PASS")

    def test_fail_when_bare(self):
        self.pkg({"ios": "expo run:ios"})
        mark, msg = inject_rules.check_ios_pin(self.root)
        self.assertEqual(mark, "FAIL")
        self.assertIn("target.py --udid", msg)

    def test_fix_preserves_existing_flags(self):
        self.pkg({"ios": "expo run:ios --port 8092 --no-build-cache"})
        mark, _ = inject_rules.check_ios_pin(self.root, fix=True)
        self.assertEqual(mark, "fixed")
        ios = self.ios_of()
        self.assertIn(inject_rules.IOS_PIN, ios)
        self.assertIn("--port 8092", ios)
        self.assertIn("--no-build-cache", ios)
        # idempotent: a second check passes with no further change
        self.assertEqual(inject_rules.check_ios_pin(self.root)[0], "PASS")

    def test_fix_replaces_hardcoded_device(self):
        self.pkg({"ios": "expo run:ios --device ABC-123-UDID --port 8092"})
        inject_rules.check_ios_pin(self.root, fix=True)
        ios = self.ios_of()
        self.assertNotIn("ABC-123-UDID", ios)
        self.assertIn("target.py --udid", ios)
        self.assertIn("--port 8092", ios)
        self.assertEqual(ios.count("--device"), 1)  # no duplicate device flag

    def test_fix_adds_missing_ios_script(self):
        self.pkg({"start": "expo start"})
        mark, _ = inject_rules.check_ios_pin(self.root, fix=True)
        self.assertEqual(mark, "fixed")
        scripts = json.loads(self.read(os.path.join(self.root, "package.json")))["scripts"]
        self.assertEqual(scripts["ios"], inject_rules.IOS_CANONICAL)
        self.assertEqual(scripts["start"], "expo start")  # sibling script preserved

    def test_skip_when_no_package_json(self):
        mark, _ = inject_rules.check_ios_pin(self.root)
        self.assertEqual(mark, "SKIP")

    def test_doctor_helper_shapes(self):
        self.pkg({"ios": inject_rules.IOS_CANONICAL})
        self.assertEqual(inject_rules.ios_pin_check(self.root), (True, ""))
        self.pkg({"ios": "expo run:ios"})
        ok, hint = inject_rules.ios_pin_check(self.root)
        self.assertFalse(ok)
        self.assertIn("target.py --udid", hint)
        os.remove(os.path.join(self.root, "package.json"))
        self.assertEqual(inject_rules.ios_pin_check(self.root), (None, ""))


class RigDetection(Base):
    def test_web_rig_skips_pin_check(self):
        # web rig: no DEVICE_NAME. An absent ios script must NOT fail the command.
        self.target('TESTER_PORT = 3002\nSERVER_CMD = ["bun", "run", "dev"]\n')
        self.pkg({"dev": "next dev"})
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("skipped", out.lower())
        self.assertNotIn("[FAIL]", out)

    def test_mobile_unpinned_exits_1(self):
        self.target('DEVICE_NAME = "iPhone 16 Pro"\n')
        self.pkg({"ios": "expo run:ios"})
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_mobile_fix_via_main_exits_0(self):
        self.target('DEVICE_NAME = "iPhone 16 Pro"\n')
        self.pkg({"ios": "expo run:ios --port 8092"})
        code, _ = self.run_main("--fix")
        self.assertEqual(code, 0)
        ios = self.ios_of()
        self.assertIn("target.py --udid", ios)
        self.assertIn("--port 8092", ios)

    def test_release_default_and_mobile_detection_helpers(self):
        self.assertEqual(inject_rules.read_release(""), "pre-release")
        self.assertEqual(inject_rules.read_release('RELEASE = "live"'), "live")
        self.assertEqual(inject_rules.read_release('# RELEASE = "live"'), "pre-release")  # comment ignored
        self.assertTrue(inject_rules.is_mobile_rig('DEVICE_NAME = "iPhone 16 Pro"'))
        self.assertTrue(inject_rules.is_mobile_rig("UDID = targetkit.resolve_udid(DEVICE_NAME, ...)"))
        self.assertFalse(inject_rules.is_mobile_rig('TESTER_PORT = 3002\nSERVER_CMD = []'))


if __name__ == "__main__":
    unittest.main()
