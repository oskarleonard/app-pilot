#!/usr/bin/env python3
"""
app-pilot dev-server manager — PINNED to one simulator + Metro port. [DEV TOOL]

Scoped on purpose (see target.py): the tester owns exactly target.UDID +
target.PORT. You can run OTHER projects on OTHER sims/ports simultaneously — it
never kills Metro on a different port or drives a different sim.

Process hygiene (so nothing lingers unnoticed):
  - `serve`/`recover` start Metro in its OWN process group (pid → target.PIDFILE,
    output → target.METRO_LOG) AND an OS-level crash-log stream (see crashlog.py).
  - `status` shows whether the tester's Metro is alive (pid + what holds the port).
  - `stop` kills Metro + the crash stream (this pid/port only) and clears the pids.

Subcommands:
  serve         (re)start the tester's Metro (kills ONLY :PORT first), wait for UP
  recover       reconnect the app; restart Metro only if it's down
  reload        FALLBACK reload (cold-restart app) when Fast Refresh doesn't apply a change
  health        Metro HTTP + app-vs-launcher state (on target.UDID) + backend +
                idb companion + NO fatal crash since serve — the verdict gate
  status        is the tester's Metro running? pid, port holder, logfile
  stop          kill the tester's Metro + crash stream (this pid/port only)
  metrolog [N]  last N lines of the Metro log (JS warns / console / bundling)
  crashes [N]   crash-pattern hits from the OS log stream (native/red-box/fatal)
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # for sibling core modules (common, crashlog)
# target.py lives one level up (project/core boundary).
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import common  # noqa: E402
import crashlog  # noqa: E402
import idb_ui  # noqa: E402
import target  # noqa: E402

LOCAL_BACKEND_URL = getattr(target, "BACKEND_URL", None)  # ground-truth API; unset/None = project has no backend
_BACKEND_HINT = getattr(target, "BACKEND_HINT", "start your local backend")  # printed when the backend is DOWN


def _find_repo():
    """Walk up to the project root (a dir containing package.json) so this folder
    works wherever it's dropped in a repo; falls back to two levels up."""
    d = os.environ.get("APP_PILOT_PROJECT_DIR") or HERE
    for _ in range(6):
        if os.path.exists(os.path.join(d, "package.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(os.path.join(HERE, "..", ".."))


REPO = _find_repo()

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def deeplink():
    # Dev-client deep link uses the app's registered URL scheme (app.config.ts
    # `scheme`), falling back to the bundle id if target.py doesn't pin one.
    # The tester drives a SIMULATOR, which shares the host loopback — always
    # 127.0.0.1 (a LAN IP would break whenever the Mac changes networks
    # mid-session; an earlier version used it because it predates the pin).
    scheme = getattr(target, "SCHEME", None) or target.BUNDLE
    return (f"{scheme}://expo-development-client/"
            f"?url=http%3A%2F%2F127.0.0.1%3A{target.PORT}")


def pids_on_port():
    out = subprocess.run(["lsof", "-ti", f"tcp:{target.PORT}"],
                         capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if p.strip().isdigit()]


def kill_port():
    """Kill ONLY what's bound to target.PORT (this project's Metro) + its group."""
    for pid in pids_on_port():
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass


def metro_ok():
    try:
        with urllib.request.urlopen(f"http://localhost:{target.PORT}/status", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def backend_ok():
    """ANY HTTP response (even 404) proves the local BE answers; connection
    refused means it's down. Only meaningful in mock mode with a backend."""
    if not LOCAL_BACKEND_URL:
        return True
    try:
        urllib.request.urlopen(LOCAL_BACKEND_URL, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def app_state():
    """'app' | 'launcher' | 'springboard' | 'unknown', read from the a11y tree.

    Detection is POSITIVE wherever it can be: a rig that pins APP_LABELS (a label
    visible ONLY inside its own running UI — a tab/header/content string) gets
    'app' only when one is actually visible, else 'unknown'. The launcher and the
    iOS home screen (springboard) are matched FIRST, so a silently-failed launch
    (deep link not approved → app terminated → home screen frontmost) is caught
    before the app check and can't read as the running app.

    LIMITATION — why APP_LABELS must be app-EXCLUSIVE: this greps a11y labels, so
    it cannot perfectly tell a missed launch from a running app if an APP_LABEL
    also appears on the home screen. E.g. APP_LABELS=["Settings"] matches the
    undeletable iOS Settings icon, and your app's own DISPLAY NAME labels its
    home-screen icon — either is a false PASS. The springboard check is a
    best-effort backstop: it only fires when a known home-screen icon (default
    "Safari") is visible, which a folder/Control-Center overlay/custom layout can
    hide. The real protection is choosing APP_LABELS that never appear on the
    home screen (an in-app tab/header, NOT the app name or a system-app name).
    Fully closing the gap needs a frontmost-bundle-id probe (idb exposes no such
    call today) — tracked as a follow-up.

    The old code checked the app BEFORE the home screen and required an
    English-only "safari" AND "messages" springboard, so a non-English home
    screen ("Meddelanden" on a Swedish device) fell through to a 'app' default —
    a false PASS on a localized box. An earlier version sampled the center pixel
    (its app is dark, the Expo dev-launcher light) — a light-themed app means
    pixels can't distinguish them, hence the label-grep approach. An EMPTY tree
    can also mean the idb companion is down — `health` reports that separately;
    treat 'unknown' as a prompt to cross-check, not a verdict.
    """
    els = idb_ui.labelled(target.UDID)
    if not els:
        return "unknown"
    labels = [e.label.lower() for e in els]
    joined = " | ".join(labels)

    # `hints or []`: a rig may PIN a label var to None (not just omit it), which
    # getattr's default can't catch — degrade to "no match" rather than crash the
    # engine's most safety-critical probe on a config typo.
    def has_text(hints):
        """Substring match anywhere in the tree — for phrase/partial signals."""
        return any(h.lower() in joined for h in (hints or []))

    def has_icon(hints):
        """Match an exact app/dock ICON label (e.g. "Safari"), tolerating a
        trailing a11y suffix like ", 3 new items" or ", tab, 2 of 5". Anchored
        at the label start, so an in-app "Open in Safari" button never matches."""
        heads = {lbl.split(",", 1)[0].strip() for lbl in labels}
        return any(h.lower() in heads for h in (hints or []))

    if has_text(getattr(target, "LAUNCHER_LABELS", ["development servers"])):
        return "launcher"
    # Home screen BEFORE the app check so a detected springboard wins over a
    # coincidental APP_LABEL match. "safari" is an unlocalized brand and a dock
    # icon's exact label → locale-safe; rigs can override SPRINGBOARD_LABELS.
    if has_icon(getattr(target, "SPRINGBOARD_LABELS", ["safari"])):
        return "springboard"
    app_labels = getattr(target, "APP_LABELS", [])
    if app_labels:
        # Strict rig: 'app' only when its own label is positively visible, else
        # 'unknown' — a missed launch can never read as the running app.
        return "app" if has_text(app_labels) else "unknown"
    # Legacy rig (no APP_LABELS) keeps the old optimistic default so its existing
    # health checks don't suddenly break.
    return "app"


def start_metro():
    kill_port()
    time.sleep(2)
    log = open(target.METRO_LOG, "w")
    # Project-pinned expo binary — NEVER npx (repo rule: a wrong cwd makes npx
    # silently download an unrelated registry package with the same name).
    expo_bin = os.path.join(REPO, "node_modules", ".bin", "expo")
    p = subprocess.Popen(
        [expo_bin, "start", "--dev-client", "--port", str(target.PORT)],
        cwd=REPO, stdout=log, stderr=log,
        env={**os.environ,
             # Mode env (e.g. EXPO_PUBLIC_MOCK_AUTH=true) — inlined into the JS
             # bundle at Metro transform time; see target.py "Tester mode".
             **getattr(target, "METRO_ENV", {}),
             "EXPO_NO_INSPECTOR": "1", "BROWSER": "/usr/bin/true",
             "REACT_DEBUGGER": "/usr/bin/true"},
        start_new_session=True,
    )
    with open(target.PIDFILE, "w") as f:
        f.write(str(p.pid))
    return p.pid


def _wait_up(seconds=90):
    for _ in range(seconds // 2):
        if metro_ok():
            return True
        time.sleep(2)
    return metro_ok()


def cmd_serve(_):
    pid = start_metro()
    print(f"started Metro pid={pid} port={target.PORT} mode={target.MODE} log={target.METRO_LOG}")
    up = _wait_up()
    print(f"metro: {'UP' if up else 'still starting/down — see log'}")
    # fresh=True: each serve starts a NEW QA session, so reset the crash log to
    # a clean baseline — the health crash-gate then reflects only crashes since
    # THIS serve, not one left over from a prior session's still-live stream.
    print(f"crash-log stream pid={crashlog.start(fresh=True)} -> {target.CRASHLOG}")
    if target.MODE == "mock" and LOCAL_BACKEND_URL and not backend_ok():
        print(f"WARNING: local backend {LOCAL_BACKEND_URL} is DOWN — mock mode needs it: "
              f"`{_BACKEND_HINT}`")
    if up:
        # A foregrounded app may still be running a bundle from ANOTHER Metro
        # (the dev's :8081, or a different tester mode). serve just created a
        # fresh Metro whose env defines the bundle flavor (mock/staging), so
        # ALWAYS force the app to re-fetch from THIS one — `recover` alone
        # would see "app" and skip the deep link.
        print("reloading app from this Metro (cold start pulls the fresh bundle)...")
        reload_app()
        print(f"app state: {app_state()}")
    else:
        sys.exit(1)  # Metro never came up — make it scriptable


def cmd_recover(_):
    if not metro_ok():
        print(f"Metro down -> restarting (scoped to :{target.PORT})...")
        start_metro()
        if not _wait_up():
            print(f"metro: STILL DOWN — see {target.METRO_LOG}")
            sys.exit(1)
        print("metro: UP")
    # Companion BEFORE app_state — the a11y-tree read needs a live idb
    # companion (a prior terminal force-quit can kill it + leave a stale
    # socket, after which all tap/tree calls silently no-op).
    ok, msg = idb_ui.ensure_companion(target.UDID)
    print(f"idb: {msg}" if ok else f"idb: WARNING — {msg}")
    if app_state() != "app":
        print("reloading app via dev-client deep link...")
        common.activate_simulator()
        _open_deeplink()
        time.sleep(10)
    crashlog.start()
    state = app_state()
    print(f"final app state: {state}")
    if state != "app":
        sys.exit(1)  # recovery didn't reach a usable app — make it scriptable


def _approve_openurl_prompt():
    """`simctl openurl` with a custom scheme pops an iOS confirm dialog
    ('Open in "<your app>"?') when invoked from outside the app.
    Tap its Open button when present so recover/reload stay unattended.
    The dialog can take a few seconds to appear — keep polling after a
    no-prompt read; only stop once we've tapped it and it's gone."""
    handled = False
    for i in range(6):
        time.sleep(1.2)
        els = idb_ui.describe(target.UDID)
        prompt = any("open in" in (e.label or "").lower() for e in els)
        if prompt:
            btn = next((e for e in els
                        if e.label == "Open" and "button" in (e.role or "").lower()), None)
            if btn:
                idb_ui.tap_point(target.UDID, btn.cx, btn.cy)
                handled = True
        elif handled:
            return  # prompt appeared, got tapped, and is now gone
        elif i >= 2 and app_state() == "app":
            # The link already opened the app (pre-approved) — done. If the
            # app is NOT foregrounded yet, keep polling the full window so a
            # slow dialog still gets tapped.
            return


def _open_deeplink():
    subprocess.run(["xcrun", "simctl", "openurl", target.UDID, deeplink()], **_QUIET)
    _approve_openurl_prompt()


def reload_app():
    """Load a FRESH bundle WITHOUT restarting Metro: cold-restart the app (terminate)
    then re-open via the dev-client deep link. A plain openurl on a RUNNING app does
    NOT re-fetch the bundle — terminating first makes it a cold start that pulls
    current code from the (warm) Metro."""
    subprocess.run(["xcrun", "simctl", "terminate", target.UDID, target.BUNDLE], **_QUIET)
    time.sleep(1)
    common.activate_simulator()
    _open_deeplink()
    time.sleep(6)


def cmd_reload(_):
    print("reloading app (terminate + dev-client deep link; Metro stays warm)...")
    reload_app()
    print(f"app state: {app_state()}")


def verdict(metro, backend, companion, state, fatal):
    """The health pass/fail decision as ONE pure function (no I/O, no printing):
    green only when every pillar is up, the app is positively frontmost, and no
    fatal crash was captured since serve. `fatal` is a count (0 = none). This is
    the single most safety-critical expression in the engine — keeping it pure
    makes it exhaustively unit-testable without monkeypatching probes or capturing
    stdout, and there's exactly one place the verdict lives."""
    return bool(metro and backend and companion and state == "app" and not fatal)


def cmd_health(_):
    print(f"target: udid={target.UDID[:8]}… port={target.PORT} mode={target.MODE} "
          f"bundle={target.BUNDLE}")
    metro = metro_ok()
    print(f"metro localhost:{target.PORT}: {'UP (200)' if metro else 'DOWN'}")
    backend = True
    if target.MODE == "mock" and LOCAL_BACKEND_URL:
        backend = backend_ok()
        print(f"backend {LOCAL_BACKEND_URL}: "
              + ("UP" if backend else f"DOWN — `{_BACKEND_HINT}`"))
    state = app_state()
    print(f"app state: {state}")
    # idb companion liveness — when DOWN, tap/tree silently no-op (run `recover`).
    # Short timeout: a dead companion must not stall the health gate for 30s.
    companion = idb_ui.companion_alive(target.UDID, timeout=5)
    print(f"idb companion: {'UP' if companion else 'DOWN — run `app-pilot recover`'}")
    # Crash gate: a red-box / native-fatal in the captured crash log means the
    # app is broken even when Metro + companion are up and the tree reads 'app'.
    # Fold it into the verdict so `health` can't report a false PASS on a crashed
    # app (the worst class of failure for the engine that verifies its own fixes).
    # FATAL subset only — softer markers stay advisory via `app-pilot crashes`.
    _, fatal, _ = crashlog.fatal_hits()
    crash_detail = f"{fatal} FATAL hit(s) — see `app-pilot crashes`" if fatal else "none"
    print(f"crashes: {crash_detail}")
    # Non-zero when the verdict is red so skills/scripts can gate on `app-pilot health`.
    if not verdict(metro, backend, companion, state, fatal):
        sys.exit(1)


def cmd_doctor(_):
    """One-shot machine-setup check for new developers — every FAIL prints
    the command that fixes it. Exit 1 if anything required is missing."""
    results = []

    def check(name, ok, fix="", warn=False):
        mark = "PASS" if ok else ("WARN" if warn else "FAIL")
        results.append((mark, name, fix))

    xcrun = shutil.which("xcrun") is not None
    check("xcrun (Xcode CLT)", xcrun, "xcode-select --install")
    sim_known = False
    if xcrun:
        out = subprocess.run(["xcrun", "simctl", "list", "devices"],
                             capture_output=True, text=True, timeout=15).stdout
        sim_known = target.UDID in out
        check(f"simulator {target.UDID[:8]}… ({getattr(target, 'DEVICE_NAME', '?')})",
              sim_known,
              f"delete scripts/app-pilot/target.local to re-resolve, or pin another UDID there")
        if sim_known:
            booted = f"{target.UDID}) (Booted" in out
            check("simulator booted", booted,
                  f"xcrun simctl boot {target.UDID}  (and `open -a Simulator`)", warn=True)
    check("idb client", os.path.exists(target.IDB),
          "python3 -m venv ~/.idb-venv && ~/.idb-venv/bin/pip install fb-idb")
    check("idb_companion", idb_ui._find_companion_binary() is not None,
          "brew tap facebook/fb && brew install idb-companion")
    expo_bin = os.path.join(REPO, "node_modules", ".bin", "expo")
    check("node_modules (expo binary)", os.path.exists(expo_bin), "npm install")
    if xcrun and sim_known:
        app = subprocess.run(
            ["xcrun", "simctl", "get_app_container", target.UDID, target.BUNDLE],
            capture_output=True, text=True, timeout=15)
        check(f"app installed ({target.BUNDLE})", app.returncode == 0,
              f"./node_modules/.bin/expo run:ios --no-bundler --device {target.UDID}")
    if target.MODE == "mock" and LOCAL_BACKEND_URL:
        check(f"local backend ({LOCAL_BACKEND_URL})", backend_ok(),
              _BACKEND_HINT, warn=True)

    width = max(len(n) for _, n, _ in results)
    failed = False
    for mark, name, fix in results:
        line = f"{mark}  {name.ljust(width)}"
        if mark != "PASS" and fix:
            line += f"  -> {fix}"
        if mark == "FAIL":
            failed = True
        print(line)
    print(f"\n{'setup incomplete — fix the FAILs above' if failed else 'machine ready'} "
          f"(mode={target.MODE}, port={target.PORT})")
    sys.exit(1 if failed else 0)


def _pidfile_pid():
    try:
        return int(open(target.PIDFILE).read().strip())
    except Exception:
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    # PID-reuse guard: only treat the pidfile PID as ours while it still looks
    # like the Metro we spawned — otherwise stop() could killpg a stranger.
    return "expo" in cmd or "node" in cmd


def cmd_status(_):
    pid = _pidfile_pid()
    print(f"pidfile {target.PIDFILE}: pid={pid} alive={bool(pid) and _alive(pid)}")
    print(f"holders of port {target.PORT}: {pids_on_port() or 'none'}")
    print(f"metro UP: {metro_ok()}")
    if os.path.exists(target.METRO_LOG):
        print(f"log: {target.METRO_LOG} ({os.path.getsize(target.METRO_LOG)} bytes)")
    cpid, calive, csize = crashlog.status()
    print(f"crash stream: pid={cpid} alive={calive} ({csize} bytes)")
    print("to kill: `scripts/app-pilot/app-pilot stop`  (or `lsof -ti tcp:%d | xargs kill`)" % target.PORT)


def cmd_stop(_):
    pid = _pidfile_pid()
    if pid and _alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    kill_port()  # backstop — scoped to this port only
    if os.path.exists(target.PIDFILE):
        os.remove(target.PIDFILE)
    crashlog.stop()
    time.sleep(1)
    print(f"stopped; holders of port {target.PORT}: {pids_on_port() or 'none'}")


def _tail_lines(path, n, max_bytes=8 * 1024 * 1024):
    """Last n lines of a file, reading at most max_bytes from the end so RAM
    stays bounded even if the file is huge (Metro logs can grow over a long
    session). Mirrors crashlog.hits()'s bounded-tail strategy."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # discard partial line after the seek
        data = fh.read()
    return data.decode(errors="replace").splitlines()[-n:]


def cmd_metrolog(args):
    if not os.path.exists(target.METRO_LOG):
        print(f"no {target.METRO_LOG} — tester doesn't own Metro yet (run `serve`)")
        return
    print("\n".join(_tail_lines(target.METRO_LOG, args.n)))


def cmd_crashes(args):
    if not os.path.exists(target.CRASHLOG):
        print(f"no {target.CRASHLOG} — run `serve`/`recover` to start crash capture")
        return
    last, total, scanned = crashlog.hits(args.n)
    if total == 0:
        print(f"clean — no crash patterns in {scanned} captured log lines")
        return
    print(f"{total} crash-pattern hit(s) in {scanned} lines (last {args.n}):")
    print("\n".join(last))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    sub.add_parser("recover").set_defaults(fn=cmd_recover)
    sub.add_parser("reload").set_defaults(fn=cmd_reload)
    sub.add_parser("health").set_defaults(fn=cmd_health)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    pm = sub.add_parser("metrolog")
    pm.add_argument("n", nargs="?", type=int, default=40)
    pm.set_defaults(fn=cmd_metrolog)
    pc = sub.add_parser("crashes")
    pc.add_argument("n", nargs="?", type=int, default=20)
    pc.set_defaults(fn=cmd_crashes)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
