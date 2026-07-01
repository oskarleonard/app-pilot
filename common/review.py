#!/usr/bin/env python3
"""app-pilot review — the pre-PR cross-vendor CODE-review trigger. [DEV TOOL]

The QA pass proves an app *behaves* (app-pilot drives it, Claude judges the
screenshots). This adds the second axis: it proves the *diff* is sound, by
shelling out to the standalone **`ensemble-ai`** CLI (the portable cross-vendor
review engine — Codex/Grok read the diff read-only and surface typed findings).
Run it in the QA pass with review-on and the PR is **born reviewed**: behavior
verdict + code findings land in ONE run trail, so the dashboard just *surfaces*
already-reviewed work instead of firing a review after the PR exists.

app-pilot only *triggers + records* — it never reimplements review logic. It
shells out (Python subprocess, exactly how it already drives playwright/idb),
reads `ensemble-ai`'s typed trail, computes its OWN host gate (facts→policy),
and writes the result beside the screenshots at `runs/<run>/review/`.

Per-repo config — an opt-in `REVIEW` dict in the project's `target.py`
(the project's existing pinned-config surface; read by AST so importing a
mobile target.py never triggers sim resolution):

    REVIEW = {
        "enabled": True,            # opt-in; absent/False → review is skipped
        "reviewers": ["codex", "grok"],  # or omit → every configured reviewer
        "base": "origin/main",      # optional base ref override
        "sandbox": None,            # optional ensemble-ai sandbox profile
        "allow_sensitive": False,   # let a diff with sensitive paths through
        "fail_on_high": False,      # v1 report-only; True → a HIGH fails this step
    }

Design notes (forks picked + documented, per the Phase-3 spec):
  • Config home = target.py's REVIEW dict — matches the spec's "target.py-style"
    and needs no new file convention. "Which accounts" is out of scope for v1:
    the codex/grok CLIs own their own auth; ensemble-ai's later work-scoped subs
    handle account separation, not app-pilot.
  • Gate hardness = REPORT-ONLY by default (rule 6 — new loops start report-only).
    The two-axis hard gate is opt-in via `fail_on_high`. ensemble-ai computes the
    HIGH signal (its exit 4); app-pilot's host policy decides whether to block.
  • Graceful degradation — if `ensemble-ai` is not on PATH (or review is disabled,
    or there's no diff), the step SKIPS with a clear note and exits 0. An absent
    optional reviewer NEVER fails the behavior QA pass.

Subcommand:
  review [--run DIR] [--out DIR] [--base REF] [--reviewers a,b] [--pr N|url]
         [--working-tree|--staged] [--sandbox P] [--allow-sensitive]
         [--fail-on-high|--no-fail-on-high] [--force] [--timeout SECS]
"""
import argparse
import ast
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE)
RUNS = os.path.join(PROJECT_DIR, "runs")
CURRENT = os.path.join(RUNS, ".current")

ENSEMBLE_BIN = "ensemble-ai"
DEFAULT_TIMEOUT = 900  # reviewers fan out to real model CLIs — minutes, not seconds
INSTALL_HINT = "npm i -g github:oskarleonard/ensemble-ai"

# ensemble-ai review exit codes (its documented contract — facts, not our gate):
#   0 completed, no HIGH · 1 a reviewer failed · 2 blocked by the secret-scan
#   3 usage / no diff     · 4 completed WITH a HIGH finding (its built-in gate)
EXIT_MEANING = {
    0: ("clean", "pass", "review completed — no HIGH finding"),
    1: ("reviewer-failed", "incomplete", "a reviewer crashed / timed out / did not parse"),
    2: ("blocked", "blocked", "blocked by the diff secret-scan (sensitive path in the diff)"),
    3: ("no-diff", "skipped", "nothing to review (empty diff) or a usage error"),
    4: ("high", "fail", "review completed WITH a HIGH finding"),
}

# The severity tiers ensemble-ai emits, ordered high→low. Single-sourced so the
# per-reviewer tally, the totals, and the one-line summary never drift apart.
SEVERITIES = ("high", "medium", "low")


# ── per-repo config (AST-read, never import — a mobile target.py resolves a sim
#    on import and would sys.exit without one) ──────────────────────────────────
def load_config(project_dir=PROJECT_DIR):
    """Read the optional REVIEW dict literal from the project's target.py without
    executing it. Any parse problem degrades to {} (review then defaults to off)."""
    path = os.path.join(project_dir, "target.py")
    try:
        with open(path) as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        # Match both `REVIEW = {...}` (Assign) and an annotated
        # `REVIEW: dict = {...}` (AnnAssign) — a typed target.py uses the latter.
        if isinstance(node, ast.Assign):
            names, value = [t for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target], node.value  # value is None for a bare annotation
        else:
            continue
        if value is not None and any(n.id == "REVIEW" for n in names):
            try:
                literal = ast.literal_eval(value)
                return literal if isinstance(literal, dict) else {}
            except (ValueError, SyntaxError):
                return {}
    return {}


# ── environment ───────────────────────────────────────────────────────────────
def resolve_repo_root(start=PROJECT_DIR):
    """The git repo whose branch diff we review (the project's, not app-pilot's).
    None when `start` isn't inside a git work tree."""
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    root = out.stdout.strip()
    return root if out.returncode == 0 and root else None


def which_ensemble():
    return shutil.which(ENSEMBLE_BIN)


# ── argv assembly (config < CLI overrides) ──────────────────────────────────────
def build_argv(ensemble, out, repo_root, cfg, args, run_id):
    """The `ensemble-ai review` argv. We do NOT pass --no-fail-on-high: we WANT
    ensemble's exit 4 (HIGH present) as the gate signal, then apply our own host
    policy (fail_on_high) on top. `run_id` is ALWAYS passed: ensemble writes its
    per-reviewer trail into `<out>/<run_id>/`, so we must know it to read back
    the exact subdir (see trail_subdir)."""
    argv = [ensemble, "review", "--out", out, "--cwd", repo_root, "--run-id", run_id]

    base = args.base or cfg.get("base")
    if base:
        argv += ["--base", base]

    reviewers = args.reviewers or cfg.get("reviewers")
    if reviewers:
        ids = reviewers if isinstance(reviewers, str) else ",".join(reviewers)
        argv += ["--reviewers", ids]

    # Diff-source overrides (mutually exclusive — argparse guards it).
    if args.pr:
        argv += ["--pr", args.pr]
    elif args.working_tree:
        argv += ["--working-tree"]
    elif args.staged:
        argv += ["--staged"]

    sandbox = args.sandbox or cfg.get("sandbox")
    if sandbox:
        argv += ["--sandbox", sandbox]

    if args.allow_sensitive or cfg.get("allow_sensitive"):
        argv += ["--allow-sensitive"]
    return argv


# ── trail parsing (ensemble-ai's typed per-reviewer StoredReview files) ─────────
def _load_stored(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def trail_subdir(out_dir, run_id):
    """ensemble-ai persists each reviewer's `review.<id>.json` into
    `<out>/<sanitized run_id>/` (its reviewDir), NOT `<out>/` directly. Mirror its
    sanitize (cli.js sanitizePathSegment: non-[A-Za-z0-9._-] → '_', empty →
    'unknown') so we read back the exact subdir it wrote — and, because run_id is
    fresh per invocation, only THIS run's files (never a prior run's leftovers)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_id) or "unknown"
    return os.path.join(out_dir, safe)


def clear_trail(trail_dir):
    """Remove any prior per-reviewer trail files from the target subdir before a
    run, so a caller-supplied (reused) run_id can't carry a previous run's
    evidence — or a since-dropped reviewer's stale file — into this tally. Only
    touches the files we parse; leaves the dir and anything else untouched."""
    stale = glob.glob(os.path.join(trail_dir, "review.*.json"))
    stale.append(os.path.join(trail_dir, "review.json"))
    for f in stale:
        try:
            os.remove(f)
        except OSError:
            pass


def parse_trail(out_dir):
    """Read ensemble-ai's per-reviewer `review.<id>.json` (StoredReview) files
    from the trail dir into a compact record: per-reviewer tally + total counts.
    Reuses ensemble-ai's typed format verbatim — one review shape, no drift."""
    reviewers = []
    counts = {s: 0 for s in SEVERITIES}
    files = sorted(glob.glob(os.path.join(out_dir, "review.*.json")))
    # A pre-fan-out ensemble wrote a single bare `review.json` (always codex);
    # include it as a fallback. Fan-out files sort first, so the dedup-by-reviewer
    # below prefers a real `review.<id>.json` and skips a stray legacy copy of the
    # same reviewer — no double count.
    legacy = os.path.join(out_dir, "review.json")
    if os.path.exists(legacy):
        files.append(legacy)
    seen = set()
    for f in files:
        stored = _load_stored(f)
        if not isinstance(stored, dict):
            continue
        # `reviewer` may be present-but-null in a partial trail (a reviewer that
        # died before vendor/model resolved) — `or {}` guards the .get chain.
        reviewer = stored.get("reviewer") or {}
        rid = stored.get("reviewerId") or reviewer.get("vendor") or "?"
        if rid in seen:
            continue  # same reviewer already tallied (legacy copy beside a fan-out file)
        seen.add(rid)
        state = stored.get("terminalState", "?")
        findings = stored.get("findings") or []
        per = {s: 0 for s in SEVERITIES}
        for fnd in findings:
            sev = (fnd or {}).get("severity")
            if sev in per:
                per[sev] += 1
                counts[sev] += 1
        reviewers.append({
            "id": rid,
            "vendor": reviewer.get("vendor"),
            "model": reviewer.get("model"),
            "terminalState": state,
            "counts": per,
            "summary": (stored.get("summary") or "").strip()[:200],
        })
    return {"reviewers": reviewers, "counts": counts}


def _tally(r):
    if r["terminalState"] != "reviewed":
        return f"{r['id']} {r['terminalState']}"
    c = r["counts"]
    parts = [f"{c[s]}{s[0].upper()}" for s in SEVERITIES if c[s]]
    return f"{r['id']} {'/'.join(parts) if parts else 'clean'}"


def one_line(trail):
    return " · ".join(_tally(r) for r in trail["reviewers"]) or "no reviewer output"


# ── verdict (facts → host policy) ───────────────────────────────────────────────
def compute_verdict(exit_code, trail):
    status, gate, note = EXIT_MEANING.get(
        exit_code, ("error", "error", f"ensemble-ai exited {exit_code}")
    )
    c = trail["counts"]
    # Trust the trail over a clean exit: if ensemble exits 0 yet a HIGH sits in
    # the trail (contract drift / partial write), don't under-report it as pass.
    if exit_code == 0 and c["high"]:
        status, gate, note = "high", "fail", "trail carries a HIGH finding despite a clean exit"
    # exit 0 with only MED/LOW findings is still "findings", not bare "clean".
    elif exit_code == 0 and (c["medium"] or c["low"]):
        status = "findings"
    return {"status": status, "gate": gate, "note": note}


# ── run-dir resolution (nest beside the screenshots; standalone if no run) ───────
def resolve_run_dir(run_arg):
    if run_arg:
        os.makedirs(run_arg, exist_ok=True)
        return run_arg
    if os.path.exists(CURRENT):
        with open(CURRENT) as fh:
            run = fh.read().strip()
        if os.path.isdir(run):
            return run
    # No current run — create a standalone one so a born-reviewed pre-PR check
    # works without a full QA session first.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")  # %f: no same-second collision
    run = os.path.join(RUNS, f"{stamp}__review")
    os.makedirs(run, exist_ok=True)
    return run


def _append_finding(run_dir, line):
    fp = os.path.join(run_dir, "findings.md")
    try:
        with open(fp, "a") as fh:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            fh.write(f"{ts}  {line}\n")
    except OSError:
        pass


def _write_summary(out_dir, summary):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)


# ── seams for tests (monkeypatched) ─────────────────────────────────────────────
def run_ensemble(argv, timeout):
    """Run ensemble-ai, streaming its own summary to the terminal so the agent
    sees the findings live. Returns the exit code (a timeout maps to 1 =
    reviewer-incomplete). Isolated so tests can stub the subprocess."""
    try:
        return subprocess.run(argv, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"app-pilot review: ensemble-ai timed out after {timeout}s", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"app-pilot review: could not run ensemble-ai: {e}", file=sys.stderr)
        return 1


def _skip(run_dir, out_dir, reason, detail):
    """Record a skipped review and exit 0 — an absent/disabled reviewer never
    fails the behavior QA pass."""
    _write_summary(out_dir, {
        "tool": "app-pilot review",
        "status": "skipped",
        "gate": "skipped",
        "reason": reason,
        "detail": detail,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    _append_finding(run_dir, f"- [review] skipped — {detail}")
    print(f"app-pilot review: skipped — {detail}")
    print(f"  trail: {out_dir}")
    return 0


def cmd_review(args):
    cfg = load_config()
    run_dir = resolve_run_dir(args.run)
    out_dir = args.out or os.path.join(run_dir, "review")

    enabled = bool(cfg.get("enabled")) or args.force
    if not enabled:
        return _skip(run_dir, out_dir, "disabled",
                     "review is off (set REVIEW={'enabled': True} in target.py, or pass --force)")

    repo_root = resolve_repo_root()
    if not repo_root:
        return _skip(run_dir, out_dir, "not-a-repo",
                     f"{PROJECT_DIR} is not inside a git work tree — nothing to review")

    ensemble = which_ensemble()
    if not ensemble:
        return _skip(run_dir, out_dir, "ensemble-ai-not-found",
                     f"`{ENSEMBLE_BIN}` not on PATH — install it: {INSTALL_HINT}")

    # Own the run id: pass it to ensemble AND use it to read back the exact
    # `<out>/<run_id>/` subdir it writes into. A fresh id per run also means we
    # only ever tally THIS run's trail, never a reused dir's leftovers.
    run_id = args.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    trail_dir = trail_subdir(out_dir, run_id)
    clear_trail(trail_dir)  # a reused/caller-supplied run_id must not inherit stale files
    argv = build_argv(ensemble, out_dir, repo_root, cfg, args, run_id)
    print(f"app-pilot review: {' '.join(argv)}", file=sys.stderr)
    exit_code = run_ensemble(argv, args.timeout)

    trail = parse_trail(trail_dir)
    verdict = compute_verdict(exit_code, trail)
    tally = one_line(trail)

    summary = {
        "tool": "app-pilot review",
        "status": verdict["status"],
        "gate": verdict["gate"],
        "note": verdict["note"],
        "ensembleExitCode": exit_code,
        "repoRoot": repo_root,
        "base": args.base or cfg.get("base"),
        "counts": trail["counts"],
        "reviewers": trail["reviewers"],
        "tally": tally,
        "trailDir": out_dir,
        "runId": run_id,  # per-reviewer files live in <trailDir>/<runId>/
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _write_summary(out_dir, summary)
    _append_finding(run_dir, f"- [review] {tally} — gate: {verdict['gate']} ({verdict['note']}) → trail: review/")

    print(f"\napp-pilot review — {verdict['status']} (gate: {verdict['gate']})")
    print(f"  {verdict['note']}")
    print(f"  {tally}")
    print(f"  trail: {out_dir}")

    # Host gate policy: report-only by default (rule 6). Only an OPTED-IN
    # fail_on_high on a real HIGH (ensemble exit 4) fails this step.
    fail_on_high = args.fail_on_high
    if fail_on_high is None:
        fail_on_high = bool(cfg.get("fail_on_high"))
    # Fail on a HIGH by EITHER signal: ensemble's exit 4, OR a HIGH parsed from the
    # trail on a clean exit (the contract-drift case compute_verdict already gates).
    if fail_on_high and (exit_code == 4 or trail["counts"]["high"]):
        print("  → FAILING the QA pass: a HIGH finding is present (fail_on_high).", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="app-pilot review", description=__doc__)
    p.add_argument("--run", default=None, help="target run dir (default: .current, else a fresh run)")
    p.add_argument("--out", default=None, help="trail output dir (default: <run>/review)")
    p.add_argument("--base", default=None, help="base ref override (e.g. origin/main)")
    p.add_argument("--reviewers", default=None, help="comma-separated reviewer ids override")
    p.add_argument("--run-id", default=None, help="ensemble-ai run/receipt id (default: generated)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--pr", default=None, help="review a GitHub PR diff (N or URL)")
    src.add_argument("--working-tree", action="store_true", help="review uncommitted tracked changes")
    src.add_argument("--staged", action="store_true", help="review staged changes")
    p.add_argument("--sandbox", default=None, help="ensemble-ai sandbox profile override")
    p.add_argument("--allow-sensitive", action="store_true", help="review even if the diff carries sensitive paths")
    gate = p.add_mutually_exclusive_group()
    gate.add_argument("--fail-on-high", dest="fail_on_high", action="store_true", default=None,
                      help="fail this step (exit 1) when a HIGH finding is present")
    gate.add_argument("--no-fail-on-high", dest="fail_on_high", action="store_false",
                      help="report-only even on a HIGH (override config)")
    p.add_argument("--force", action="store_true", help="run even if REVIEW.enabled is not set")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"reviewer timeout secs (default {DEFAULT_TIMEOUT})")
    args = p.parse_args(argv)
    sys.exit(cmd_review(args))


if __name__ == "__main__":
    main()
