"""Neutral per-run machine record: runs/<id>/run.json, written beside the
mission's markdown artifacts.

The markdown (journal.md, findings.md) stays the human artifact; run.json is
the machine contract — any dashboard or tool can consume a run without parsing
prose. It is deliberately engine-neutral: no consumer's schema leaks in here,
and runs must keep recording with no dashboard on the machine.

Lifecycle: `open_run()` at run-dir creation (stamps status "running"),
`close_run()` as the run's last step. A run that dies without closing can be
settled by consumers from the run dir's ACTIVITY (its files' mtimes — appends
touch files, not the dir inode); a run that never OPENS is invisible — which
is why missions must open first, not close-only.

This module is the raw lifecycle; the engines' `app-pilot close` layers audit
logging and .current bookkeeping on top. The CLI below exists for adopting a
run dir with zero app-pilot wiring (ad-hoc terminal QA, retro-stamping).

Schema (version 1 — every field after "status" is optional, and later
additions are optional too, so a record written before them still parses):
  { "schema": 1, "runId": "<dir basename>", "rig": "<project id>",
    "scope": "...", "goal": "...", "target": "...?", "env": "...?",
    "startedAt": iso8601, "endedAt": iso8601?,
    "status": "running" | "done" | "failed" | "abandoned",
    "verdict": "pass" | "fail" | "mixed"?, "costUsd": number?,
    "gate": "PASS" | "PASS_WITH_EXCEPTIONS" | "INCOMPLETE"?,
    "gateReasons": ["..."]?,
    "findings": [{ "id", "severity", "title", "ticket"?,
                   "class"?: parity|copy|prd-gap|cross-surface|number|
                             functional|console|network|crash,
                   "expected"?, "observed"?,
                   "designRef"?: { "fileKey", "nodeId", "band"?,
                                   "renderHash"?, "render"? },
                   "region"?: { "image", "space": points|pixels|viewport,
                                "imageW", "imageH", "x", "y", "w", "h",
                                "transform"? },
                   "repro"?: ["step", ...],
                   "basis"?: observed|measured|verified-in-source,
                   "certainty"?: confirmed|suspected,
                   "judge"?: raised|lowered|added }]?,
    "oracleQuestions": [{ "screen", "platform"?, "citations": ["..."],
                          "statement",
                          "suggestedRecipient"?: design|product|engineering }]?,
    "insufficientEvidence": [{ "screen", "need", "platform"?, "state"? }]? }
Meaning of each field: missions/_format.md ("Run record"). The optional
finding/record fields are validated only when present.

CLI (for markdown missions — no inline python needed):
  python3 common/runlog.py open  <run_dir> --rig <id> --scope <s> --goal <g>
                                 [--target <t>] [--env <e>]
  python3 common/runlog.py close <run_dir> --status done|failed|abandoned
                                 [--verdict pass|fail|mixed]
                                 [--gate PASS|PASS_WITH_EXCEPTIONS|INCOMPLETE]
                                 [--gate-reason <text>]...
                                 [--findings <path.json>] [--cost-usd <n>]
                                 [--oracle-questions <path.json>]
                                 [--insufficient-evidence <path.json>]
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
# The release-gate verdict — separate from `verdict` and from severity.
GATES = ("PASS", "PASS_WITH_EXCEPTIONS", "INCOMPLETE")
FINDING_CLASSES = ("parity", "copy", "prd-gap", "cross-surface", "number",
                   "functional", "console", "network", "crash")
BASES = ("observed", "measured", "verified-in-source")
CERTAINTIES = ("confirmed", "suspected")
JUDGE_MARKS = ("raised", "lowered", "added")
REGION_SPACES = ("points", "pixels", "viewport")
RECIPIENTS = ("design", "product", "engineering")

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


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _is_number(value):
    # bool is an int subclass — a `true` coordinate is a bug, not a 1.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _check_enum(where, key, value, allowed):
    if value not in allowed:
        raise ValueError(f"{where}: {key} must be one of {'|'.join(allowed)}")


def _check_text_list(where, key, value, non_empty=False):
    if not isinstance(value, list) or not all(_is_text(v) for v in value):
        raise ValueError(f"{where}: {key} must be a list of non-empty strings")
    if non_empty and not value:
        raise ValueError(f"{where}: {key} must not be empty")


def _check_required_text(where, obj, keys):
    for key in keys:
        if not _is_text(obj.get(key)):
            raise ValueError(f"{where}: {key} is required (non-empty string)")


def _check_optional_text(where, obj, keys):
    for key in keys:
        if key in obj and not isinstance(obj[key], str):
            raise ValueError(f"{where}: {key} must be a string")


def validate_finding(finding):
    """Checks the optional evidence fields only when present — a legacy
    {id,severity,title,ticket?} finding passes untouched."""
    if not isinstance(finding, dict):
        raise ValueError("findings entries must be objects ({id,severity,title,ticket?})")
    where = f"finding {finding.get('id', '?')}"
    for key, allowed in (("class", FINDING_CLASSES), ("basis", BASES),
                         ("certainty", CERTAINTIES), ("judge", JUDGE_MARKS)):
        if key in finding:
            _check_enum(where, key, finding[key], allowed)
    _check_optional_text(where, finding, ("expected", "observed"))
    if "repro" in finding:
        _check_text_list(where, "repro", finding["repro"])
    if "designRef" in finding:
        ref = finding["designRef"]
        if not isinstance(ref, dict):
            raise ValueError(f"{where}: designRef must be an object")
        _check_required_text(f"{where} designRef", ref, ("fileKey", "nodeId"))
        _check_optional_text(f"{where} designRef", ref, ("band", "renderHash", "render"))
    if "region" in finding:
        region = finding["region"]
        if not isinstance(region, dict):
            raise ValueError(f"{where}: region must be an object")
        # A box without its coordinate space is worse than no box — a reader
        # cannot tell points from @3x pixels or viewport from full-page.
        _check_required_text(f"{where} region", region, ("image",))
        _check_enum(f"{where} region", "space", region.get("space"), REGION_SPACES)
        for key in ("imageW", "imageH", "x", "y", "w", "h"):
            if not _is_number(region.get(key)):
                raise ValueError(f"{where} region: {key} is required (finite number)")
        if region["imageW"] <= 0 or region["imageH"] <= 0 or region["w"] < 0 or region["h"] < 0:
            raise ValueError(f"{where} region: imageW/imageH must be > 0, w/h >= 0")


def validate_oracle_question(question):
    if not isinstance(question, dict):
        raise ValueError("oracleQuestions entries must be objects")
    where = "oracle question"
    _check_required_text(where, question, ("screen", "statement"))
    _check_text_list(where, "citations", question.get("citations"), non_empty=True)
    _check_optional_text(where, question, ("platform",))
    if "suggestedRecipient" in question:
        _check_enum(where, "suggestedRecipient", question["suggestedRecipient"], RECIPIENTS)


def validate_insufficient_evidence(entry):
    if not isinstance(entry, dict):
        raise ValueError("insufficientEvidence entries must be objects")
    where = "insufficientEvidence"
    _check_required_text(where, entry, ("screen", "need"))
    _check_optional_text(where, entry, ("platform", "state"))


def _validate_gate(status, gate, gate_reasons):
    if gate is None:
        if gate_reasons is not None:
            raise ValueError("gateReasons without a gate")
        return
    _check_enum("close", "gate", gate, GATES)
    reasons = gate_reasons or []
    _check_text_list("close", "gateReasons", reasons)
    # Exceptions are disclosed and a gap is named — never a bare non-PASS.
    if gate != "PASS" and not reasons:
        raise ValueError(f"gate {gate} needs at least one gateReason")
    # A run that died or was abandoned cannot certify anything.
    if gate != "INCOMPLETE" and status != "done":
        raise ValueError(f"gate {gate} requires status done (use INCOMPLETE)")


def close_run(run_dir, status, verdict=None, findings=None, cost_usd=None,
              gate=None, gate_reasons=None, oracle_questions=None,
              insufficient_evidence=None):
    """Settle the record — close is FINAL. A retry of the IDENTICAL close
    (every supplied field matching, omitted ones ignored) is an idempotent
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
    _validate_gate(status, gate, gate_reasons)
    for entries, validate in ((findings, validate_finding),
                              (oracle_questions, validate_oracle_question),
                              (insufficient_evidence, validate_insufficient_evidence)):
        for entry in entries or ():
            validate(entry)
    extras = {
        "verdict": verdict,
        "findings": findings,
        "costUsd": cost_usd,
        "gate": gate,
        "gateReasons": gate_reasons,
        "oracleQuestions": oracle_questions,
        "insufficientEvidence": insufficient_evidence,
    }
    with _run_lock(run_dir):
        return _close_locked(run_dir, status, extras)


def _close_locked(run_dir, status, extras):
    record = read_run(run_dir)
    if record is not None and record.get("status") in CLOSE_STATUSES:
        # Omitted params (None) count as matching — a bare-status retry of a
        # richer close is still the same close, per the docstring's contract.
        same = record.get("status") == status and all(
            value is None or record.get(key) == value
            for key, value in extras.items()
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
    record.update({key: value for key, value in extras.items() if value is not None})
    _write_atomic(run_dir, record)
    return record


def _reject_constant(token):
    raise ValueError(f"non-finite {token} in findings — not valid JSON")


def _load_array(path, flag, validate):
    with open(path) as fh:
        # parse_constant rejects NaN/Infinity at the door — json.load would
        # otherwise accept them and the strict re-dump would fail later.
        loaded = json.load(fh, parse_constant=_reject_constant)
    if not isinstance(loaded, list):
        raise ValueError(f"{flag} file must hold a JSON array")
    for entry in loaded:
        validate(entry)
    return loaded


def load_findings(path):
    return _load_array(path, "--findings", validate_finding)


def load_oracle_questions(path):
    return _load_array(path, "--oracle-questions", validate_oracle_question)


def load_insufficient_evidence(path):
    return _load_array(path, "--insufficient-evidence", validate_insufficient_evidence)


def add_gate_args(parser):
    """The close flags beyond status/verdict/findings/cost — shared with the
    engines' `app-pilot close` so the two CLIs cannot drift."""
    parser.add_argument("--gate", choices=list(GATES), default=None)
    parser.add_argument("--gate-reason", action="append", dest="gate_reasons",
                        default=None, metavar="TEXT",
                        help="repeatable: one gap or disclosed exception per flag")
    parser.add_argument("--oracle-questions", dest="oracle_questions", default=None,
                        help="path to a JSON array of oracle questions")
    parser.add_argument("--insufficient-evidence", dest="insufficient_evidence",
                        default=None, help="path to a JSON array of recapture requests")


def gate_kwargs(args):
    """close_run kwargs for the add_gate_args flags (files loaded + validated)."""
    return {
        "gate": args.gate,
        "gate_reasons": args.gate_reasons,
        "oracle_questions": (load_oracle_questions(args.oracle_questions)
                             if args.oracle_questions else None),
        "insufficient_evidence": (load_insufficient_evidence(args.insufficient_evidence)
                                  if args.insufficient_evidence else None),
    }


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
    add_gate_args(p_close)
    p_close.add_argument("--findings", help="path to a JSON array of findings")
    p_close.add_argument("--cost-usd", type=float, dest="cost_usd")

    args = parser.parse_args(argv)
    if not os.path.isdir(args.run_dir):
        parser.error(f"not a run dir: {args.run_dir}")

    if args.cmd == "open":
        record = open_run(args.run_dir, args.rig, args.scope, args.goal, args.target, args.env)
    else:
        findings = load_findings(args.findings) if args.findings else None
        record = close_run(args.run_dir, args.status, args.verdict, findings,
                           args.cost_usd, **gate_kwargs(args))
    json.dump(record, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
