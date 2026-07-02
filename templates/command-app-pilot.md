---
description: One generic front door for ALL app-pilot missions (bug-hunt, scenario-exec, feature-dev, improvement, …). Reads <harness>/missions/<name>.md and runs it. Copy ONCE per project — replaces the per-mission, per-driver command-file sprawl. claude -p / Remote Control compatible.
argument-hint: <mission> [wake|goal] <request> — e.g. "bug-hunt wake speed for 1h", "feature-dev goal build the X screen per specs/x.md", "improvement report-only top 3"
---

<!--
  WHY THIS FILE: the per-mission shims (e.g. qa-tester.md + qa-tester-wake.md)
  hardcode ONE mission and ONE driver each, so every mission × every driver is a
  separate copy in every project — and they drift. This one launcher reaches
  EVERY mission by name, so adding a mission to the harness needs NO new command
  file here.

  INSTALL (once per project): copy to <project>/.claude/commands/app-pilot.md and
  set ADAPTER_DIR below to this project's app-pilot layer (`scripts/app-pilot/`).
  That single line is the ONLY per-project edit — the engine (mobile vs web) is
  read from the shim, so it needs no separate config.
-->

Run a **app-pilot mission** — the one named in `$ARGUMENTS` — against THIS project.

**Per-project config (the one line to set at install):**
- `ADAPTER_DIR` = `scripts/app-pilot/`   <!-- same for mobile + web; the engine is read from the shim -->

**Steps:**
1. **Parse `$ARGUMENTS`:**
   - **mission** = the first token (e.g. `bug-hunt`, `scenario-exec`, `feature-dev`, `improvement`).
   - **driver** = the next token **iff** it is exactly `wake` or `goal` (else default `wake`); strip it from the request.
   - **request** = the remaining text (scope, bound, constraints) — passed through verbatim.
2. **Resolve the harness** (same chain as the `app-pilot` shim): `$APP_PILOT_HOME` if set
   → else the first line of `~/.app-pilot` → else `~/programming/projects/app-pilot`.
   Call it `<harness>`.
3. **Pick the engine** by reading the shim `<ADAPTER_DIR>/app-pilot`: its `exec`
   line points at `$H/mobile/app-pilot` (→ engine `mobile`) or `$H/web/app-pilot`
   (→ engine `web`). The shim is the source of truth — no per-project engine config.
4. **Verify the mission exists**, then read and execute it: if
   `<harness>/missions/<mission>.md` is missing, list `<harness>/missions/*.md`
   and STOP (don't guess a mission). Otherwise read it and run it with —
   - **driver**: the parsed driver
   - **adapter dir**: `ADAPTER_DIR`
   - **request**: the parsed request
5. **Mission read order:** the mission → `<harness>/<engine>/RUNBOOK.md` (engine
   spine) → `<ADAPTER_DIR>/product/RUNBOOK.md` (product addendum) →
   `<ADAPTER_DIR>/target.py` (pin).

Notes:
- This replaces N missions × 2 drivers of per-project command files with one
  file. Trade-off: the slash-command `description`/`argument-hint` are generic
  rather than mission-specific — worth it for zero drift. A project that wants a
  named shortcut for a hot path (e.g. `/app-pilot`) can still keep a thin
  one-liner that delegates here.
- The mission itself owns bounds, rails, and the driver behavior — this launcher
  only routes `mission + driver + adapter dir + request` to it (the invocation
  contract in `missions/_format.md`).
