#!/usr/bin/env python3
"""Insert or refresh app-pilot's managed AGENTS.md blocks + assert the ios pin.

app-pilot maintains up to two managed blocks in a project's AGENTS.md, each
delimited by BEGIN/END markers and idempotently refreshed from a template:

  app-pilot-rules   QA / visual-evidence conventions (screenshots -> `publish`,
                    never commit). Source: templates/agents-app-pilot-rules.md.
  release-state     the app's compatibility stance, PRE-RELEASE or LIVE, chosen
                    from `RELEASE` in the rig's scripts/app-pilot/target.py
                    (absent = pre-release). Source: templates/agents-release-{pre-release,live}.md.

Re-running REPLACES whatever is between each block's markers with the current
canonical text (idempotent); a block with no markers yet is appended. If there's
no AGENTS.md at all we refuse — make it canonical first (move the rules into
AGENTS.md, set CLAUDE.md to `@AGENTS.md`) so non-Claude tools get the rules too.
A hand-pasted copy of the release rule OUTSIDE the markers is left alone (and
reported) so the managed block never fights an old manual paste.

For MOBILE rigs it also asserts the project's `npm run ios` script pins the
simulator from target.py — `--device $(python3 scripts/app-pilot/target.py
--udid)` — so a fresh rig can't launch a bare `expo run:ios` into the WRONG
sim (lived 2026-07-15). `--fix` rewrites the script in place, preserving any
other flags (`--port`, `--no-build-cache`, ...). Web rigs skip this check.

Usage:
  app-pilot inject-rules [project-dir] [--fix]
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "..", "templates")
RULES_TEMPLATE = os.path.join(TEMPLATES, "agents-app-pilot-rules.md")

RULES_BEGIN, RULES_END = "<!-- BEGIN:app-pilot-rules -->", "<!-- END:app-pilot-rules -->"
RELEASE_BEGIN, RELEASE_END = "<!-- BEGIN:release-state -->", "<!-- END:release-state -->"

MANAGED_NOTE = (
    "<!-- Managed block — source of truth: app-pilot templates/. Don't hand-edit "
    "between the markers; re-sync with `app-pilot inject-rules`. -->"
)

# The device pin every mobile rig's `ios` npm script must carry.
IOS_PIN = "--device $(python3 scripts/app-pilot/target.py --udid)"
IOS_CANONICAL = f"expo run:ios {IOS_PIN}"

# Both release variants open with this heading; a hand-pasted copy of the rule
# outside the markers carries it, ordinary prose never does.
RELEASE_HEADING = "## Release state:"


# ── templates → canonical blocks ────────────────────────────────────────────

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _block_between(text, begin, end):
    """The begin..end block (inclusive) from `text`."""
    i = text.index(begin)
    j = text.index(end) + len(end)
    return text[i:j]


def rules_block():
    return _block_between(_read(RULES_TEMPLATE), RULES_BEGIN, RULES_END)


def release_block(release):
    """The BEGIN..END release-state block for `release` (its own template file)."""
    path = os.path.join(TEMPLATES, f"agents-release-{release}.md")
    if not os.path.isfile(path):
        raise KeyError(f"no release variant {release!r} ({path} missing)")
    return _block_between(_read(path), RELEASE_BEGIN, RELEASE_END)


def upsert_block(content, begin, end, block):
    """Refresh the begin..end block in `content`, or append it if absent.
    Returns (new_content, action) — action in {refreshed, unchanged, inserted}."""
    if begin in content and end in content:
        new = re.sub(
            re.escape(begin) + r".*?" + re.escape(end), lambda _: block,
            content, count=1, flags=re.DOTALL,
        )
        return new, ("refreshed" if new != content else "unchanged")
    tail = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
    return f"{content}{tail}{MANAGED_NOTE}\n{block}\n", "inserted"


# ── rig target.py reads (text-scan only — never exec the pin) ────────────────

def rig_target_path(repo_root):
    return os.path.join(repo_root, "scripts", "app-pilot", "target.py")


RELEASES = ("pre-release", "live")


def read_release(target_text):
    """`RELEASE` from the rig's target.py text; default pre-release when absent.
    A present-but-unrecognized value raises ValueError rather than silently
    falling back to pre-release — a typo must not inject the wrong compat stance
    (e.g. the pre-release 'wipe-and-reinstall' rule into a live app)."""
    m = re.search(r'^\s*RELEASE\s*=\s*["\']([^"\']*)["\']', target_text or "", re.M)
    if not m:
        return "pre-release"
    value = m.group(1)
    if value not in RELEASES:
        raise ValueError(
            f'unrecognized RELEASE {value!r} in target.py — use "pre-release" or "live"'
        )
    return value


def is_mobile_rig(target_text):
    """A mobile rig drives a simulator: it declares DEVICE_NAME / resolves a UDID.
    A web rig (TESTER_PORT + SERVER_CMD, no sim) does neither → skips the ios pin."""
    text = target_text or ""
    return bool(re.search(r"^\s*DEVICE_NAME\s*=", text, re.M) or re.search(r"resolve_udid\s*\(", text))


# ── the ios-pin assertion (shared by inject-rules + `app-pilot doctor`) ───────

def ios_pinned(script):
    """True when the `ios` script pins the sim from target.py (`target.py --udid`)."""
    return bool(script) and re.search(r"target\.py\s+--udid", script) is not None


def pin_ios_script(script):
    """The canonical pinned `ios` script: insert the target.py --udid device pin
    after `run:ios`, preserving other flags and replacing any hardcoded --device."""
    script = (script or "").strip()
    if not script:
        return IOS_CANONICAL
    # Drop any existing --device <token | "quoted" | $(...)> — idempotent, and
    # replaces a hardcoded UDID with the pin.
    stripped = re.sub(
        r"\s*--device\s+(?:\$\([^)]*\)|\"[^\"]*\"|'[^']*'|\S+)", "", script,
    ).strip()
    m = re.search(r"run:ios", stripped)
    if not m:
        return f"{stripped} {IOS_PIN}".strip() if stripped else IOS_CANONICAL
    head, tail = stripped[: m.end()], stripped[m.end():].strip()
    return f"{head} {IOS_PIN}" + (f" {tail}" if tail else "")


def _load_scripts(repo_root):
    """(package.json path, raw text, scripts dict) — scripts None if unreadable."""
    pkg = os.path.join(repo_root, "package.json")
    if not os.path.isfile(pkg):
        return pkg, None, None
    try:
        raw = _read(pkg)
        return pkg, raw, (json.loads(raw).get("scripts") or {})
    except (OSError, json.JSONDecodeError):
        return pkg, None, None


def ios_pin_check(repo_root):
    """For `app-pilot doctor`: (ok, fix_hint). ok is True/False, or None when
    there's nothing to check (no readable package.json)."""
    _, _, scripts = _load_scripts(repo_root)
    if scripts is None:
        return None, ""
    ios = scripts.get("ios")
    if ios_pinned(ios):
        return True, ""
    return False, f'set package.json "scripts.ios" to "{pin_ios_script(ios)}"  (or `app-pilot inject-rules --fix`)'


def check_ios_pin(repo_root, fix=False):
    """For inject-rules: assert (and optionally --fix) the `ios` pin.
    Returns (mark, message): PASS / FAIL / fixed / SKIP."""
    pkg, raw, scripts = _load_scripts(repo_root)
    if scripts is None:
        return "SKIP", "no readable package.json at repo root — cannot check the ios pin"
    ios = scripts.get("ios")
    if ios_pinned(ios):
        return "PASS", "npm run ios pins the sim via target.py --udid"
    fixed = pin_ios_script(ios)
    if not fix:
        return "FAIL", (
            "npm run ios does not pin the sim from target.py — a bare "
            "`expo run:ios` launches the WRONG simulator.\n"
            f'       fix: set package.json "scripts.ios" to "{fixed}"   (or re-run with --fix)'
        )
    _write_ios_script(pkg, raw, fixed)
    return "fixed", f'rewrote package.json "scripts.ios" -> "{fixed}"'


def _write_ios_script(pkg, raw, fixed):
    """Rewrite scripts.ios to `fixed`. In-place string edit when the key exists
    (preserves the file's formatting); a structured rewrite adds a missing key."""
    body = json.dumps(fixed)[1:-1]  # JSON-escaped value, without the surrounding quotes
    pat = re.compile(r'("ios"\s*:\s*")(?:\\.|[^"\\])*(")')
    new, n = pat.subn(lambda m: m.group(1) + body + m.group(2), raw, count=1)
    if not n:  # no ios key yet — add one
        data = json.loads(raw)
        data.setdefault("scripts", {})["ios"] = fixed
        new = json.dumps(data, indent=2) + "\n"
    _write(pkg, new)


def stray_release_note(content):
    """A hand-pasted copy of the release rule OUTSIDE the managed markers → a note.
    Anchored on the block heading (which a real paste always carries and ordinary
    prose never does), so unrelated wording can't trigger a false report."""
    outside = re.sub(
        re.escape(RELEASE_BEGIN) + r".*?" + re.escape(RELEASE_END), "",
        content, flags=re.DOTALL,
    )
    if RELEASE_HEADING in outside:
        return (
            "note: a hand-pasted copy of the release rule appears OUTSIDE the managed "
            "markers — left untouched; delete it so the managed block is the only copy."
        )
    return None


# ── driver ───────────────────────────────────────────────────────────────────

def repo_root(start):
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or start
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start  # not a git repo — operate on the dir as-is


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="app-pilot inject-rules",
        description="Insert/refresh app-pilot's managed AGENTS.md blocks + assert the ios pin.",
    )
    ap.add_argument("project_dir", nargs="?", default=os.getcwd(),
                    help="a dir inside the target repo (default: cwd)")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite package.json's ios script to pin the sim (mobile rigs)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.project_dir):
        sys.exit(f"not a directory: {args.project_dir}")
    root = repo_root(args.project_dir)
    agents = os.path.join(root, "AGENTS.md")
    if not os.path.isfile(agents):
        sys.exit(
            f"no AGENTS.md at {agents}\n"
            "Make AGENTS.md canonical first: move the rules into AGENTS.md and "
            "set CLAUDE.md to `@AGENTS.md`, then re-run."
        )

    tpath = rig_target_path(root)
    target_text = _read(tpath) if os.path.isfile(tpath) else ""
    try:
        release = read_release(target_text)
    except ValueError as e:
        sys.exit(str(e))
    mobile = is_mobile_rig(target_text)

    content = original = _read(agents)
    content, a1 = upsert_block(content, RULES_BEGIN, RULES_END, rules_block())
    content, a2 = upsert_block(content, RELEASE_BEGIN, RELEASE_END, release_block(release))
    if content != original:
        _write(agents, content)

    print(f"app-pilot-rules block: {a1}")
    print(f"release-state block: {a2} (RELEASE={release})")
    note = stray_release_note(content)
    if note:
        print(note)

    failed = False
    if mobile:
        mark, msg = check_ios_pin(root, fix=args.fix)
        print(f"[{mark}] ios pin: {msg}")
        failed = mark == "FAIL"
    else:
        print("ios pin: skipped (web rig — no simulator to pin)")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
