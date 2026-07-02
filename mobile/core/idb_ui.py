#!/usr/bin/env python3
"""idb-based accessibility helpers for app-pilot.  [DEV TOOL]

Reads the iOS accessibility tree via idb (Facebook's iOS Development Bridge) so we
can find + tap UI elements by their accessibilityLabel instead of guessing pixel
coordinates. Far more robust than the osascript/pixel fallback in common.py.

Setup (one-time, per machine):
  brew tap facebook/fb && brew install idb-companion
  python3 -m venv ~/.idb-venv && ~/.idb-venv/bin/pip install fb-idb
  (path lives in target.IDB)

API (coordinates are POINTS — the space idb describe-all + tap share):
  describe(udid)         -> [Element] from `idb ui describe-all`
  labelled(udid)         -> only elements that have a label
  find(udid, label,role) -> best Element matching label (exact > substring) or None
  tap_label(udid, label) -> find + tap its frame center; returns the Element or None
  tap_point(udid, x, y)  -> `idb ui tap x y`; True iff delivered (failure -> stderr)
  tap_frac(udid, fx, fy) -> tap at a fraction of the screen (fallback for unlabelled)
  tap_tab(udid, name)    -> tap a bottom tab by name (the tab bar collapses its
                            children into one group, so we tap the n-th segment)
  type_text(udid, text)  -> type into the focused field, per-char (bulk text drops chars)
  press_key(udid, code)  -> press a HID keycode (42=backspace, 40=return)

CLI:  python3 idb_ui.py {tree|find|tap <label>|tab <name>|frac fx,fy|text <s>|key <code>} [--udid X]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# target.py lives one level up (the project/core boundary — see PORTING.md).
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import target  # noqa: E402

IDB = getattr(target, "IDB", None) or os.path.expanduser("~/.idb-venv/bin/idb")


def _run_idb(args, timeout):
    """subprocess.run for idb calls that can never traceback: a hung companion
    (TimeoutExpired) or a missing idb binary (OSError) comes back as a normal
    failed CompletedProcess (rc 124/127) the caller can report — not an
    uncaught exception that kills the whole command mid-run."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args, 124, stdout="",
            stderr=f"timed out after {timeout}s (companion hung? run `app-pilot recover`)")
    except OSError as e:
        return subprocess.CompletedProcess(
            args, 127, stdout="",
            stderr=f"cannot run {args[0]}: {e} (run `app-pilot doctor`)")


def _last_err(out):
    """One-line failure detail from a CompletedProcess (last stderr line).
    Capped: idb can emit a single multi-KB line (e.g. a bad-UDID error dumps
    every UDID on the machine) — the head carries the actual reason."""
    err = (out.stderr or "").strip().splitlines()
    detail = err[-1] if err else f"exit {out.returncode}"
    return detail[:200] + "…" if len(detail) > 200 else detail


class Element:
    __slots__ = ("label", "role", "cx", "cy", "enabled", "frame")

    def __init__(self, d):
        self.label = (d.get("AXLabel") or d.get("title") or "").strip()
        self.role = d.get("type") or d.get("role") or ""
        f = d.get("frame") or {}
        self.frame = f
        self.cx = f.get("x", 0) + f.get("width", 0) / 2
        self.cy = f.get("y", 0) + f.get("height", 0) / 2
        self.enabled = d.get("enabled", True)

    def __repr__(self):
        return f"<{self.role} {self.label!r} @({self.cx:.0f},{self.cy:.0f}) en={self.enabled}>"


def describe(udid):
    out = _run_idb([IDB, "ui", "describe-all", "--udid", udid], timeout=30)
    if out.returncode != 0:
        # An empty tree from a FAILED read must not pass silently for "blank
        # screen" — say why on stderr so `tree`/`tap` callers see the real cause.
        print(f"idb describe-all failed: {_last_err(out)}", file=sys.stderr)
        return []
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []
    return [Element(d) for d in data]


# ─── Companion lifecycle (self-healing) ───────────────────────────────────────
# A terminal force-quit (or any crash of the process that spawned idb) kills the
# idb_companion daemon and leaves a stale unix socket at
# /tmp/idb/<udid>_companion.sock. After that, every `idb ui describe-all` fails
# with "Failed to connect to companion … Connection refused", so tap/tree
# silently no-op. `devserver.py recover` calls ensure_companion() to detect this
# and respawn — same self-healing spirit as the Metro restart.


def _companion_sock(udid):
    return f"/tmp/idb/{udid}_companion.sock"


def companion_alive(udid, timeout=30):
    """True iff idb can reach a companion for this udid. The probe is a real
    describe-all: on success it prints a JSON array (even '[]' on a blank
    screen); on a dead/stale companion it exits non-zero with a connect error.
    Callers probing in a loop (ensure_companion) pass a SHORT timeout so a
    degraded companion can't stall recovery for minutes.
    """
    out = _run_idb([IDB, "ui", "describe-all", "--udid", udid], timeout=timeout)
    return out.returncode == 0 and out.stdout.lstrip().startswith("[")


def _find_companion_binary():
    """Locate idb_companion (the native daemon, separate from the python `idb`
    client). brew installs it to /opt/homebrew/bin (Apple Silicon) or
    /usr/local/bin (Intel)."""
    return (
        shutil.which("idb_companion")
        or next(
            (p for p in ("/opt/homebrew/bin/idb_companion", "/usr/local/bin/idb_companion")
             if os.path.exists(p)),
            None,
        )
    )


def ensure_companion(udid):
    """Respawn the idb companion if it's unreachable. Returns (ok, message).

    No-op (fast) when the companion is already alive. When dead: removes the
    stale socket, spawns a fresh `idb_companion` detached, and polls up to ~5s
    for it to come up. Probes use short timeouts so recovery stays bounded.
    """
    if companion_alive(udid, timeout=5):
        return True, "idb companion alive"
    sock = _companion_sock(udid)
    try:
        os.remove(sock)
    except FileNotFoundError:
        pass
    binary = _find_companion_binary()
    if not binary:
        return False, "idb_companion not found (brew install idb-companion)"
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    subprocess.Popen(
        [binary, "--udid", udid, "--grpc-domain-sock", sock],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(10):
        time.sleep(0.5)
        if companion_alive(udid, timeout=2):
            return True, "respawned idb companion (was dead — stale socket cleared)"
    return False, "respawned idb_companion but it's still unreachable"


def labelled(udid):
    return [e for e in describe(udid) if e.label]


def find(udid, label, role=None):
    label_l = label.lower()
    els = describe(udid)
    if role:
        els = [e for e in els if role.lower() in e.role.lower()]
    exact = [e for e in els if e.label.lower() == label_l]
    if exact:
        return exact[0]
    sub = [e for e in els if label_l in e.label.lower()]
    return sub[0] if sub else None


def screen_size(udid):
    for e in describe(udid):
        if "application" in (e.role or "").lower():
            return e.frame.get("width", 402), e.frame.get("height", 874)
    return 402, 874


def tap_point(udid, x, y):
    """Tap at device coords. Returns True iff idb delivered the tap.

    A failed tap (dead/hung companion, wrong UDID, idb missing) must never
    masquerade as a delivered one — the idb error goes to stderr and False
    comes back, the same contract type_text() has for characters."""
    out = _run_idb([IDB, "ui", "tap", str(round(x)), str(round(y)), "--udid", udid],
                   timeout=30)
    if out.returncode != 0:
        print(f"idb tap failed: {_last_err(out)}", file=sys.stderr)
        return False
    return True


def tap_label(udid, label, role=None):
    """find + tap. Returns the Element or None (= no such label); a found-but-
    undelivered tap is reported on stderr by tap_point."""
    el = find(udid, label, role)
    if el:
        tap_point(udid, el.cx, el.cy)
    return el


def tap_frac(udid, fx, fy):
    w, h = screen_size(udid)
    return tap_point(udid, fx * w, fy * h)


def type_text(udid, text):
    """Type a string into the FOCUSED field, one character at a time. idb's bulk
    `ui text` intermittently drops trailing characters (observed live: typing
    '1.50' landed only '1'); per-char delivery with a small settle delay is
    reliable for the short inputs we care about (money amounts, notes).

    Returns the count of characters idb failed to deliver (non-zero exit), so a
    caller can surface a partial/failed entry instead of reporting false success
    (e.g. when the companion is down, every char silently no-ops)."""
    failures = 0
    for ch in text:
        out = _run_idb([IDB, "ui", "text", ch, "--udid", udid], timeout=15)
        if out.returncode != 0:
            failures += 1
        time.sleep(0.04)
    return failures


def press_key(udid, code, times=1):
    """Press a HID keycode N times (42 = backspace/clear, 40 = return)."""
    for _ in range(times):
        _run_idb([IDB, "ui", "key", str(code), "--udid", udid], timeout=15)
        time.sleep(0.02)


def swipe(udid, x1, y1, x2, y2, duration=0.3):
    """Swipe between two device-coord points. Works on NATIVE scroll surfaces
    (RN ScrollView/FlatList use UIScrollView's pan recognizer) and on native
    pan-tracking controls — verified: a swipe across a UISwitch frame flips it
    while taps never do — but NOT on react-native-gesture-handler gestures
    (gorhom drag-to-dismiss, RNGH swipeables), which ignore idb-synthesized
    touches entirely."""
    _run_idb(
        [IDB, "ui", "swipe",
         str(round(x1)), str(round(y1)), str(round(x2)), str(round(y2)),
         "--duration", str(duration), "--udid", udid],
        timeout=30,
    )


def scroll(udid, direction="down", amount=0.35):
    """Scroll the screen content. direction 'down' reveals lower content
    (finger drags up). amount = fraction of screen height to traverse.
    Touch points are clamped into a safe band so large amounts can't start
    the gesture on the floating tab bar (bottom) or the status bar (top)."""
    w, h = screen_size(udid)
    x = w / 2
    delta = h * amount
    top_safe, bottom_safe = h * 0.12, h * 0.80
    if direction == "down":
        y1, y2 = h * 0.62 + delta / 2, h * 0.62 - delta / 2
    else:
        y1, y2 = h * 0.38 - delta / 2, h * 0.38 + delta / 2
    y1 = min(max(y1, top_safe), bottom_safe)
    y2 = min(max(y2, top_safe), bottom_safe)
    swipe(udid, x, y1, x, y2)


def _describe_point(udid, x, y):
    out = _run_idb(
        [IDB, "ui", "describe-point", str(round(x)), str(round(y)), "--udid", udid],
        timeout=30,
    )
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def tap_tab(udid, name):
    """Tap a bottom tab by name. NativeTabs renders a native UITabBar whose items
    don't show up in `describe-all` (only a full-width 'Tab Bar' group does) — but
    they ARE accessible via `describe-point`. On iOS 26 Liquid Glass the visual
    pill is CENTERED and much narrower than the group frame, so naive
    frame-segment math can tap empty glass (verified live: a 2-tab pill spans
    ~43% of a 402pt group). Probe describe-point along the group's y-center,
    center-outward, and tap the labelled item that matches."""
    order = [t.lower() for t in getattr(target, "TAB_ORDER", [])]
    key = name.strip().lower()
    if key not in order:
        return False
    grp = find(udid, "Tab Bar", role="Group")
    if not grp:
        # iOS 26 / Expo Router: tab items appear directly as Button elements in
        # describe-all with labels like "Brain, tab, 2 of 5" — no wrapping Tab
        # Bar group is present in the tree.  Fall back to direct label match.
        el = find(udid, key, role="Button")
        if el:
            return tap_point(udid, el.cx, el.cy)
        return False
    f = grp.frame
    gx, gw = f.get("x", 0), f.get("width", 0)
    y = f.get("y", 0) + f.get("height", 0) / 2
    probes = 16
    center_out = sorted(range(probes), key=lambda i: abs(i - (probes - 1) / 2))
    for i in center_out:
        x = gx + gw * (i + 0.5) / probes
        d = _describe_point(udid, x, y)
        if not d:
            continue
        label = (d.get("AXLabel") or "").strip().lower()
        if label == key or (label and key in label):
            fr = d.get("frame") or {}
            cx = fr.get("x", x) + fr.get("width", 0) / 2
            cy = fr.get("y", y) + fr.get("height", 0) / 2
            return tap_point(udid, cx or x, cy or y)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tree", "find", "tap", "tab", "frac", "scroll",
                                    "text", "key", "companion"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--udid", default=target.UDID)
    ap.add_argument("--role", default=None)
    ap.add_argument("--amount", type=float, default=0.35)
    a = ap.parse_args()
    if a.cmd in ("find", "tap", "tab", "frac", "text", "key") and not a.arg:
        ap.error(f"'{a.cmd}' requires an argument")  # fail fast, not a traceback
    if a.cmd == "tree":
        for e in labelled(a.udid):
            print(e)
    elif a.cmd == "find":
        print(find(a.udid, a.arg, a.role))
    elif a.cmd == "tap":
        print("tapped", tap_label(a.udid, a.arg, a.role))
    elif a.cmd == "tab":
        print(f"tab {a.arg} -> {tap_tab(a.udid, a.arg)}")
    elif a.cmd == "frac":
        fx, fy = (float(v) for v in a.arg.split(","))
        tap_frac(a.udid, fx, fy)
        print(f"tapped frac {fx},{fy}")
    elif a.cmd == "scroll":
        direction = a.arg or "down"
        scroll(a.udid, direction, a.amount)
        print(f"scrolled {direction} (amount={a.amount})")
    elif a.cmd == "text":
        failed = type_text(a.udid, a.arg)
        if failed:
            ap.error(f"idb failed to deliver {failed}/{len(a.arg)} char(s)")
        print(f"typed {a.arg!r}")
    elif a.cmd == "key":
        if not a.arg.isdigit():
            ap.error("'key' requires a numeric HID keycode (e.g. 42=backspace, 40=return)")
        press_key(a.udid, int(a.arg))
        print(f"pressed key {a.arg}")
    elif a.cmd == "companion":
        # `companion` (no arg) = check; `companion ensure` = respawn if dead
        if a.arg == "ensure":
            ok, msg = ensure_companion(a.udid)
            print(("OK: " if ok else "FAIL: ") + msg)
        else:
            print(f"idb companion: {'UP' if companion_alive(a.udid) else 'DOWN'}")


if __name__ == "__main__":
    main()
