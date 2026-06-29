#!/usr/bin/env python3
"""OS-level crash-log capture for app-pilot.  [DEV TOOL]

Streams the iOS unified log for the app + React Native subsystem to target.CRASHLOG
via `xcrun simctl spawn <udid> log stream`, so red-box / native-module / fatal
crashes that never reach Metro stdout are still caught. devserver.py starts/stops
this alongside Metro (serve/recover/stop); read hits via `devserver.py crashes`.
"""
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# target.py lives one level up (project/core boundary).
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import target  # noqa: E402

# The process-image hint comes from target.py so this file stays portable
# (an earlier version hardcoded its own app name here).
_HINT = getattr(target, "LOG_PROCESS_HINT", "")
PREDICATE = 'subsystem == "com.facebook.react.log"' + (
    f' OR processImagePath CONTAINS[c] "{_HINT}"' if _HINT else ""
)

# Read at most this many bytes from the END of the crash log when scanning for
# hits. Bounds RAM no matter how large the file grows (recent crashes are what
# matter). Was the cause of a 40GB RAM spike in an earlier version: the old
# code did `open(f).read().splitlines()` on a 7.8GB file (the file had
# ballooned because `log stream` ran at `--level debug` — the full RN debug
# firehose). Both fixed: default log level below (crashes are error/fault, not
# debug) + this tail cap.
MAX_TAIL_BYTES = 8 * 1024 * 1024  # 8 MB

# Crash-log line markers, each tagged with whether it's FATAL — a line that
# means the app is genuinely broken (red-box / native crash / fatal abort), as
# opposed to a soft warning. `devserver health` gates its verdict on the FATAL
# subset ONLY: a false PASS on a crashed app is the worst failure for the engine
# that verifies its own fixes, so health must go red on a real crash — while a
# soft marker must NOT falsely FAIL a healthy app (a false FAIL is its own
# reliability bug). The advisory (fatal=False) markers stay reportable via
# `crashes` but never gate health:
#   - "Unhandled promise rejection"/"Possible Unhandled Promise" can be caught
#     or dev-only;
#   - "ExceptionsManager"/"TurboModuleRegistry"/"facebook::react" appear in
#     non-fatal native logs too.
# PATTERNS (what `crashes` scans) and FATAL_PATTERNS (the health gate) are both
# DERIVED from this one table, so the subset relationship can never silently
# drift — add a marker once, here, with its fatal flag.
_MARKERS = [
    ("Cannot find native module", True),
    ("Invariant Violation", True),
    ("TurboModuleRegistry", False),
    ("Unhandled JS Exception", True),
    ("Unhandled promise rejection", False),
    ("Possible Unhandled Promise", False),
    ("RedBox", True),
    ("RCTFatal", True),
    ("ExceptionsManager", False),
    ("Terminating app due to uncaught", True),
    ("*** Terminating", True),
    ("fatal error", True),
    ("Fatal Exception", True),
    ("EXC_BAD", True),
    ("facebook::react", False),
]
PATTERNS = [m for m, _ in _MARKERS]
FATAL_PATTERNS = [m for m, fatal in _MARKERS if fatal]


def _pid():
    try:
        return int(open(target.CRASHLOG_PID).read().strip())
    except Exception:
        return None


def _owned(pid):
    """True iff the PID's command still looks like OUR `log stream` process —
    guards against PID reuse making start() adopt / stop() kill a stranger."""
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    return "log" in cmd and "stream" in cmd


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    return _owned(pid)


def start(fresh=False):
    """Idempotent — leaves an existing live stream running; else spawns one.

    fresh=True first stops any running stream so the crash log is truncated to a
    clean baseline. `serve` uses it: each serve begins a new QA session, so the
    health crash-gate then reflects crashes SINCE this serve, not a crash left
    over from a previous session whose stream happened to still be alive.
    `recover` keeps the default (idempotent) so it never drops in-flight capture.
    """
    if fresh:
        stop()  # kills any live stream + clears the pidfile; always re-spawn below
    elif alive(pid := _pid()):
        return pid
    # Open with "w" (truncates any stale file from a prior session). Default
    # log level — NOT `--level debug`, which captures the entire React Native
    # debug firehose. Crashes (RCTFatal, *** Terminating, EXC_BAD, fatal error)
    # are logged at error/fault level, which the default level includes.
    log = open(target.CRASHLOG, "w")
    p = subprocess.Popen(
        ["xcrun", "simctl", "spawn", target.UDID, "log", "stream",
         "--style", "compact", "--predicate", PREDICATE],
        stdout=log, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    open(target.CRASHLOG_PID, "w").write(str(p.pid))
    return p.pid


def stop():
    pid = _pid()
    if alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    if os.path.exists(target.CRASHLOG_PID):
        os.remove(target.CRASHLOG_PID)


def status():
    pid = _pid()
    size = os.path.getsize(target.CRASHLOG) if os.path.exists(target.CRASHLOG) else 0
    return pid, alive(pid), size


def hits(n=20, patterns=None):
    """(last n hit lines, total hits, total lines) of crash-pattern matches.

    `patterns` defaults to the full advisory PATTERNS (what `crashes` reports);
    pass FATAL_PATTERNS for the high-confidence subset the health verdict gates
    on. Scans only the last MAX_TAIL_BYTES of the file so RAM stays bounded no
    matter how large the crash log grows. `total`/`scanned` are therefore
    counts WITHIN the scanned tail, not the whole file — which is fine: we
    want recent crashes, and an unbounded full-file read is exactly what
    spiked RAM before.
    """
    if not os.path.exists(target.CRASHLOG):
        return [], 0, 0
    size = os.path.getsize(target.CRASHLOG)
    pats = [p.lower() for p in (patterns or PATTERNS)]
    with open(target.CRASHLOG, "rb") as fh:
        if size > MAX_TAIL_BYTES:
            fh.seek(size - MAX_TAIL_BYTES)
            fh.readline()  # discard the partial first line after the seek
        data = fh.read()
    lines = data.decode(errors="replace").splitlines()
    h = [ln for ln in lines if any(p in ln.lower() for p in pats)]
    return h[-n:], len(h), len(lines)


def fatal_hits(n=20):
    """Like hits() but scoped to FATAL_PATTERNS — the verdict-gating subset that
    `health` consumes (high precision, so a real crash fails the gate without a
    soft warning falsely failing a healthy app)."""
    return hits(n, patterns=FATAL_PATTERNS)
