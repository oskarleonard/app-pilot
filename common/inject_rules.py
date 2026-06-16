#!/usr/bin/env python3
"""Insert or refresh the `app-pilot-rules` block in a project's AGENTS.md.

The block (QA / visual-evidence conventions — screenshots → `publish`, never
commit) has ONE source of truth: templates/agents-app-pilot-rules.md. This keeps
every project's copy in sync: re-running REPLACES whatever is between the
BEGIN/END markers with the current canonical block (idempotent). If AGENTS.md has
no block yet, the block is appended. If there's no AGENTS.md at all we refuse —
make it canonical first (move the rules into AGENTS.md, set CLAUDE.md to
`@AGENTS.md`) so non-Claude tools get the rules too.

Usage:
  app-pilot inject-rules [project-dir]   # default: the repo containing cwd
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "templates", "agents-app-pilot-rules.md")
BEGIN = "<!-- BEGIN:app-pilot-rules -->"
END = "<!-- END:app-pilot-rules -->"
MANAGED_NOTE = (
    "<!-- Managed block — source of truth: app-pilot "
    "templates/agents-app-pilot-rules.md. Don't hand-edit between the markers; "
    "re-sync with `app-pilot inject-rules`. -->"
)


def canonical_block():
    """The BEGIN…END block from the template (its comment header is dropped)."""
    text = open(TEMPLATE, encoding="utf-8").read()
    i = text.index(BEGIN)
    j = text.index(END) + len(END)
    return text[i:j]


def repo_root(start):
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or start
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start  # not a git repo — operate on the dir as-is


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(start):
        sys.exit(f"not a directory: {start}")
    agents = os.path.join(repo_root(start), "AGENTS.md")
    if not os.path.isfile(agents):
        sys.exit(
            f"no AGENTS.md at {agents}\n"
            "Make AGENTS.md canonical first: move the rules into AGENTS.md and "
            "set CLAUDE.md to `@AGENTS.md`, then re-run."
        )

    block = canonical_block()
    content = open(agents, encoding="utf-8").read()

    if BEGIN in content and END in content:
        new = re.sub(
            re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block,
            content, count=1, flags=re.DOTALL,
        )
        action = "refreshed"
    else:
        tail = "" if content.endswith("\n\n") else (
            "\n" if content.endswith("\n") else "\n\n"
        )
        new = f"{content}{tail}{MANAGED_NOTE}\n{block}\n"
        action = "inserted"

    if new == content:
        print(f"already up to date — {agents}")
        return
    open(agents, "w", encoding="utf-8").write(new)
    print(f"{action} app-pilot-rules block in {agents}")


if __name__ == "__main__":
    main()
