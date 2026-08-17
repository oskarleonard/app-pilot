"""Tests for runlog — the neutral run.json lifecycle.

Run:  python3 common/test_runlog.py     (or `python3 -m pytest -q`)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import runlog  # noqa: E402


class RunlogLifecycle(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-x")
        self.addCleanup(shutil.rmtree, self.run_dir, True)

    def read(self):
        with open(os.path.join(self.run_dir, "run.json")) as fh:
            return json.load(fh)

    def test_open_stamps_running_record(self):
        record = runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x", target="repo#7", env="staging")
        on_disk = self.read()
        self.assertEqual(record, on_disk)
        self.assertEqual(on_disk["schema"], runlog.SCHEMA)
        self.assertEqual(on_disk["status"], "running")
        self.assertEqual(on_disk["runId"], os.path.basename(self.run_dir))
        self.assertEqual(on_disk["target"], "repo#7")
        self.assertTrue(on_disk["startedAt"].endswith("Z"))
        self.assertNotIn("endedAt", on_disk)

    def test_open_omits_absent_optionals(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        on_disk = self.read()
        self.assertNotIn("target", on_disk)
        self.assertNotIn("env", on_disk)

    def test_open_is_idempotent(self):
        first = runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        second = runlog.open_run(self.run_dir, "rig-b", "other", "different")
        self.assertEqual(first, second)
        self.assertEqual(self.read()["rig"], "rig-a")

    def test_close_merges_onto_open(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        findings = [{"id": "f1", "severity": "high", "title": "boom", "ticket": "TRI-1"}]
        runlog.close_run(self.run_dir, "done", verdict="mixed", findings=findings, cost_usd=1.25)
        on_disk = self.read()
        self.assertEqual(on_disk["status"], "done")
        self.assertEqual(on_disk["verdict"], "mixed")
        self.assertEqual(on_disk["findings"], findings)
        self.assertEqual(on_disk["costUsd"], 1.25)
        self.assertEqual(on_disk["rig"], "rig-a")  # open fields survive
        self.assertIn("endedAt", on_disk)

    def test_close_rejects_bad_vocabulary(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "running")
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", verdict="meh")

    def test_close_survives_corrupt_open_record(self):
        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
            fh.write("{ not json")
        record = runlog.close_run(self.run_dir, "failed")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(self.read()["runId"], os.path.basename(self.run_dir))

    def test_close_without_open_records_what_it_knows(self):
        record = runlog.close_run(self.run_dir, "abandoned")
        self.assertEqual(record["status"], "abandoned")
        self.assertIn("startedAt", record)

    def test_no_tmp_residue(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        runlog.close_run(self.run_dir, "done")
        self.assertEqual(sorted(os.listdir(self.run_dir)), ["run.json"])


class RunlogCli(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-cli")
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        self.script = os.path.join(os.path.dirname(__file__), "runlog.py")

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, self.script, *args], capture_output=True, text=True
        )

    def test_open_then_close_roundtrip(self):
        opened = self.cli("open", self.run_dir, "--rig", "rig-a", "--scope", "s", "--goal", "g")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertEqual(json.loads(opened.stdout)["status"], "running")

        findings_path = os.path.join(self.run_dir, "..", "findings-tmp.json")
        with open(findings_path, "w") as fh:
            json.dump([{"id": "f1", "severity": "low", "title": "t"}], fh)
        self.addCleanup(os.remove, findings_path)

        closed = self.cli(
            "close", self.run_dir, "--status", "done", "--verdict", "pass",
            "--findings", findings_path, "--cost-usd", "0.5",
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        record = json.loads(closed.stdout)
        self.assertEqual(record["verdict"], "pass")
        self.assertEqual(len(record["findings"]), 1)

    def test_missing_run_dir_errors(self):
        gone = self.cli("open", "/nonexistent/run/dir", "--rig", "r", "--scope", "s", "--goal", "g")
        self.assertNotEqual(gone.returncode, 0)

    def test_non_array_findings_file_errors(self):
        self.cli("open", self.run_dir, "--rig", "r", "--scope", "s", "--goal", "g")
        findings_path = os.path.join(self.run_dir, "..", "findings-bad.json")
        with open(findings_path, "w") as fh:
            json.dump({"not": "an array"}, fh)
        self.addCleanup(os.remove, findings_path)
        bad = self.cli("close", self.run_dir, "--status", "done", "--findings", findings_path)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
