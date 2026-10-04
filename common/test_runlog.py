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
        # Fixtures get their OWN tmpdir — never fixed names in the shared
        # system temp dir (the parent of mkdtemp).
        self.fixtures = tempfile.mkdtemp(prefix="runlog-fixtures-")
        self.addCleanup(shutil.rmtree, self.fixtures, True)

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

    def test_non_dict_json_is_no_record(self):
        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
            fh.write("[]")
        record = runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        self.assertEqual(record["status"], "running")  # fresh dict, not the list
        runlog.close_run(self.run_dir, "done")  # must not crash on a non-dict
        self.assertEqual(self.read()["status"], "done")

    def test_close_rejects_non_finite_cost(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                runlog.close_run(self.run_dir, "done", cost_usd=bad)

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
        self.assertTrue(record["recovered"])  # labelled, not passed off as full

    def test_close_is_final(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        first = runlog.close_run(self.run_dir, "done", verdict="pass")
        # identical retry → idempotent no-op
        self.assertEqual(runlog.close_run(self.run_dir, "done", verdict="pass"), first)
        # a bare-status retry (omitted params) is still the same close
        self.assertEqual(runlog.close_run(self.run_dir, "done"), first)
        # any OTHER close of a settled record refuses
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "failed")
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", verdict="fail")
        self.assertEqual(self.read()["verdict"], "pass")

    def test_findings_file_rejects_non_finite(self):
        findings_path = os.path.join(self.fixtures, "findings-nan.json")
        with open(findings_path, "w") as fh:
            fh.write('[{"id":"f1","severity":"low","title":"t","score":NaN}]')
        with self.assertRaises(ValueError):
            runlog.load_findings(findings_path)

    def test_findings_file_rejects_non_object_entries(self):
        findings_path = os.path.join(self.fixtures, "findings-strings.json")
        with open(findings_path, "w") as fh:
            fh.write('["oops", [1, 2]]')
        with self.assertRaises(ValueError):
            runlog.load_findings(findings_path)

    def test_close_refuses_retry_with_different_findings(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        runlog.close_run(self.run_dir, "done", verdict="pass",
                         findings=[{"id": "f1", "severity": "low", "title": "a"}])
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", verdict="pass",
                             findings=[{"id": "f2", "severity": "high", "title": "b"}])
        # a bare retry (no findings supplied) is still the identical close
        runlog.close_run(self.run_dir, "done", verdict="pass")

    def test_corrupt_record_is_kept_aside_on_close(self):
        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
            fh.write("{ not json")
        runlog.close_run(self.run_dir, "failed")
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "run.json.corrupt")))

    def test_shapeless_dict_record_is_labelled_recovered(self):
        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
            fh.write("{}")
        record = runlog.close_run(self.run_dir, "done")
        self.assertTrue(record["recovered"])
        self.assertEqual(record["schema"], runlog.SCHEMA)

    def test_no_tmp_residue(self):
        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
        runlog.close_run(self.run_dir, "done")
        self.assertEqual(sorted(os.listdir(self.run_dir)), ["run.json"])


LEGACY_FINDING = {"id": "f1", "severity": "low", "title": "t", "ticket": "T-1"}

RICH_FINDING = {
    "id": "f2", "severity": "high", "title": "hero chart uses the wrong fill",
    "class": "parity", "expected": "accent fill per frame", "observed": "neutral fill",
    "designRef": {"fileKey": "abc123", "nodeId": "12:34", "band": "1.2",
                  "renderHash": "sha256:00ff", "render": "figma/home.png"},
    "region": {"image": "screens/home.png", "space": "points", "imageW": 390,
               "imageH": 844, "x": 16, "y": 120.5, "w": 358, "h": 200,
               "transform": {"scale": 3}},
    "repro": ["open home", "scroll to the chart"],
    "basis": "measured", "certainty": "confirmed", "judge": "added",
}

ORACLE_QUESTION = {
    "screen": "settings", "platform": "web", "statement": "brief says the toggle is hidden by design",
    "citations": ["brief line 4", "frame 12:40"], "suggestedRecipient": "product",
}


class RunlogFindingsRecord(unittest.TestCase):
    """The optional evidence fields and the gate — additive to schema 1."""

    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-rec")
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        self.fixtures = tempfile.mkdtemp(prefix="runlog-rec-fixtures-")
        self.addCleanup(shutil.rmtree, self.fixtures, True)

    def read(self):
        with open(os.path.join(self.run_dir, "run.json")) as fh:
            return json.load(fh)

    def write_json(self, name, payload):
        path = os.path.join(self.fixtures, name)
        with open(path, "w") as fh:
            json.dump(payload, fh)
        return path

    def test_legacy_closed_record_still_parses_and_retries(self):
        legacy = {"schema": 1, "runId": os.path.basename(self.run_dir), "rig": "r",
                  "scope": "s", "goal": "g", "startedAt": "2026-08-17T10:11:12Z",
                  "endedAt": "2026-08-17T11:00:00Z", "status": "done",
                  "verdict": "mixed", "findings": [LEGACY_FINDING]}
        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
            json.dump(legacy, fh)
        self.assertEqual(runlog.read_run(self.run_dir), legacy)
        self.assertEqual(runlog.close_run(self.run_dir, "done", verdict="mixed"), legacy)
        # a gate the legacy close never recorded is differing evidence
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", gate="INCOMPLETE", gate_reasons=["x"])

    def test_legacy_findings_file_still_loads(self):
        path = self.write_json("legacy.json", [LEGACY_FINDING, {"id": "f9"}])
        self.assertEqual(runlog.load_findings(path), [LEGACY_FINDING, {"id": "f9"}])

    def test_rich_finding_round_trips(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        path = self.write_json("rich.json", [LEGACY_FINDING, RICH_FINDING])
        findings = runlog.load_findings(path)
        runlog.close_run(self.run_dir, "done", verdict="fail", findings=findings,
                         gate="INCOMPLETE", gate_reasons=["settings: empty state not captured"],
                         oracle_questions=[ORACLE_QUESTION],
                         insufficient_evidence=[{"screen": "home", "need": "full-screen capture"}])
        on_disk = self.read()
        self.assertEqual(on_disk["findings"], [LEGACY_FINDING, RICH_FINDING])
        self.assertEqual(on_disk["gate"], "INCOMPLETE")
        self.assertEqual(on_disk["gateReasons"], ["settings: empty state not captured"])
        self.assertEqual(on_disk["oracleQuestions"], [ORACLE_QUESTION])
        self.assertEqual(on_disk["insufficientEvidence"][0]["screen"], "home")
        self.assertEqual(on_disk["verdict"], "fail")  # verdict stays alongside gate

    def test_close_without_new_fields_writes_none_of_them(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        runlog.close_run(self.run_dir, "done", verdict="pass", findings=[LEGACY_FINDING])
        on_disk = self.read()
        for key in ("gate", "gateReasons", "oracleQuestions", "insufficientEvidence"):
            self.assertNotIn(key, on_disk)

    def test_bad_finding_fields_refuse(self):
        bad = [
            {"class": "visual"}, {"basis": "guessed"}, {"certainty": "likely"},
            {"judge": "agreed"}, {"repro": "one string"}, {"expected": 3},
            {"designRef": "12:34"}, {"designRef": {"nodeId": "12:34"}},
            {"region": {**RICH_FINDING["region"], "space": "inches"}},
            {"region": {k: v for k, v in RICH_FINDING["region"].items() if k != "space"}},
            {"region": {**RICH_FINDING["region"], "x": True}},
            {"region": {**RICH_FINDING["region"], "imageW": 0}},
            {"region": {**RICH_FINDING["region"], "h": float("nan")}},
        ]
        for extra in bad:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    runlog.validate_finding({**LEGACY_FINDING, **extra})
        path = self.write_json("bad.json", [{**LEGACY_FINDING, "class": "visual"}])
        with self.assertRaises(ValueError):
            runlog.load_findings(path)

    def test_close_validates_findings_passed_directly(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", findings=[{**LEGACY_FINDING, "certainty": "maybe"}])
        self.assertEqual(self.read()["status"], "running")  # refused before any write

    def test_gate_rules(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        refused = [
            dict(status="done", gate="pass"),
            dict(status="done", gate="PASS_WITH_EXCEPTIONS"),  # exceptions undisclosed
            dict(status="done", gate="INCOMPLETE", gate_reasons=[]),  # gap unnamed
            dict(status="done", gate="INCOMPLETE", gate_reasons=["  "]),
            dict(status="failed", gate="PASS"),  # a dead run certifies nothing
            dict(status="abandoned", gate="PASS_WITH_EXCEPTIONS", gate_reasons=["x"]),
            dict(status="done", gate_reasons=["orphan reason"]),
        ]
        for kwargs in refused:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    runlog.close_run(self.run_dir, **kwargs)
        record = runlog.close_run(self.run_dir, "failed", gate="INCOMPLETE",
                                  gate_reasons=["lane died before settle"])
        self.assertEqual(record["gate"], "INCOMPLETE")

    def test_pass_needs_no_reasons(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        record = runlog.close_run(self.run_dir, "done", verdict="pass", gate="PASS")
        self.assertEqual(record["gate"], "PASS")
        self.assertNotIn("gateReasons", record)

    def test_gate_idempotency(self):
        runlog.open_run(self.run_dir, "rig-a", "s", "g")
        reasons = ["accepted-deviation: f2 — spacing token pending design update [frame 12:34]"]
        first = runlog.close_run(self.run_dir, "done", gate="PASS_WITH_EXCEPTIONS",
                                 gate_reasons=reasons)
        self.assertEqual(runlog.close_run(self.run_dir, "done", gate="PASS_WITH_EXCEPTIONS",
                                          gate_reasons=reasons), first)
        self.assertEqual(runlog.close_run(self.run_dir, "done"), first)
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", gate="PASS")
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", gate="PASS_WITH_EXCEPTIONS",
                             gate_reasons=["a different disclosure"])
        with self.assertRaises(ValueError):
            runlog.close_run(self.run_dir, "done", oracle_questions=[ORACLE_QUESTION])

    def test_oracle_question_and_recapture_shapes(self):
        bad_questions = [
            {k: v for k, v in ORACLE_QUESTION.items() if k != "statement"},
            {**ORACLE_QUESTION, "citations": []},
            {**ORACLE_QUESTION, "citations": "brief line 4"},
            {**ORACLE_QUESTION, "suggestedRecipient": "qa"},
            "a bare string",
        ]
        for question in bad_questions:
            with self.subTest(question=question):
                with self.assertRaises(ValueError):
                    runlog.validate_oracle_question(question)
        minimal = {"screen": "s", "statement": "x", "citations": ["c"]}
        runlog.validate_oracle_question(minimal)
        for entry in ({"screen": "home"}, {"need": "x"}, ["home"]):
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    runlog.validate_insufficient_evidence(entry)
        path = self.write_json("oq.json", {"not": "an array"})
        with self.assertRaises(ValueError):
            runlog.load_oracle_questions(path)


class RunlogCli(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-cli")
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        self.fixtures = tempfile.mkdtemp(prefix="runlog-cli-fixtures-")
        self.addCleanup(shutil.rmtree, self.fixtures, True)
        self.script = os.path.join(os.path.dirname(__file__), "runlog.py")

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, self.script, *args], capture_output=True, text=True
        )

    def test_open_then_close_roundtrip(self):
        opened = self.cli("open", self.run_dir, "--rig", "rig-a", "--scope", "s", "--goal", "g")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertEqual(json.loads(opened.stdout)["status"], "running")

        findings_path = os.path.join(self.fixtures, "findings-tmp.json")
        with open(findings_path, "w") as fh:
            json.dump([{"id": "f1", "severity": "low", "title": "t"}], fh)

        closed = self.cli(
            "close", self.run_dir, "--status", "done", "--verdict", "pass",
            "--findings", findings_path, "--cost-usd", "0.5",
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        record = json.loads(closed.stdout)
        self.assertEqual(record["verdict"], "pass")
        self.assertEqual(len(record["findings"]), 1)

    def test_close_with_gate_flags(self):
        self.cli("open", self.run_dir, "--rig", "r", "--scope", "s", "--goal", "g")
        oq_path = os.path.join(self.fixtures, "oq.json")
        with open(oq_path, "w") as fh:
            json.dump([ORACLE_QUESTION], fh)
        closed = self.cli(
            "close", self.run_dir, "--status", "done", "--verdict", "mixed",
            "--gate", "INCOMPLETE", "--gate-reason", "home: error state not captured",
            "--gate-reason", "settings: oracle unresolved", "--oracle-questions", oq_path,
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        record = json.loads(closed.stdout)
        self.assertEqual(record["gate"], "INCOMPLETE")
        self.assertEqual(len(record["gateReasons"]), 2)
        self.assertEqual(record["oracleQuestions"], [ORACLE_QUESTION])

    def test_bad_gate_flag_errors(self):
        self.cli("open", self.run_dir, "--rig", "r", "--scope", "s", "--goal", "g")
        bad = self.cli("close", self.run_dir, "--status", "done", "--gate", "GREEN")
        self.assertNotEqual(bad.returncode, 0)
        unnamed = self.cli("close", self.run_dir, "--status", "done", "--gate", "INCOMPLETE")
        self.assertNotEqual(unnamed.returncode, 0)

    def test_missing_run_dir_errors(self):
        gone = self.cli("open", "/nonexistent/run/dir", "--rig", "r", "--scope", "s", "--goal", "g")
        self.assertNotEqual(gone.returncode, 0)

    def test_non_array_findings_file_errors(self):
        self.cli("open", self.run_dir, "--rig", "r", "--scope", "s", "--goal", "g")
        findings_path = os.path.join(self.fixtures, "findings-bad.json")
        with open(findings_path, "w") as fh:
            json.dump({"not": "an array"}, fh)
        bad = self.cli("close", self.run_dir, "--status", "done", "--findings", findings_path)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
