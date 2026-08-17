"""Neutral per-run machine record: runs/<id>/run.json, written beside the
mission's markdown artifacts.

The markdown (journal.md, findings.md) stays the human artifact; run.json is
the machine contract — any dashboard or tool can consume a run without parsing
prose. It is deliberately engine-neutral: no consumer's schema leaks in here,
and runs must keep recording with no dashboard on the machine.

Lifecycle: `open_run()` at run-dir creation (stamps status "running"),
`close_run()` as the run's last step. A run that dies without closing can be
settled by consumers from the dir's mtime; a run that never OPENS is invisible
— which is why missions must open first, not close-only.

Schema (version 1):
  { "schema": 1, "runId": "<dir basename>", "rig": "<project id>",
    "scope": "...", "goal": "...", "target": "...?", "env": "...?",
    "startedAt": iso8601, "endedAt": iso8601?,
    "status": "running" | "done" | "failed" | "abandoned",
    "verdict": "pass" | "fail" | "mixed"?, "costUsd": number?,
    "findings": [{ "id", "severity", "title", "ticket"? }]? }

CLI (for markdown missions — no inline python needed):
  python3 common/runlog.py open  <run_dir> --rig <id> --scope <s> --goal <g>
                                 [--target <t>] [--env <e>]
  python3 common/runlog.py close <run_dir> --status done|failed|abandoned
                                 [--verdict pass|fail|mixed]
                                 [--findings <path.json>] [--cost-usd <n>]
"""
import argparse
import json
import os
import sys
import time

SCHEMA = 1
STATUSES = ("running", "done", "failed", "abandoned")
VERDICTS = ("pass", "fail", "mixed")

RUN_JSON = "run.json"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path(run_dir):
    return os.path.join(run_dir, RUN_JSON)


def _write_atomic(run_dir, record):
    """tmp + rename so a reader never sees a half-written record."""
    tmp = _path(run_dir) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, _path(run_dir))


def read_run(run_dir):
    """The current record, or None (absent or unreadable — caller decides)."""
    try:
        with open(_path(run_dir)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def open_run(run_dir, rig, scope, goal, target=None, env=None):
    """Stamp run.json at run-dir creation. Idempotent: an existing readable
    record wins (a re-run of the open step must not clobber startedAt)."""
    existing = read_run(run_dir)
    if existing is not None:
        return existing
    record = {
        "schema": SCHEMA,
        "runId": os.path.basename(os.path.normpath(run_dir)),
        "rig": rig,
        "scope": scope,
        "goal": goal,
        "startedAt": _now_iso(),
        "status": "running",
    }
    if target:
        record["target"] = target
    if env:
        record["env"] = env
    _write_atomic(run_dir, record)
    return record


def close_run(run_dir, status, verdict=None, findings=None, cost_usd=None):
    """Settle the record. Tolerant of a corrupt/missing open record: closing
    must never kill a finished run's last step — record what we know."""
    if status not in STATUSES or status == "running":
        raise ValueError("close status must be one of done|failed|abandoned")
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError("verdict must be one of pass|fail|mixed")
    record = read_run(run_dir)
    if record is None:
        if os.path.exists(_path(run_dir)):
            print("runlog: existing run.json unreadable — rewriting from close", file=sys.stderr)
        record = {
            "schema": SCHEMA,
            "runId": os.path.basename(os.path.normpath(run_dir)),
            "startedAt": _now_iso(),
        }
    record["status"] = status
    record["endedAt"] = _now_iso()
    if verdict is not None:
        record["verdict"] = verdict
    if findings is not None:
        record["findings"] = findings
    if cost_usd is not None:
        record["costUsd"] = cost_usd
    _write_atomic(run_dir, record)
    return record


def load_findings(path):
    with open(path) as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, list):
        raise ValueError("--findings file must hold a JSON array")
    return loaded


def main(argv=None):
    parser = argparse.ArgumentParser(description="neutral run.json lifecycle")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="stamp run.json at run-dir creation")
    p_open.add_argument("run_dir")
    p_open.add_argument("--rig", required=True)
    p_open.add_argument("--scope", required=True)
    p_open.add_argument("--goal", required=True)
    p_open.add_argument("--target")
    p_open.add_argument("--env")

    p_close = sub.add_parser("close", help="settle run.json as the run's last step")
    p_close.add_argument("run_dir")
    p_close.add_argument("--status", required=True, choices=[s for s in STATUSES if s != "running"])
    p_close.add_argument("--verdict", choices=list(VERDICTS))
    p_close.add_argument("--findings", help="path to a JSON array of findings")
    p_close.add_argument("--cost-usd", type=float, dest="cost_usd")

    args = parser.parse_args(argv)
    if not os.path.isdir(args.run_dir):
        parser.error(f"not a run dir: {args.run_dir}")

    if args.cmd == "open":
        record = open_run(args.run_dir, args.rig, args.scope, args.goal, args.target, args.env)
    else:
        findings = load_findings(args.findings) if args.findings else None
        record = close_run(args.run_dir, args.status, args.verdict, findings, args.cost_usd)
    json.dump(record, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
