#!/usr/bin/env python3
"""Web QA tester — run bookkeeping + archival screenshots. [DEV TOOL]

The agent's live eyes/hands are the Playwright MCP (browser_navigate /
browser_click / browser_snapshot / browser_console_messages / ...). This
script provides what the MCP doesn't:

  - a versioned run folder (journal/findings/actions) so long unattended runs
    are auditable and survive context compaction
  - `shot`: an archival full-page screenshot of any app PATH into the run
    folder, via the Playwright CLI in a fresh browser context. Because mock
    modes need no login, app states are URL-addressable — `app-pilot shot home /`
    captures the same screen a teammate would see. (In staging mode a fresh
    context only sees the login page; use the MCP's in-session screenshot
    instead.)

Subcommands (operate on the "current" run unless --run given):
  init  --scope <all|home|send|transactions|...> [--driver wake|goal] [--label L]
  shot  <label> [path]           full-page screenshot of APP_URL+path (default /)
  note  <text...>                append a finding to findings.md
  act   <text...>                append a line to actions.log
  close --status done|failed|abandoned [--verdict pass|fail|mixed] [--findings J]
        [--gate PASS|PASS_WITH_EXCEPTIONS|INCOMPLETE] [--gate-reason T]...
        [--oracle-questions J] [--insufficient-evidence J]
                                 settle run.json (machine record; the closing step —
                                 it owns run.json and its own audit lines)
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import target  # noqa: E402

# The shared engine's common/runlog.py, loaded by explicit path — never via
# sys.path, where a project-dir module named `runlog` (earlier in the path)
# would silently shadow it.
# Guarded: a broken/partial engine checkout must not take down shot/tap/note
# — subcommands that never touch the machine record. close fails loud instead.
import importlib.util as _importlib_util  # noqa: E402

try:
    _runlog_spec = _importlib_util.spec_from_file_location(
        "app_pilot_runlog",
        os.path.join(os.path.dirname(os.path.dirname(HERE)), "common", "runlog.py"),
    )
    runlog = _importlib_util.module_from_spec(_runlog_spec)
    _runlog_spec.loader.exec_module(runlog)
except Exception as _runlog_err:  # noqa: BLE001
    print(f"app-pilot: runlog unavailable ({_runlog_err}) — machine records disabled",
          file=sys.stderr)
    runlog = None

RUNS = os.path.join(os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE), "runs")
CURRENT = os.path.join(RUNS, ".current")


def _playwright_bin():
    d = os.environ.get("APP_PILOT_PROJECT_DIR") or HERE
    for _ in range(6):
        for candidate in (
            os.path.join(d, "node_modules", ".bin", "playwright"),
            os.path.join(d, "apps", "web", "node_modules", ".bin", "playwright"),
        ):
            if os.path.exists(candidate):
                return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    sys.exit("playwright CLI not found — run `bun install` at the repo root")


def _now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _run_dir(args):
    if getattr(args, "run", None):
        return args.run
    if os.path.exists(CURRENT):
        run = open(CURRENT).read().strip()
        if not os.path.isdir(run):
            sys.exit(f"current run dir is gone ({run}) — run `app-pilot init` again")
        return run
    sys.exit("no current run — run `app-pilot init --scope ...` first")


def _log(run, fname, text):
    with open(os.path.join(run, fname), "a") as fh:
        fh.write(f"{_now()}  {text}\n")


def _safe_part(value):
    """Collapse anything outside [A-Za-z0-9._-] to '-': scope/label/shot names
    flow into directory + file paths, so a value carrying separators ('../',
    '/') must not be able to escape the run tree."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "x"


def _rig_id():
    """The rig's identity string — consumers key on it, nothing here does.
    Resolution: APP_PILOT_RIG env -> gitignored rig.pin.local -> committed
    rig.pin (one line beside target.py) -> the derived default: the dir above
    scripts/app-pilot. The pins exist for monorepos, where the derived name
    degenerates to the surface dir (every repo's web surface would be "web")."""
    adapter = os.path.dirname(RUNS)
    pinned = os.environ.get("APP_PILOT_RIG", "").strip()
    if not pinned:
        for name in ("rig.pin.local", "rig.pin"):
            try:
                with open(os.path.join(adapter, name)) as f:
                    pinned = f.read().strip()
            except OSError:
                continue
            if pinned:
                break
    if pinned:
        return _safe_part(pinned)
    return os.path.basename(os.path.abspath(os.path.join(adapter, "..", "..")))


def cmd_init(args):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    scope = _safe_part(args.scope)
    label = args.label and _safe_part(args.label)
    if args.driver and label:
        if not label.startswith(f"{args.driver}-"):
            label = f"{args.driver}-{label}"
    elif args.driver and not label:
        label = args.driver
    rid = f"{stamp}__{scope}" + (f"__{label}" if label else "")
    run = os.path.join(RUNS, rid)
    os.makedirs(os.path.join(run, "screenshots"), exist_ok=True)
    with open(os.path.join(run, "journal.md"), "w") as fh:
        fh.write(
            f"# QA run: {rid}\n\n"
            f"- Scope: **{args.scope}**\n"
            f"- Mode: **{target.MODE}**\n"
            f"- App: {target.APP_URL}\n"
            f"- Started: {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n"
            "## Goal\nExplore the in-scope screens/flows and flag visual + logic bugs.\n\n"
            "## Nav map (routes + selectors learned)\n\n"
            "## Tested\n\n## Open questions\n\n"
            "## Next steps\n- Begin: open the app via the Playwright MCP, orient.\n"
        )
    with open(os.path.join(run, "findings.md"), "w") as fh:
        fh.write(
            f"# Findings — {rid}\n\n_Format: `[severity] screen — observation (evidence)`_\n\n"
        )
    with open(os.path.join(run, "actions.log"), "w") as fh:
        fh.write(f"# Actions — {rid}\n")
    with open(CURRENT, "w") as fh:
        fh.write(run)
    # Machine record beside the markdown: run.json opens here (harness-stamped
    # — a mission can forget a step; init can't) and closes via `close`.
    # AFTER .current: if the stamp fails, evidence still routes to THIS dir
    # (adopted as a partial row) instead of silently landing in the previous run.
    # Guarded: bookkeeping must never kill the run — callers do
    # RUN=$(app-pilot init …) and need the dir on stdout regardless.
    try:
        if runlog is None:
            raise RuntimeError("runlog module unavailable")
        runlog.open_run(run, rig=_rig_id(), scope=scope, goal=label or scope,
                        target=args.target, env=getattr(target, "MODE", None))
    except Exception as err:  # noqa: BLE001
        print(f"app-pilot init: run.json stamp failed ({err}) — continuing; "
              "dashboards adopt this dir as a partial row", file=sys.stderr)
    print(run)


def cmd_shot(args):
    run = _run_dir(args)
    sdir = os.path.join(run, "screenshots")
    nums = [int(f.split("_", 1)[0]) for f in os.listdir(sdir)
            if f.endswith(".png") and f.split("_", 1)[0].isdigit()]
    seq = max(nums) + 1 if nums else 0
    out = os.path.join(sdir, f"{seq:04d}_{_safe_part(args.label)}.png")
    url = args.path if args.path.startswith("http") else target.APP_URL + args.path
    result = subprocess.run(
        [_playwright_bin(), "screenshot", "--full-page",
         "--viewport-size", "1440,900", "--wait-for-timeout", "2500", url, out],
        capture_output=True, text=True, timeout=90,
    )
    if result.returncode != 0 or not os.path.exists(out):
        sys.exit(f"screenshot failed: {result.stderr.strip()[:300]}")
    _log(run, "actions.log", f"SHOT {os.path.basename(out)} url={url}")
    print(out)


def cmd_note(args):
    _log(_run_dir(args), "findings.md", "- " + " ".join(args.text))
    print("noted")


def cmd_act(args):
    _log(_run_dir(args), "actions.log", " ".join(args.text))
    print("logged")


def cmd_close(args):
    if runlog is None:
        sys.exit("app-pilot close: runlog module unavailable — cannot settle run.json")
    run = _run_dir(args)
    findings = runlog.load_findings(args.findings) if args.findings else None
    extra = runlog.gate_kwargs(args)
    # Two-phase audit: an attempt line before (so a failed close is visible),
    # a settled line after (so the log never asserts a close that didn't land).
    _log(run, "actions.log", f"CLOSE attempt status={args.status}"
         + (f" verdict={args.verdict}" if args.verdict else "")
         + (f" gate={args.gate}" if args.gate else ""))
    record = runlog.close_run(run, args.status, args.verdict, findings, args.cost_usd,
                              **extra)
    _log(run, "actions.log", f"CLOSE settled status={record['status']}")
    # The run is settled — drop the .current pointer so a stray follow-up
    # note/shot can't write into a closed run dir (the next init re-points it).
    if not getattr(args, "run", None):
        try:
            os.unlink(CURRENT)
        except OSError:
            pass
    print(json.dumps(record, indent=2, sort_keys=True))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--scope", required=True,
                    help="all|home|send|transactions|contacts|notifications|settings|workspace")
    pi.add_argument("--label", default=None)
    pi.add_argument("--target", default=None,
                    help="what the run is against (repo#N or a ticket id) — stamped into run.json")
    pi.add_argument("--driver", choices=["wake", "goal"], default=None)
    pi.set_defaults(fn=cmd_init)
    ps = sub.add_parser("shot")
    ps.add_argument("label")
    ps.add_argument("path", nargs="?", default="/",
                    help="app path (e.g. /transactions) or full URL")
    ps.add_argument("--run", default=None)
    ps.set_defaults(fn=cmd_shot)
    pn = sub.add_parser("note")
    pn.add_argument("text", nargs="+")
    pn.add_argument("--run", default=None)
    pn.set_defaults(fn=cmd_note)
    pa = sub.add_parser("act")
    pa.add_argument("text", nargs="+")
    pa.add_argument("--run", default=None)
    pa.set_defaults(fn=cmd_act)
    pc = sub.add_parser("close", help="settle run.json as the run's last step")
    pc.add_argument("--status", required=True, choices=list(runlog.CLOSE_STATUSES))
    pc.add_argument("--verdict", choices=list(runlog.VERDICTS), default=None)
    runlog.add_gate_args(pc)
    pc.add_argument("--findings", default=None,
                    help="path to a JSON array of findings (shape: common/runlog.py)")
    pc.add_argument("--cost-usd", type=float, dest="cost_usd", default=None)
    pc.add_argument("--run", default=None)
    pc.set_defaults(fn=cmd_close)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
