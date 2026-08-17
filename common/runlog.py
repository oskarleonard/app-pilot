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
import fcntl
import json
import math
import os
import sys
import time
from contextlib import contextmanager

SCHEMA = 1
CLOSE_STATUSES = ("done", "failed", "abandoned")
STATUSES = ("running", *CLOSE_STATUSES)
VERDICTS = ("pass", "fail", "mixed")

RUN_JSON = "run.json"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path(run_dir):
    return os.path.join(run_dir, RUN_JSON)


@contextmanager
def _run_lock(run_dir):
    """Serialize open/close per run dir by flocking the DIRECTORY fd (no lock
    file, no residue). 'Close is final' is only enforceable when the check and
    the write are one critical section — without this, two closers both read
    'running' and the last writer wins. POSIX-only, like the engines."""
    fd = os.open(run_dir, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_atomic(run_dir, record):
    """tmp + rename so a reader never sees a half-written record. The tmp name
    is per-process so concurrent writers can't truncate each other's file;
    allow_nan enforces the strict-JSON contract at the write boundary; a failed
    dump removes its tmp instead of leaking it into the run dir."""
    tmp = f"{_path(run_dir)}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as fh:
            json.dump(record, fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
        os.replace(tmp, _path(run_dir))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_run(run_dir):
    """The current record, or None (absent, unreadable, or not a dict —
    a run.json holding `[]` or a bare string is no record; caller decides)."""
    try:
        with open(_path(run_dir)) as fh:
            loaded = json.load(fh)
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def open_run(run_dir, rig, scope, goal, target=None, env=None):
    """Stamp run.json at run-dir creation. Idempotent: an existing readable
    record wins (a re-run of the open step must not clobber startedAt)."""
    with _run_lock(run_dir):
        return _open_locked(run_dir, rig, scope, goal, target, env)


def _open_locked(run_dir, rig, scope, goal, target, env):
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
    """Settle the record — close is FINAL. A retry of the IDENTICAL close
    (status, verdict, findings, cost all matching or omitted) is an idempotent
    no-op; any other close of a settled record refuses — differing evidence
    must never be silently answered with the old record. Tolerant of a
    corrupt/missing open record: closing must never kill a finished run's last
    step — record what we know, labelled, keeping the corrupt file aside."""
    if status not in CLOSE_STATUSES:
        raise ValueError("close status must be one of done|failed|abandoned")
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError("verdict must be one of pass|fail|mixed")
    if cost_usd is not None and not math.isfinite(cost_usd):
        raise ValueError("costUsd must be finite (NaN/Infinity is not valid JSON)")
    with _run_lock(run_dir):
        return _close_locked(run_dir, status, verdict, findings, cost_usd)


def _close_locked(run_dir, status, verdict, findings, cost_usd):
    record = read_run(run_dir)
    if record is not None and record.get("status") in CLOSE_STATUSES:
        same = (
            record.get("status") == status
            and record.get("verdict") == verdict
            and (findings is None or record.get("findings") == findings)
            and (cost_usd is None or record.get("costUsd") == cost_usd)
        )
        if same:
            return record  # idempotent retry of the same close
        raise ValueError(
            f"run already closed as {record.get('status')} — close is final"
        )
    if record is None:
        if os.path.exists(_path(run_dir)):
            corrupt = _path(run_dir) + ".corrupt"
            try:
                os.replace(_path(run_dir), corrupt)
                print(f"runlog: existing run.json unreadable — kept as {os.path.basename(corrupt)}, rewriting from close", file=sys.stderr)
            except OSError:
                print("runlog: existing run.json unreadable — rewriting from close", file=sys.stderr)
        record = {
            "schema": SCHEMA,
            "runId": os.path.basename(os.path.normpath(run_dir)),
            "startedAt": _now_iso(),
            # The open record was missing/unreadable — say so rather than
            # passing off a rig/scope/goal-less record as a full one.
            "recovered": True,
        }
    elif not all(k in record for k in ("runId", "startedAt", "status")):
        # Parseable dict that isn't a v1 open record (e.g. {}) — augment it,
        # but labelled, never passed off as a full record.
        record.setdefault("schema", SCHEMA)
        record.setdefault("runId", os.path.basename(os.path.normpath(run_dir)))
        record.setdefault("startedAt", _now_iso())
        record["recovered"] = True
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


def _reject_constant(token):
    raise ValueError(f"non-finite {token} in findings — not valid JSON")


def load_findings(path):
    with open(path) as fh:
        # parse_constant rejects NaN/Infinity at the door — json.load would
        # otherwise accept them and the strict re-dump would fail later.
        loaded = json.load(fh, parse_constant=_reject_constant)
    if not isinstance(loaded, list):
        raise ValueError("--findings file must hold a JSON array")
    if not all(isinstance(f, dict) for f in loaded):
        raise ValueError("--findings entries must be objects ({id,severity,title,ticket?})")
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
    p_close.add_argument("--status", required=True, choices=list(CLOSE_STATUSES))
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
