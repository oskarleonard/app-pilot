#!/usr/bin/env python3
"""Web QA tester's dev-server manager — PINNED to target.TESTER_PORT. [DEV TOOL]

Owns exactly one dev server (the tester's — Next, Vite, ...; see
target.SERVER_CMD), spawned with the env for the active mode. Never kills a
server on another port, so your own dev server coexists.

Subcommands:
  serve         (re)start the tester's server (kills ONLY :TESTER_PORT first)
  health        server HTTP + backend (local mode) + mode
  status        pid, port holders, log size
  stop          kill the tester's server (this pid/port only)
  logs [N]      last N lines of the server log (compile errors, API proxy noise)
"""
import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import target  # noqa: E402


def _find_repo():
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

# How to launch the project's dev server (override per project in target.py):
#   SERVER_CMD — argv list, default ["bun", "run", "dev"]
#   SERVER_CWD — subdir of the repo root to launch from, default the root
_SERVER_CMD = getattr(target, "SERVER_CMD", ["bun", "run", "dev"])
_SERVER_CWD = os.path.normpath(os.path.join(REPO, getattr(target, "SERVER_CWD", "")))


def pids_on_port():
    out = subprocess.run(["lsof", "-ti", f"tcp:{target.TESTER_PORT}"],
                         capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if p.strip().isdigit()]


def kill_port():
    for pid in pids_on_port():
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass


def server_ok():
    try:
        with urllib.request.urlopen(target.APP_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


_BACKEND_URL = getattr(target, "BACKEND_URL", None)  # ground-truth API; None = project has no backend
_BACKEND_HINT = getattr(target, "BACKEND_HINT", "start your local backend")


def backend_ok():
    if not _BACKEND_URL:
        return True
    try:
        urllib.request.urlopen(_BACKEND_URL, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def start_server():
    kill_port()
    time.sleep(1)
    log = open(target.SERVER_LOG, "w")
    p = subprocess.Popen(
        _SERVER_CMD,
        cwd=_SERVER_CWD,
        stdout=log, stderr=log,
        env={**os.environ, **target.MODE_ENV, "PORT": str(target.TESTER_PORT)},
        start_new_session=True,
    )
    with open(target.PIDFILE, "w") as fh:
        fh.write(str(p.pid))
    return p.pid


def _wait_up(seconds=90):
    # Next dev compiles lazily; the first request triggers the page build.
    for _ in range(seconds // 2):
        if server_ok():
            return True
        time.sleep(2)
    return server_ok()


def cmd_serve(_):
    pid = start_server()
    print(f"started dev server pid={pid} url={target.APP_URL} mode={target.MODE} "
          f"log={target.SERVER_LOG}")
    up = _wait_up()
    print(f"server: {'UP' if up else 'still starting/down — see log'}")
    if target.MODE == "local" and _BACKEND_URL and not backend_ok():
        print(f"WARNING: local backend {_BACKEND_URL} is DOWN — local mode "
              f"needs it: `{_BACKEND_HINT}`")
    if not up:
        sys.exit(1)


def cmd_health(_):
    print(f"target: {target.APP_URL} mode={target.MODE}")
    server = server_ok()
    print(f"server: {'UP (200)' if server else 'DOWN — run `app-pilot serve`'}")
    backend = True
    if target.MODE == "local" and _BACKEND_URL:
        backend = backend_ok()
        print(f"backend {_BACKEND_URL}: "
              + ("UP" if backend else f"DOWN — `{_BACKEND_HINT}`"))
    if not (server and backend):
        sys.exit(1)


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
    # like the dev server we spawned.
    return "bun" in cmd or "node" in cmd or "next" in cmd


def cmd_status(_):
    pid = _pidfile_pid()
    print(f"pidfile {target.PIDFILE}: pid={pid} alive={bool(pid) and _alive(pid)}")
    print(f"holders of port {target.TESTER_PORT}: {pids_on_port() or 'none'}")
    print(f"server UP: {server_ok()}")
    if os.path.exists(target.SERVER_LOG):
        print(f"log: {target.SERVER_LOG} ({os.path.getsize(target.SERVER_LOG)} bytes)")


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
    kill_port()
    if os.path.exists(target.PIDFILE):
        os.remove(target.PIDFILE)
    time.sleep(1)
    print(f"stopped; holders of port {target.TESTER_PORT}: {pids_on_port() or 'none'}")


def _tail_lines(path, n, max_bytes=8 * 1024 * 1024):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()
        data = fh.read()
    return data.decode(errors="replace").splitlines()[-n:]


def cmd_logs(args):
    if not os.path.exists(target.SERVER_LOG):
        print(f"no {target.SERVER_LOG} — tester doesn't own a server yet (run `serve`)")
        return
    print("\n".join(_tail_lines(target.SERVER_LOG, args.n)))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    sub.add_parser("health").set_defaults(fn=cmd_health)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    pl = sub.add_parser("logs")
    pl.add_argument("n", nargs="?", type=int, default=40)
    pl.set_defaults(fn=cmd_logs)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
