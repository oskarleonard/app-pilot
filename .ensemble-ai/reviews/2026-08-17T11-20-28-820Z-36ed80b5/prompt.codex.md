You are an adversarial code reviewer from a DIFFERENT vendor than the author.
You have NO prior memory: your own memory, the repository, and every earlier
conversation are unknown to you EXCEPT what is embedded below. Review only
what is here; do not assume facts not present.

Repository: https://github.com/oskarleonard/app-pilot · reviewing the diff below

## Objective
_(why this review was fired)_

Adversarial cross-vendor review of a code diff — find correctness, security, and convention issues a same-vendor author might miss.

## The diff under review
_(the change itself — review THIS, not the whole repo)_

diff --git a/common/runlog.py b/common/runlog.py
new file mode 100644
index 0000000..ef41f76
--- /dev/null
+++ b/common/runlog.py
@@ -0,0 +1,161 @@
+"""Neutral per-run machine record: runs/<id>/run.json, written beside the
+mission's markdown artifacts.
+
+The markdown (journal.md, findings.md) stays the human artifact; run.json is
+the machine contract — any dashboard or tool can consume a run without parsing
+prose. It is deliberately engine-neutral: no consumer's schema leaks in here,
+and runs must keep recording with no dashboard on the machine.
+
+Lifecycle: `open_run()` at run-dir creation (stamps status "running"),
+`close_run()` as the run's last step. A run that dies without closing can be
+settled by consumers from the dir's mtime; a run that never OPENS is invisible
+— which is why missions must open first, not close-only.
+
+Schema (version 1):
+  { "schema": 1, "runId": "<dir basename>", "rig": "<project id>",
+    "scope": "...", "goal": "...", "target": "...?", "env": "...?",
+    "startedAt": iso8601, "endedAt": iso8601?,
+    "status": "running" | "done" | "failed" | "abandoned",
+    "verdict": "pass" | "fail" | "mixed"?, "costUsd": number?,
+    "findings": [{ "id", "severity", "title", "ticket"? }]? }
+
+CLI (for markdown missions — no inline python needed):
+  python3 common/runlog.py open  <run_dir> --rig <id> --scope <s> --goal <g>
+                                 [--target <t>] [--env <e>]
+  python3 common/runlog.py close <run_dir> --status done|failed|abandoned
+                                 [--verdict pass|fail|mixed]
+                                 [--findings <path.json>] [--cost-usd <n>]
+"""
+import argparse
+import json
+import os
+import sys
+import time
+
+SCHEMA = 1
+CLOSE_STATUSES = ("done", "failed", "abandoned")
+STATUSES = ("running", *CLOSE_STATUSES)
+VERDICTS = ("pass", "fail", "mixed")
+
+RUN_JSON = "run.json"
+
+
+def _now_iso():
+    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
+
+
+def _path(run_dir):
+    return os.path.join(run_dir, RUN_JSON)
+
+
+def _write_atomic(run_dir, record):
+    """tmp + rename so a reader never sees a half-written record."""
+    tmp = _path(run_dir) + ".tmp"
+    with open(tmp, "w") as fh:
+        json.dump(record, fh, indent=2, sort_keys=True)
+        fh.write("\n")
+    os.replace(tmp, _path(run_dir))
+
+
+def read_run(run_dir):
+    """The current record, or None (absent or unreadable — caller decides)."""
+    try:
+        with open(_path(run_dir)) as fh:
+            return json.load(fh)
+    except (OSError, ValueError):
+        return None
+
+
+def open_run(run_dir, rig, scope, goal, target=None, env=None):
+    """Stamp run.json at run-dir creation. Idempotent: an existing readable
+    record wins (a re-run of the open step must not clobber startedAt)."""
+    existing = read_run(run_dir)
+    if existing is not None:
+        return existing
+    record = {
+        "schema": SCHEMA,
+        "runId": os.path.basename(os.path.normpath(run_dir)),
+        "rig": rig,
+        "scope": scope,
+        "goal": goal,
+        "startedAt": _now_iso(),
+        "status": "running",
+    }
+    if target:
+        record["target"] = target
+    if env:
+        record["env"] = env
+    _write_atomic(run_dir, record)
+    return record
+
+
+def close_run(run_dir, status, verdict=None, findings=None, cost_usd=None):
+    """Settle the record. Tolerant of a corrupt/missing open record: closing
+    must never kill a finished run's last step — record what we know."""
+    if status not in CLOSE_STATUSES:
+        raise ValueError("close status must be one of done|failed|abandoned")
+    if verdict is not None and verdict not in VERDICTS:
+        raise ValueError("verdict must be one of pass|fail|mixed")
+    record = read_run(run_dir)
+    if record is None:
+        if os.path.exists(_path(run_dir)):
+            print("runlog: existing run.json unreadable — rewriting from close", file=sys.stderr)
+        record = {
+            "schema": SCHEMA,
+            "runId": os.path.basename(os.path.normpath(run_dir)),
+            "startedAt": _now_iso(),
+        }
+    record["status"] = status
+    record["endedAt"] = _now_iso()
+    if verdict is not None:
+        record["verdict"] = verdict
+    if findings is not None:
+        record["findings"] = findings
+    if cost_usd is not None:
+        record["costUsd"] = cost_usd
+    _write_atomic(run_dir, record)
+    return record
+
+
+def load_findings(path):
+    with open(path) as fh:
+        loaded = json.load(fh)
+    if not isinstance(loaded, list):
+        raise ValueError("--findings file must hold a JSON array")
+    return loaded
+
+
+def main(argv=None):
+    parser = argparse.ArgumentParser(description="neutral run.json lifecycle")
+    sub = parser.add_subparsers(dest="cmd", required=True)
+
+    p_open = sub.add_parser("open", help="stamp run.json at run-dir creation")
+    p_open.add_argument("run_dir")
+    p_open.add_argument("--rig", required=True)
+    p_open.add_argument("--scope", required=True)
+    p_open.add_argument("--goal", required=True)
+    p_open.add_argument("--target")
+    p_open.add_argument("--env")
+
+    p_close = sub.add_parser("close", help="settle run.json as the run's last step")
+    p_close.add_argument("run_dir")
+    p_close.add_argument("--status", required=True, choices=list(CLOSE_STATUSES))
+    p_close.add_argument("--verdict", choices=list(VERDICTS))
+    p_close.add_argument("--findings", help="path to a JSON array of findings")
+    p_close.add_argument("--cost-usd", type=float, dest="cost_usd")
+
+    args = parser.parse_args(argv)
+    if not os.path.isdir(args.run_dir):
+        parser.error(f"not a run dir: {args.run_dir}")
+
+    if args.cmd == "open":
+        record = open_run(args.run_dir, args.rig, args.scope, args.goal, args.target, args.env)
+    else:
+        findings = load_findings(args.findings) if args.findings else None
+        record = close_run(args.run_dir, args.status, args.verdict, findings, args.cost_usd)
+    json.dump(record, sys.stdout, indent=2, sort_keys=True)
+    print()
+
+
+if __name__ == "__main__":
+    main()
diff --git a/common/test_runlog.py b/common/test_runlog.py
new file mode 100644
index 0000000..1948182
--- /dev/null
+++ b/common/test_runlog.py
@@ -0,0 +1,131 @@
+"""Tests for runlog — the neutral run.json lifecycle.
+
+Run:  python3 common/test_runlog.py     (or `python3 -m pytest -q`)
+"""
+import json
+import os
+import shutil
+import subprocess
+import sys
+import tempfile
+import unittest
+
+sys.path.insert(0, os.path.dirname(__file__))
+import runlog  # noqa: E402
+
+
+class RunlogLifecycle(unittest.TestCase):
+    def setUp(self):
+        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-x")
+        self.addCleanup(shutil.rmtree, self.run_dir, True)
+
+    def read(self):
+        with open(os.path.join(self.run_dir, "run.json")) as fh:
+            return json.load(fh)
+
+    def test_open_stamps_running_record(self):
+        record = runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x", target="repo#7", env="staging")
+        on_disk = self.read()
+        self.assertEqual(record, on_disk)
+        self.assertEqual(on_disk["schema"], runlog.SCHEMA)
+        self.assertEqual(on_disk["status"], "running")
+        self.assertEqual(on_disk["runId"], os.path.basename(self.run_dir))
+        self.assertEqual(on_disk["target"], "repo#7")
+        self.assertTrue(on_disk["startedAt"].endswith("Z"))
+        self.assertNotIn("endedAt", on_disk)
+
+    def test_open_omits_absent_optionals(self):
+        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
+        on_disk = self.read()
+        self.assertNotIn("target", on_disk)
+        self.assertNotIn("env", on_disk)
+
+    def test_open_is_idempotent(self):
+        first = runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
+        second = runlog.open_run(self.run_dir, "rig-b", "other", "different")
+        self.assertEqual(first, second)
+        self.assertEqual(self.read()["rig"], "rig-a")
+
+    def test_close_merges_onto_open(self):
+        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
+        findings = [{"id": "f1", "severity": "high", "title": "boom", "ticket": "TRI-1"}]
+        runlog.close_run(self.run_dir, "done", verdict="mixed", findings=findings, cost_usd=1.25)
+        on_disk = self.read()
+        self.assertEqual(on_disk["status"], "done")
+        self.assertEqual(on_disk["verdict"], "mixed")
+        self.assertEqual(on_disk["findings"], findings)
+        self.assertEqual(on_disk["costUsd"], 1.25)
+        self.assertEqual(on_disk["rig"], "rig-a")  # open fields survive
+        self.assertIn("endedAt", on_disk)
+
+    def test_close_rejects_bad_vocabulary(self):
+        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
+        with self.assertRaises(ValueError):
+            runlog.close_run(self.run_dir, "running")
+        with self.assertRaises(ValueError):
+            runlog.close_run(self.run_dir, "done", verdict="meh")
+
+    def test_close_survives_corrupt_open_record(self):
+        with open(os.path.join(self.run_dir, "run.json"), "w") as fh:
+            fh.write("{ not json")
+        record = runlog.close_run(self.run_dir, "failed")
+        self.assertEqual(record["status"], "failed")
+        self.assertEqual(self.read()["runId"], os.path.basename(self.run_dir))
+
+    def test_close_without_open_records_what_it_knows(self):
+        record = runlog.close_run(self.run_dir, "abandoned")
+        self.assertEqual(record["status"], "abandoned")
+        self.assertIn("startedAt", record)
+
+    def test_no_tmp_residue(self):
+        runlog.open_run(self.run_dir, "rig-a", "workspace", "probe-x")
+        runlog.close_run(self.run_dir, "done")
+        self.assertEqual(sorted(os.listdir(self.run_dir)), ["run.json"])
+
+
+class RunlogCli(unittest.TestCase):
+    def setUp(self):
+        self.run_dir = tempfile.mkdtemp(prefix="20260817-101112__scope__goal-cli")
+        self.addCleanup(shutil.rmtree, self.run_dir, True)
+        self.script = os.path.join(os.path.dirname(__file__), "runlog.py")
+
+    def cli(self, *args):
+        return subprocess.run(
+            [sys.executable, self.script, *args], capture_output=True, text=True
+        )
+
+    def test_open_then_close_roundtrip(self):
+        opened = self.cli("open", self.run_dir, "--rig", "rig-a", "--scope", "s", "--goal", "g")
+        self.assertEqual(opened.returncode, 0, opened.stderr)
+        self.assertEqual(json.loads(opened.stdout)["status"], "running")
+
+        findings_path = os.path.join(self.run_dir, "..", "findings-tmp.json")
+        with open(findings_path, "w") as fh:
+            json.dump([{"id": "f1", "severity": "low", "title": "t"}], fh)
+        self.addCleanup(os.remove, findings_path)
+
+        closed = self.cli(
+            "close", self.run_dir, "--status", "done", "--verdict", "pass",
+            "--findings", findings_path, "--cost-usd", "0.5",
+        )
+        self.assertEqual(closed.returncode, 0, closed.stderr)
+        record = json.loads(closed.stdout)
+        self.assertEqual(record["verdict"], "pass")
+        self.assertEqual(len(record["findings"]), 1)
+
+    def test_missing_run_dir_errors(self):
+        gone = self.cli("open", "/nonexistent/run/dir", "--rig", "r", "--scope", "s", "--goal", "g")
+        self.assertNotEqual(gone.returncode, 0)
+
+    def test_non_array_findings_file_errors(self):
+        self.cli("open", self.run_dir, "--rig", "r", "--scope", "s", "--goal", "g")
+        findings_path = os.path.join(self.run_dir, "..", "findings-bad.json")
+        with open(findings_path, "w") as fh:
+            json.dump({"not": "an array"}, fh)
+        self.addCleanup(os.remove, findings_path)
+        bad = self.cli("close", self.run_dir, "--status", "done", "--findings", findings_path)
+        self.assertNotEqual(bad.returncode, 0)
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/missions/_format.md b/missions/_format.md
index b088994..8cee107 100644
--- a/missions/_format.md
+++ b/missions/_format.md
@@ -48,6 +48,15 @@ steps), **Driver: wake / Driver: goal** (pacing specifics), **Watchdog**.
   apply high-confidence findings, re-verify + static checks, THEN open the
   PR (one gate pass, no looping). bug-hunt §4 is the reference wording —
   copy it into any new mission that commits code.
+- **Machine record — non-negotiable.** `app-pilot init` stamps a neutral
+  `runs/<id>/run.json` (schema in `common/runlog.py`) at run-dir creation, and
+  every mission's finish steps MUST settle it:
+  `app-pilot close --status done|failed --verdict pass|fail|mixed`
+  (`--findings <json>` optional) as the run's LAST action. The markdown stays
+  the human artifact; run.json is what dashboards and tools consume. A run
+  that dies unclosed can be settled by consumers from the dir's mtime — a run
+  that never opened is invisible, which is why the open lives in `init`, not
+  in mission prose.
 
 ## Current missions
 
diff --git a/missions/bug-hunt.md b/missions/bug-hunt.md
index 1aa3a8b..6c9b206 100644
--- a/missions/bug-hunt.md
+++ b/missions/bug-hunt.md
@@ -184,5 +184,8 @@ on a timer EVEN IF an iteration crashed — that is the point. In this mode:
   base per the **product PR convention** (`product/RUNBOOK.md` — e.g. some
   repos want title-only bodies + self-assign). ELSE leave the branch local
   and report its name.
+- Settle the machine record LAST: `app-pilot close --status done --verdict
+  <pass|fail|mixed>` (`--findings <json>` when a findings JSON exists; a run
+  aborted midway closes `--status failed`). Nothing runs after close.
 - (wake) do NOT schedule again · (--driven) cancel the pacemaker · report
   and stop.
diff --git a/missions/feature-dev.md b/missions/feature-dev.md
index 6f664fb..d4776fa 100644
--- a/missions/feature-dev.md
+++ b/missions/feature-dev.md
@@ -142,6 +142,9 @@ STEP6 update the journal (Done / Remaining / Next).
   the **product PR convention** (`product/RUNBOOK.md`). The PR body carries the
   criteria→evidence table so a reviewer sees, per criterion, the live proof.
   ELSE leave the branch local and report its name + the blockers.
+- Settle the machine record LAST: `app-pilot close --status done --verdict
+  <pass|fail|mixed>` (a build aborted midway closes `--status failed`).
+  Nothing runs after close.
 - (wake) do NOT schedule again · (--driven) cancel the pacemaker · report and
   stop. Recommend a fresh non-author verifier as the next step.
 
diff --git a/missions/improvement.md b/missions/improvement.md
index 177c6ca..4ea489f 100644
--- a/missions/improvement.md
+++ b/missions/improvement.md
@@ -110,7 +110,9 @@ On top of them:
    one pass, no loop (skills absent → note it, proceed). IF DONE commits exist:
    push + open a PR into `base` per the **product PR convention**, body = the
    verdict table + the DEFERRED list; ELSE report the triage, no empty PR.
-   (wake) don't reschedule · (--driven) cancel the pacemaker · report + stop.
+   Settle the machine record LAST: `app-pilot close --status done --verdict
+   <pass|fail|mixed>`. (wake) don't reschedule · (--driven) cancel the
+   pacemaker · report + stop.
 
 ## Driver notes
 Same pacing machinery as bug-hunt/scenario-exec: **wake** = `ScheduleWakeup`
diff --git a/missions/scenario-exec.md b/missions/scenario-exec.md
index 623ef09..ce2d1ab 100644
--- a/missions/scenario-exec.md
+++ b/missions/scenario-exec.md
@@ -85,7 +85,9 @@ On top of them:
    screenshots in the adapter's `runs/<id>/` and reference them by filename.
 5. **Finish**: `app-pilot check` ground-truth sweep (if the adapter has one) —
    failures become log notes; append `## Summary` (the completion sentinel)
-   to BOTH the run log and `findings.md`; `app-pilot stop`; report totals.
+   to BOTH the run log and `findings.md`; `app-pilot stop`; settle the machine
+   record LAST — `app-pilot close --status done --verdict <pass|fail|mixed>`;
+   report totals.
 
 ## Driver notes
 Same pacing machinery as bug-hunt (wake = `ScheduleWakeup` ≈90 s with the
diff --git a/mobile/app-pilot b/mobile/app-pilot
index 138363e..0f65cd5 100755
--- a/mobile/app-pilot
+++ b/mobile/app-pilot
@@ -44,6 +44,8 @@ Run bookkeeping + eyes & hands:
   app-pilot scroll [down|up] [--amount 0.35]   scroll native lists (NOT RNGH gestures)
   app-pilot note <text>        append a finding to the current run
   app-pilot act <text>         append a line to actions.log
+  app-pilot close --status done|failed [--verdict pass|fail|mixed] [--findings J]
+                        settle the run's machine record (run.json) — the LAST step
   app-pilot find <label>       locate an element without tapping
   app-pilot companion [ensure] idb companion check / respawn
   app-pilot target [--udid|--port|--bundle|--mode|--window]   print pinned config values
@@ -86,7 +88,7 @@ case "$cmd" in
     exec python3 "$H/core/devserver.py" metrolog "${1:-40}" ;;
   crashes)
     exec python3 "$H/core/devserver.py" crashes "${1:-20}" ;;
-  init|shot|tree|tap|type|scroll|note|act)
+  init|shot|tree|tap|type|scroll|note|act|close)
     exec python3 "$H/core/qa.py" "$cmd" "$@" ;;
   publish)
     exec python3 "$COMMON/publish.py" "$@" ;;
diff --git a/mobile/core/qa.py b/mobile/core/qa.py
index 800d65a..f5a0caa 100644
--- a/mobile/core/qa.py
+++ b/mobile/core/qa.py
@@ -24,11 +24,14 @@ Subcommands (operate on the "current" run unless --run given):
   type  <text> [--label L] [--role R] [--clear] [--enter]   type into a (focused) field
   note  <text...>                append a finding to findings.md
   act   <text...>                append a line to actions.log
+  close --status done|failed|abandoned [--verdict pass|fail|mixed] [--findings J]
+                                 settle run.json (machine record; the LAST step)
 
 Tapping prefers idb (accessibility-label / tab-segment / fraction, via idb_ui).
 """
 import argparse
 import datetime
+import json
 import os
 import re
 import subprocess
@@ -43,6 +46,11 @@ import common  # noqa: E402
 import idb_ui  # noqa: E402
 import target  # noqa: E402
 
+# The shared engine's common/ (runlog) — appended, never prepended: mobile/core
+# has its own `common` module that must keep winning by that name.
+sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "common"))
+import runlog  # noqa: E402
+
 # Run output lives at scripts/app-pilot/runs/ (NOT core/runs/ — an earlier version
 # anchored to core/ by accident and grew two runs dirs).
 RUNS = os.path.join(os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE), "runs")
@@ -76,6 +84,13 @@ def _safe_part(value):
     return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "x"
 
 
+def _rig_id():
+    """The project this rig belongs to: the repo dir above scripts/app-pilot.
+    A neutral identity string — consumers key on it, nothing here does."""
+    adapter = os.path.dirname(RUNS)
+    return os.path.basename(os.path.abspath(os.path.join(adapter, "..", "..")))
+
+
 def cmd_init(args):
     stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
     # If a driver was given (wake|goal), auto-prefix the label so the resulting
@@ -106,6 +121,10 @@ def cmd_init(args):
         f"# Findings — {rid}\n\n_Format: `[severity] screen — observation (screenshot)`_\n\n"
     )
     open(os.path.join(run, "actions.log"), "w").write(f"# Actions — {rid}\n")
+    # Machine record beside the markdown: run.json opens here (harness-stamped
+    # — a mission can forget a step; init can't) and closes via `close`.
+    runlog.open_run(run, rig=_rig_id(), scope=scope, goal=label or scope,
+                    env=getattr(target, "MODE", None))
     open(CURRENT, "w").write(run)
     print(run)
 
@@ -245,6 +264,15 @@ def cmd_act(args):
     print("logged")
 
 
+def cmd_close(args):
+    run = _run_dir(args)
+    findings = runlog.load_findings(args.findings) if args.findings else None
+    record = runlog.close_run(run, args.status, args.verdict, findings, args.cost_usd)
+    _log(run, "actions.log", f"CLOSE status={args.status}"
+         + (f" verdict={args.verdict}" if args.verdict else ""))
+    print(json.dumps(record, indent=2, sort_keys=True))
+
+
 def main():
     p = argparse.ArgumentParser()
     sub = p.add_subparsers(dest="cmd", required=True)
@@ -301,6 +329,14 @@ def main():
     pa.add_argument("text", nargs="+")
     pa.add_argument("--run", default=None)
     pa.set_defaults(fn=cmd_act)
+    pc = sub.add_parser("close", help="settle run.json as the run's last step")
+    pc.add_argument("--status", required=True, choices=list(runlog.CLOSE_STATUSES))
+    pc.add_argument("--verdict", choices=list(runlog.VERDICTS), default=None)
+    pc.add_argument("--findings", default=None,
+                    help="path to a JSON array of findings ({id,severity,title,ticket?})")
+    pc.add_argument("--cost-usd", type=float, dest="cost_usd", default=None)
+    pc.add_argument("--run", default=None)
+    pc.set_defaults(fn=cmd_close)
     args = p.parse_args()
     args.fn(args)
 
diff --git a/web/app-pilot b/web/app-pilot
index eda4bc9..100b4ab 100755
--- a/web/app-pilot
+++ b/web/app-pilot
@@ -36,6 +36,8 @@ Run bookkeeping + archival evidence:
                            (fresh headless context)
   app-pilot note <text>        append a finding
   app-pilot act <text>         append to the audit log
+  app-pilot close --status done|failed [--verdict pass|fail|mixed] [--findings J]
+                        settle the run's machine record (run.json) — the LAST step
 
 PR evidence (hosts images OFF the PR branch — see RUNBOOK "PR evidence"):
   app-pilot publish <img> --feature S [--name F] [--caption C] [--width N]
@@ -75,7 +77,7 @@ case "$cmd" in
     exec python3 "$H/core/devserver.py" "$cmd" "$@" ;;
   logs)
     exec python3 "$H/core/devserver.py" logs "${1:-40}" ;;
-  init|shot|note|act)
+  init|shot|note|act|close)
     exec python3 "$H/core/qa.py" "$cmd" "$@" ;;
   publish)
     exec python3 "$COMMON/publish.py" "$@" ;;
diff --git a/web/core/qa.py b/web/core/qa.py
index bec2aef..085dca8 100644
--- a/web/core/qa.py
+++ b/web/core/qa.py
@@ -19,9 +19,12 @@ Subcommands (operate on the "current" run unless --run given):
   shot  <label> [path]           full-page screenshot of APP_URL+path (default /)
   note  <text...>                append a finding to findings.md
   act   <text...>                append a line to actions.log
+  close --status done|failed|abandoned [--verdict pass|fail|mixed] [--findings J]
+                                 settle run.json (machine record; the LAST step)
 """
 import argparse
 import datetime
+import json
 import os
 import re
 import subprocess
@@ -31,6 +34,11 @@ HERE = os.path.dirname(os.path.abspath(__file__))
 sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
 import target  # noqa: E402
 
+# The shared engine's common/ (runlog) — appended, never prepended, so it can
+# never shadow a project-dir module by the same name.
+sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "common"))
+import runlog  # noqa: E402
+
 RUNS = os.path.join(os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE), "runs")
 CURRENT = os.path.join(RUNS, ".current")
 
@@ -78,6 +86,13 @@ def _safe_part(value):
     return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "x"
 
 
+def _rig_id():
+    """The project this rig belongs to: the repo dir above scripts/app-pilot.
+    A neutral identity string — consumers key on it, nothing here does."""
+    adapter = os.path.dirname(RUNS)
+    return os.path.basename(os.path.abspath(os.path.join(adapter, "..", "..")))
+
+
 def cmd_init(args):
     stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
     scope = _safe_part(args.scope)
@@ -108,6 +123,10 @@ def cmd_init(args):
         )
     with open(os.path.join(run, "actions.log"), "w") as fh:
         fh.write(f"# Actions — {rid}\n")
+    # Machine record beside the markdown: run.json opens here (harness-stamped
+    # — a mission can forget a step; init can't) and closes via `close`.
+    runlog.open_run(run, rig=_rig_id(), scope=scope, goal=label or scope,
+                    env=getattr(target, "MODE", None))
     with open(CURRENT, "w") as fh:
         fh.write(run)
     print(run)
@@ -142,6 +161,15 @@ def cmd_act(args):
     print("logged")
 
 
+def cmd_close(args):
+    run = _run_dir(args)
+    findings = runlog.load_findings(args.findings) if args.findings else None
+    record = runlog.close_run(run, args.status, args.verdict, findings, args.cost_usd)
+    _log(run, "actions.log", f"CLOSE status={args.status}"
+         + (f" verdict={args.verdict}" if args.verdict else ""))
+    print(json.dumps(record, indent=2, sort_keys=True))
+
+
 def main():
     p = argparse.ArgumentParser()
     sub = p.add_subparsers(dest="cmd", required=True)
@@ -165,6 +193,14 @@ def main():
     pa.add_argument("text", nargs="+")
     pa.add_argument("--run", default=None)
     pa.set_defaults(fn=cmd_act)
+    pc = sub.add_parser("close", help="settle run.json as the run's last step")
+    pc.add_argument("--status", required=True, choices=list(runlog.CLOSE_STATUSES))
+    pc.add_argument("--verdict", choices=list(runlog.VERDICTS), default=None)
+    pc.add_argument("--findings", default=None,
+                    help="path to a JSON array of findings ({id,severity,title,ticket?})")
+    pc.add_argument("--cost-usd", type=float, dest="cost_usd", default=None)
+    pc.add_argument("--run", default=None)
+    pc.set_defaults(fn=cmd_close)
     args = p.parse_args()
     args.fn(args)
 


## Changed files (full content)
_(surrounding context for the diff hunks — UNAVAILABLE)_

(not available)

## Repo conventions (AGENTS.md)
_(house rules + known footguns the change must respect — UNAVAILABLE)_

(not available)

## Recent run history
_(what was fired against this repo lately — UNAVAILABLE)_

(not available)

## Your task
Find correctness bugs, security issues, broken conventions, and risky
choices IN THE DIFF. Be concrete and cite file + line. Do not nitpick style
the conventions already allow. Prefer a few high-signal findings over many
weak ones — false positives waste the arbiter’s time.

TWIN-SURFACE PARITY: when the diff adds a surface that MIRRORS an existing one
(alias routes, a twin API vocabulary, a parallel variant of an existing
endpoint/handler/command set), enumerate the mirrored surface’s operations and
behaviors as visible in the embedded context, diff the two, and flag any
operation, guard, error contract, or test the original has that the new surface
lacks WITHOUT a stated justification. An absence is a finding: cite where the
original defines what the twin is missing, and say what breaks or is blocked by
the gap. Diff-only review misses these by construction — the absence is not in
the diff, so look for it deliberately.

## Output format — STRICT
Respond with ONE fenced ```json block and NOTHING else, matching:
{
  "summary": "<one short paragraph: your overall read of the change>",
  "findings": [
    {
      "title": "<short title>",
      "body": "<the issue, why it matters, and the suggested fix>",
      "severity": "high" | "medium" | "low",
      "confidence": "high" | "medium" | "low",
      "evidence": { "file": "<a path from the diff>", "line": <number, or omit>, "detail": "<optional>" }
    }
  ]
}
Rules: cite a concrete file in every finding's "evidence" (an uncited finding is
discounted). "severity" = the impact IF the finding is real; "confidence" = how
sure you are it is real. If the change looks correct, return an empty "findings"
array with a "summary" that says so. Do not invent issues to fill the list. You
see one diff, not the project's tracker: never assert a change is out-of-scope or
unsanctioned — state the code-level consequence and, at most, note the commit
boundary.
