#!/usr/bin/env python3
"""
app-pilot (mobile) — autonomous QA-loop tooling for an iOS simulator app.  [DEV TOOL]

The *mechanical + bookkeeping* layer for a model-driven QA loop. Creates a
versioned run folder, drives the sim (screenshot/tap), and logs every action so
a long unattended run is fully auditable and survives context compaction (the
live state lives in runs/<id>/journal.md, re-read each loop iteration).

Architecture (hybrid):
  - This script  = deterministic mechanics + logging (cheap, no model).
  - The model    = decides what to test next, VIEWS select screenshots to judge
                   bugs, writes findings, updates the journal — paced by a
                   self-scheduling loop (ScheduleWakeup) or /goal.

Per-run data is isolated under runs/<timestamp>__<scope>[__label]/ so a new run
never clobbers old data. Reuses common.py for primitives (sibling module).

Subcommands (operate on the "current" run unless --run given):
  init  --scope <all|home|send|transactions|...> [--driver wake|goal] [--label L]
  shot  <label>                  screenshot -> screenshots/, logs, prints center RGB
  tree                           dump labelled a11y elements (idb) — what's tappable
  tap   (--label "AXLabel" [--role Button] | --tab home|notifications | --frac fx,fy) [--note T]
  type  <text> [--label L] [--role R] [--clear] [--enter]   type into a (focused) field
  note  <text...>                append a finding to findings.md
  act   <text...>                append a line to actions.log

Tapping prefers idb (accessibility-label / tab-segment / fraction, via idb_ui).
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # for sibling core modules (common, idb_ui)
# target.py lives one level up (project/core boundary).
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE))
import common  # noqa: E402
import idb_ui  # noqa: E402
import target  # noqa: E402

# Run output lives at scripts/app-pilot/runs/ (NOT core/runs/ — an earlier version
# anchored to core/ by accident and grew two runs dirs).
RUNS = os.path.join(os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(HERE), "runs")
CURRENT = os.path.join(RUNS, ".current")


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
    # If a driver was given (wake|goal), auto-prefix the label so the resulting
    # run dir self-identifies: `<auto-ts>__<scope>__<driver>-<label>`. Lets
    # `ls runs/ | grep __wake-` / `__goal-` separate the two skills' histories.
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
            f"- Started: {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n"
            "## Goal\nExplore the in-scope screens/flows and flag visual + logic bugs.\n\n"
            "## Nav map (labels learned)\n_(a11y labels / tab segments that worked)_\n\n"
            "## Tested\n\n## Open questions\n\n"
            "## Next steps\n- Begin: capture current screen, orient.\n"
        )
    open(os.path.join(run, "findings.md"), "w").write(
        f"# Findings — {rid}\n\n_Format: `[severity] screen — observation (screenshot)`_\n\n"
    )
    open(os.path.join(run, "actions.log"), "w").write(f"# Actions — {rid}\n")
    open(CURRENT, "w").write(run)
    print(run)


def cmd_shot(args):
    run = _run_dir(args)
    sdir = os.path.join(run, "screenshots")
    # max+1, not count — count-based numbering collides after a deletion.
    nums = [int(f.split("_", 1)[0]) for f in os.listdir(sdir)
            if f.endswith(".png") and f.split("_", 1)[0].isdigit()]
    seq = max(nums) + 1 if nums else 0
    path = os.path.join(sdir, f"{seq:04d}_{_safe_part(args.label)}.png")
    common.screenshot(path, target.UDID)
    crop = path + ".c.png"
    common.center_crop(path, crop)
    r, g, b = common.avg_rgb(crop)
    os.remove(crop)
    # Downscale in place: the model API rejects images >2000px on any side
    # once a conversation carries many images, and ONE oversized shot poisons
    # every later image read in that conversation (including already-sent
    # ones). 1800px keeps UI text readable. Raw full-res when needed:
    # `simctl io screenshot`.
    subprocess.run(["sips", "-Z", "1800", path], capture_output=True, timeout=30)
    _log(run, "actions.log", f"SHOT {os.path.basename(path)} center_rgb=({r},{g},{b})")
    print(f"{path}  center_rgb=({r},{g},{b})")


def cmd_tree(args):
    for e in idb_ui.labelled(target.UDID):
        print(e)


def _tap_blocker(el):
    """Why a tap at this element's center would NOT reach it (None if clear).

    a11y frames include off-viewport scroll content (y<0 = scrolled past,
    y>screen = below the fold), and the floating Tab Bar's native view spans
    the full width of its band and swallows taps on anything underneath —
    both verified live (two Retry taps silently hit the bar / dead space)."""
    w, h = idb_ui.screen_size(target.UDID)
    if el.cy < 0 or el.cy > h or el.cx < 0 or el.cx > w:
        return f"center ({el.cx:.0f},{el.cy:.0f}) is off-viewport ({w}x{h})"
    bar = idb_ui.find(target.UDID, "Tab Bar", role="Group")
    if bar and bar.frame and bar.label != el.label:
        f = bar.frame
        if (f.get("y", 0) <= el.cy <= f.get("y", 0) + f.get("height", 0)
                and f.get("x", 0) <= el.cx <= f.get("x", 0) + f.get("width", 0)):
            return f"center ({el.cx:.0f},{el.cy:.0f}) is under the Tab Bar overlay"
    return None


def cmd_tap(args):
    run = _run_dir(args)
    note = f" [{args.note}]" if args.note else ""
    if args.tab:
        ok = idb_ui.tap_tab(target.UDID, args.tab)
        _log(run, "actions.log", f"TAP tab={args.tab} ok={ok}{note}")
        print(f"tab {args.tab} -> {ok}")
        if not ok:
            sys.exit(f"'{args.tab}' tab not tapped — unknown tab, not on screen, or "
                     "idb delivery failed (check target.TAB_ORDER / `app-pilot tree` / stderr)")
    elif args.label:
        el = idb_ui.find(target.UDID, args.label, role=args.role)
        if el is None:
            _log(run, "actions.log", f"TAP label={args.label!r} -> None{note}")
            sys.exit(f"no element labelled {args.label!r} (try `app-pilot tree`)")
        blocker = None if args.force else _tap_blocker(el)
        if blocker:
            _log(run, "actions.log", f"TAP label={args.label!r} REFUSED: {blocker}{note}")
            sys.exit(f"refusing to tap {args.label!r}: {blocker} — "
                     "`app-pilot scroll` first, or pass --force")
        # tap_point returns False when idb could not deliver (dead/hung
        # companion) — a lost tap logged as success would corrupt the audit
        # trail the whole loop replays from, so fail loud like `type` does.
        if not idb_ui.tap_point(target.UDID, el.cx, el.cy):
            _log(run, "actions.log", f"TAP label={args.label!r} DELIVERY FAILED{note}")
            sys.exit("idb failed to deliver the tap — check `app-pilot health` (idb companion?)")
        _log(run, "actions.log", f"TAP label={args.label!r} -> {el}{note}")
        print(f"tapped label {args.label!r} -> {el}")
    elif args.frac:
        fx, fy = (float(v) for v in args.frac.split(","))
        if not idb_ui.tap_frac(target.UDID, fx, fy):
            _log(run, "actions.log", f"TAP frac={fx},{fy} DELIVERY FAILED{note}")
            sys.exit("idb failed to deliver the tap — check `app-pilot health` (idb companion?)")
        _log(run, "actions.log", f"TAP frac={fx},{fy}{note}")
        print(f"tapped frac {fx},{fy}")
    else:
        sys.exit("tap needs --label, --tab, or --frac")


def cmd_scroll(args):
    run = _run_dir(args)
    direction = args.direction or "down"
    idb_ui.scroll(target.UDID, direction, args.amount)
    _log(run, "actions.log", f"SCROLL {direction} amount={args.amount}")
    print(f"scrolled {direction} (amount={args.amount})")


# Backspaces sent by `--clear`. Bounded (idb has no select-all); covers any
# realistic field (amounts, notes, IBANs) and surplus presses no-op on a short
# field. A field longer than this would clear only partially.
_CLEAR_BACKSPACES = 40


def cmd_type(args):
    run = _run_dir(args)
    note = f" [{args.note}]" if args.note else ""
    # Optionally focus a field first; otherwise type into whatever is focused.
    if args.label:
        el = idb_ui.tap_label(target.UDID, args.label, role=args.role)
        if el is None:
            _log(run, "actions.log", f"TYPE focus={args.label!r} -> None{note}")
            sys.exit(f"no element labelled {args.label!r} to focus (try `app-pilot tree`)")
        time.sleep(0.4)  # let the keyboard animate up before sending keys
    if args.clear:
        idb_ui.press_key(target.UDID, 42, times=_CLEAR_BACKSPACES)  # 42 = backspace
    failed = idb_ui.type_text(target.UDID, args.text)
    if args.enter:
        idb_ui.press_key(target.UDID, 40)  # 40 = return
    into = f" into {args.label!r}" if args.label else ""
    cleared = " (cleared)" if args.clear else ""
    if failed:
        _log(run, "actions.log", f"TYPE {args.text!r}{into} -> {failed} char(s) FAILED{note}")
        sys.exit(f"idb failed to deliver {failed}/{len(args.text)} char(s) — "
                 "check `app-pilot health` (idb companion?)")
    _log(run, "actions.log", f"TYPE {args.text!r}{into}{cleared}{note}")
    print(f"typed {args.text!r}{into}{cleared}")


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
    pi.add_argument(
        "--driver",
        choices=["wake", "goal"],
        default=None,
        help="prefix the label with the loop driver name so runs self-identify "
        "(e.g. --driver wake --label <stamp> → runs/<ts>__<scope>__wake-<stamp>)",
    )
    pi.set_defaults(fn=cmd_init)
    ps = sub.add_parser("shot")
    ps.add_argument("label")
    ps.add_argument("--run", default=None)
    ps.set_defaults(fn=cmd_shot)
    sub.add_parser("tree").set_defaults(fn=cmd_tree)
    pt = sub.add_parser("tap")
    pt.add_argument("--label", default=None, help="accessibility label to tap")
    pt.add_argument("--tab", default=None, help="bottom tab name (home/notifications)")
    pt.add_argument("--frac", default=None, help="fraction fx,fy fallback (via idb)")
    pt.add_argument("--role", default=None,
                    help="role filter (e.g. Button) — disambiguates label collisions")
    pt.add_argument("--note", default=None, help="optional annotation for the log")
    pt.add_argument("--force", action="store_true",
                    help="tap even if the target is off-viewport / under the Tab Bar")
    pt.add_argument("--run", default=None)
    pt.set_defaults(fn=cmd_tap)
    psc = sub.add_parser("scroll")
    psc.add_argument("direction", nargs="?", default="down", choices=["down", "up"])
    psc.add_argument("--amount", type=float, default=0.35,
                     help="fraction of screen height to traverse")
    psc.add_argument("--run", default=None)
    psc.set_defaults(fn=cmd_scroll)
    py = sub.add_parser("type")
    py.add_argument("text", help="text to type into the focused field")
    py.add_argument("--label", default=None,
                    help="tap this field first to focus it before typing")
    py.add_argument("--role", default=None, help="role filter for --label")
    py.add_argument("--clear", action="store_true",
                    help="clear the field (backspaces) before typing")
    py.add_argument("--enter", action="store_true", help="press Return after typing")
    py.add_argument("--note", default=None)
    py.add_argument("--run", default=None)
    py.set_defaults(fn=cmd_type)
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
