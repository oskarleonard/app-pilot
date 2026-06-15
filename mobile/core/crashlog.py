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

PATTERNS = [
    "Cannot find native module", "Invariant Violation", "TurboModuleRegistry",
    "Unhandled JS Exception", "Unhandled promise rejection", "Possible Unhandled Promise",
    "RedBox", "RCTFatal", "ExceptionsManager", "Terminating app due to uncaught",
    "*** Terminating", "fatal error", "Fatal Exception", "EXC_BAD", "facebook::react",
]


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


def start():
    """Idempotent — leaves an existing live stream running; else spawns one."""
    pid = _pid()
    if alive(pid):
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


def hits(n=20):
    """(last n hit lines, total hits, total lines) of crash-pattern matches.

    Scans only the last MAX_TAIL_BYTES of the file so RAM stays bounded no
    matter how large the crash log grows. `total`/`scanned` are therefore
    counts WITHIN the scanned tail, not the whole file — which is fine: we
    want recent crashes, and an unbounded full-file read is exactly what
    spiked RAM before.
    """
    if not os.path.exists(target.CRASHLOG):
        return [], 0, 0
    size = os.path.getsize(target.CRASHLOG)
    pats = [p.lower() for p in PATTERNS]
    with open(target.CRASHLOG, "rb") as fh:
        if size > MAX_TAIL_BYTES:
            fh.seek(size - MAX_TAIL_BYTES)
            fh.readline()  # discard the partial first line after the seek
        data = fh.read()
    lines = data.decode(errors="replace").splitlines()
    h = [ln for ln in lines if any(p in ln.lower() for p in pats)]
    return h[-n:], len(h), len(lines)
