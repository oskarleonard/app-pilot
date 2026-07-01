#!/usr/bin/env python3
"""Headless tests for the `app-pilot review` trigger (NO ensemble-ai / no network).

Covers the Phase-3 contract: the review step assembles the right ensemble-ai
argv, parses its typed trail into a host verdict, writes the smart trail
(summary.json + a findings.md pointer), and — the load-bearing one — DEGRADES
gracefully (skips, exit 0) when ensemble-ai is absent or review is disabled, so
an optional reviewer never fails the behavior QA pass.

We stub the environment (which_ensemble / run_ensemble / repo root) and drive the
pure logic + orchestration directly — the real reviewer CLIs never run.

Run:  python3 common/test_review.py     (or `python3 -m pytest -q`)
"""
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import review  # noqa: E402


def _args(**over):
    """A cmd_review args namespace with defaults; override per test."""
    base = dict(
        run=None, out=None, base=None, reviewers=None, run_id=None,
        pr=None, working_tree=False, staged=False, sandbox=None,
        allow_sensitive=False, fail_on_high=None, force=False, timeout=900,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _stored(reviewer_id, vendor, severities, state="reviewed"):
    """An ensemble-ai StoredReview (review.<id>.json) shape."""
    return {
        "findings": [
            {"severity": s, "title": f"{s} finding", "evidence": {"file": "a.ts", "line": 1}}
            for s in severities
        ],
        "reviewer": {"vendor": vendor, "model": f"{vendor}-model", "effort": "high"},
        "reviewerId": reviewer_id,
        "runId": "r",
        "summary": f"{reviewer_id} summary",
        "terminalState": state,
    }


class LoadConfig(unittest.TestCase):
    def _write_target(self, body):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "target.py"), "w") as fh:
            fh.write(body)
        return d

    def test_reads_review_dict(self):
        d = self._write_target("REVIEW = {'enabled': True, 'reviewers': ['codex']}\n")
        cfg = review.load_config(d)
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["reviewers"], ["codex"])

    def test_missing_dict_is_empty(self):
        d = self._write_target("TESTER_PORT = 3002\n")
        self.assertEqual(review.load_config(d), {})

    def test_no_target_is_empty(self):
        self.assertEqual(review.load_config(tempfile.mkdtemp()), {})

    def test_ast_read_never_executes_target(self):
        # A target.py that would sys.exit on IMPORT (like a mobile target.py with
        # no sim) must still yield its REVIEW dict — we AST-read, never execute.
        d = self._write_target(
            "import sys\nsys.exit('boom — this must NOT run')\n"
            "REVIEW = {'enabled': True}\n"
        )
        self.assertEqual(review.load_config(d), {"enabled": True})


class BuildArgv(unittest.TestCase):
    def test_config_and_overrides(self):
        cfg = {"reviewers": ["codex", "grok"], "base": "origin/dev", "allow_sensitive": True}
        argv = review.build_argv("ensemble-ai", "/out", "/repo", cfg, _args(), "rid1")
        self.assertEqual(argv[:5], ["ensemble-ai", "review", "--out", "/out", "--cwd"])
        self.assertEqual(argv[argv.index("--run-id") + 1], "rid1")  # always passed
        self.assertIn("--reviewers", argv)
        self.assertEqual(argv[argv.index("--reviewers") + 1], "codex,grok")
        self.assertEqual(argv[argv.index("--base") + 1], "origin/dev")
        self.assertIn("--allow-sensitive", argv)

    def test_cli_overrides_config(self):
        cfg = {"base": "origin/dev", "reviewers": ["codex"]}
        argv = review.build_argv("e", "/o", "/r", cfg, _args(base="origin/main", reviewers="grok"), "rid1")
        self.assertEqual(argv[argv.index("--base") + 1], "origin/main")
        self.assertEqual(argv[argv.index("--reviewers") + 1], "grok")

    def test_never_disables_the_high_gate(self):
        # app-pilot WANTS ensemble's exit 4 (HIGH) signal, so it must never pass
        # --no-fail-on-high to the CLI (the host applies its own policy on top).
        argv = review.build_argv("e", "/o", "/r", {}, _args(fail_on_high=False), "rid1")
        self.assertNotIn("--no-fail-on-high", argv)

    def test_pr_source(self):
        argv = review.build_argv("e", "/o", "/r", {}, _args(pr="42"), "rid1")
        self.assertEqual(argv[argv.index("--pr") + 1], "42")


class ParseTrail(unittest.TestCase):
    def _trail(self, files):
        d = tempfile.mkdtemp()
        for name, content in files.items():
            with open(os.path.join(d, name), "w") as fh:
                json.dump(content, fh)
        return d

    def test_counts_and_tallies(self):
        d = self._trail({
            "review.codex.json": _stored("codex", "openai", ["high", "medium"]),
            "review.grok.json": _stored("grok", "xai", []),
        })
        trail = review.parse_trail(d)
        self.assertEqual(trail["counts"], {"high": 1, "medium": 1, "low": 0})
        line = review.one_line(trail)
        self.assertIn("codex 1H/1M", line)
        self.assertIn("grok clean", line)

    def test_failed_reviewer_surfaced(self):
        d = self._trail({"review.grok.json": _stored("grok", "xai", [], state="failed")})
        trail = review.parse_trail(d)
        self.assertIn("grok failed", review.one_line(trail))

    def test_legacy_and_corrupt(self):
        d = self._trail({"review.json": _stored("codex", "openai", ["low"])})
        with open(os.path.join(d, "review.bad.json"), "w") as fh:
            fh.write("{not json")
        trail = review.parse_trail(d)
        self.assertEqual(trail["counts"]["low"], 1)  # legacy read, corrupt skipped

    def test_null_reviewer_does_not_crash(self):
        # A partial trail file with `reviewer` present-but-null must not crash
        # parse_trail (that would fail the whole QA pass — the one thing review
        # promises never to do).
        d = self._trail({"review.codex.json": {
            "reviewerId": "codex", "reviewer": None, "terminalState": "reviewed",
            "findings": [{"severity": "high"}]}})
        trail = review.parse_trail(d)  # no AttributeError
        self.assertEqual(trail["counts"]["high"], 1)
        self.assertIsNone(trail["reviewers"][0]["vendor"])

    def test_legacy_deduped_against_fanout(self):
        # A stray legacy review.json (codex) beside a real review.codex.json must
        # NOT double-count codex.
        d = self._trail({
            "review.json": _stored("codex", "openai", ["high"]),
            "review.codex.json": _stored("codex", "openai", ["high"]),
        })
        trail = review.parse_trail(d)
        self.assertEqual(trail["counts"]["high"], 1)  # not 2
        self.assertEqual([r["id"] for r in trail["reviewers"]], ["codex"])


class ComputeVerdict(unittest.TestCase):
    def _trail(self, h=0, m=0, low=0):
        return {"counts": {"high": h, "medium": m, "low": low}, "reviewers": []}

    def test_clean(self):
        v = review.compute_verdict(0, self._trail())
        self.assertEqual((v["status"], v["gate"]), ("clean", "pass"))

    def test_findings_but_no_high(self):
        v = review.compute_verdict(0, self._trail(m=2))
        self.assertEqual((v["status"], v["gate"]), ("findings", "pass"))

    def test_exit0_but_trail_has_high_is_fail(self):
        # ensemble exited 0 yet a HIGH sits in the trail — trust the trail, don't
        # under-report it as a clean pass.
        v = review.compute_verdict(0, self._trail(h=1))
        self.assertEqual((v["status"], v["gate"]), ("high", "fail"))

    def test_high(self):
        v = review.compute_verdict(4, self._trail(h=1))
        self.assertEqual((v["status"], v["gate"]), ("high", "fail"))

    def test_reviewer_failed(self):
        self.assertEqual(review.compute_verdict(1, self._trail())["gate"], "incomplete")

    def test_secret_block(self):
        self.assertEqual(review.compute_verdict(2, self._trail())["gate"], "blocked")

    def test_no_diff(self):
        self.assertEqual(review.compute_verdict(3, self._trail())["gate"], "skipped")


class CmdReview(unittest.TestCase):
    """Orchestration — with the environment stubbed so no reviewer CLI runs."""

    def setUp(self):
        self.proj = tempfile.mkdtemp()
        self.runs = os.path.join(self.proj, "runs")
        os.makedirs(self.runs)
        self._saved = (review.PROJECT_DIR, review.RUNS, review.CURRENT,
                       review.which_ensemble, review.run_ensemble,
                       review.resolve_repo_root, review.load_config)
        review.PROJECT_DIR = self.proj
        review.RUNS = self.runs
        review.CURRENT = os.path.join(self.runs, ".current")
        review.resolve_repo_root = lambda *a, **k: self.proj  # pretend it's a repo

    def tearDown(self):
        (review.PROJECT_DIR, review.RUNS, review.CURRENT,
         review.which_ensemble, review.run_ensemble,
         review.resolve_repo_root, review.load_config) = self._saved

    def _summary(self, out_dir):
        return json.load(open(os.path.join(out_dir, "summary.json")))

    def test_disabled_skips(self):
        review.load_config = lambda *a, **k: {"enabled": False}
        review.which_ensemble = lambda: "/fake/ensemble-ai"  # present, but disabled
        code = review.cmd_review(_args())
        self.assertEqual(code, 0)
        out = os.path.join(self.runs)  # a standalone run was created under runs/
        run = [d for d in os.listdir(self.runs) if d.endswith("__review")][0]
        self.assertEqual(self._summary(os.path.join(self.runs, run, "review"))["status"], "skipped")

    def test_absent_ensemble_degrades(self):
        review.load_config = lambda *a, **k: {"enabled": True}
        review.which_ensemble = lambda: None  # NOT on PATH
        code = review.cmd_review(_args())
        self.assertEqual(code, 0)  # never fails the QA pass
        run = [d for d in os.listdir(self.runs) if d.endswith("__review")][0]
        s = self._summary(os.path.join(self.runs, run, "review"))
        self.assertEqual(s["status"], "skipped")
        self.assertEqual(s["reason"], "ensemble-ai-not-found")

    def test_not_a_repo_degrades(self):
        review.load_config = lambda *a, **k: {"enabled": True}
        review.which_ensemble = lambda: "/fake/ensemble-ai"
        review.resolve_repo_root = lambda *a, **k: None
        self.assertEqual(review.cmd_review(_args()), 0)

    def _run_with_trail(self, exit_code, severities_by_reviewer, **args_over):
        review.load_config = lambda *a, **k: {"enabled": True}
        review.which_ensemble = lambda: "/fake/ensemble-ai"

        def fake_run(argv, timeout):
            # Mirror the REAL ensemble-ai layout: per-reviewer files land in the
            # `<out>/<run_id>/` subdir, not `<out>/` directly.
            out = argv[argv.index("--out") + 1]
            run_id = argv[argv.index("--run-id") + 1]
            sub = review.trail_subdir(out, run_id)
            os.makedirs(sub, exist_ok=True)
            for rid, (vendor, sevs, state) in severities_by_reviewer.items():
                with open(os.path.join(sub, f"review.{rid}.json"), "w") as fh:
                    json.dump(_stored(rid, vendor, sevs, state), fh)
            return exit_code

        review.run_ensemble = fake_run
        return review.cmd_review(_args(**args_over))

    def test_full_run_captures_findings(self):
        run = os.path.join(self.runs, "manual-run")
        os.makedirs(run)
        code = self._run_with_trail(
            4, {"codex": ("openai", ["high"], "reviewed"), "grok": ("xai", ["medium"], "reviewed")},
            run=run,
        )
        self.assertEqual(code, 0)  # report-only default → HIGH does not fail the pass
        s = self._summary(os.path.join(run, "review"))
        self.assertEqual(s["status"], "high")
        self.assertEqual(s["gate"], "fail")
        self.assertEqual(s["ensembleExitCode"], 4)
        self.assertEqual(s["counts"], {"high": 1, "medium": 1, "low": 0})
        # the smart trail: a findings.md pointer beside the behavior findings
        findings = open(os.path.join(run, "findings.md")).read()
        self.assertIn("[review]", findings)
        self.assertIn("gate: fail", findings)

    def test_fail_on_high_opt_in_fails(self):
        run = os.path.join(self.runs, "gated-run")
        os.makedirs(run)
        code = self._run_with_trail(
            4, {"codex": ("openai", ["high"], "reviewed")}, run=run, fail_on_high=True,
        )
        self.assertEqual(code, 1)  # opt-in hard gate → HIGH fails the step

    def test_clean_run_passes(self):
        run = os.path.join(self.runs, "clean-run")
        os.makedirs(run)
        code = self._run_with_trail(
            0, {"codex": ("openai", [], "reviewed")}, run=run, fail_on_high=True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._summary(os.path.join(run, "review"))["gate"], "pass")

    def test_trail_read_from_runid_subdir_not_shallow(self):
        # Regression for the load-bearing bug: ensemble-ai writes into
        # <out>/<run_id>/, so review must read that subdir. A stray file at the
        # SHALLOW <out>/ (the layout the pre-fix code wrongly globbed) is ignored.
        run = os.path.join(self.runs, "subdir-run")
        os.makedirs(run)
        review.load_config = lambda *a, **k: {"enabled": True}
        review.which_ensemble = lambda: "/fake/ensemble-ai"

        def fake_run(argv, timeout):
            out = argv[argv.index("--out") + 1]
            run_id = argv[argv.index("--run-id") + 1]
            sub = review.trail_subdir(out, run_id)
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, "review.codex.json"), "w") as fh:
                json.dump(_stored("codex", "openai", ["high"]), fh)     # the REAL trail
            with open(os.path.join(out, "review.stray.json"), "w") as fh:
                json.dump(_stored("stray", "x", ["high", "high"]), fh)  # shallow decoy
            return 4

        review.run_ensemble = fake_run
        review.cmd_review(_args(run=run))
        s = self._summary(os.path.join(run, "review"))
        self.assertEqual(s["counts"], {"high": 1, "medium": 0, "low": 0})  # subdir only
        self.assertEqual([r["id"] for r in s["reviewers"]], ["codex"])


if __name__ == "__main__":
    unittest.main()
