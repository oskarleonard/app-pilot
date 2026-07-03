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
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import target  # noqa: E402

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


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--scope", required=True,
                    help="all|home|send|transactions|contacts|notifications|settings|workspace")
    pi.add_argument("--label", default=None)
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
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
