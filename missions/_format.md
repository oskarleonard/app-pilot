# missions/ — the format

A **mission** is a markdown brief the agent reads and follows: one job
description running on the shared engine ("hands and eyes"). The engine
RUNBOOK says HOW to operate the app; the project's `product/RUNBOOK.md` says
what's TRUE for this app; the mission says WHAT TO DO and when it's done.
Missions version with the engine — same repo, same reason the RUNBOOK does.

## Invocation contract

Missions are launched by a ~10-line **shim** in each project's
`.claude/commands/` (or any prompt that supplies the same three things):

- **driver** — `wake` (ScheduleWakeup self-pacing) or `goal` (/goal Stop-hook
  pacing). Missions define behavior per driver; shims hardcode one each.
- **adapter dir** — the project's qa layer (`scripts/sim-qa` or `scripts/qa`):
  `target.py` (pin) · `product/` (truth, rails, registries) · `ext/` ·
  `runs/`. Every project-specific fact the mission needs resolves here.
- **request** — the user's free-text arguments (`$ARGUMENTS`).

Read order at launch: this mission → the engine RUNBOOK
(`<harness>/{mobile,web}/RUNBOOK.md`) → the adapter's `product/RUNBOOK.md` →
`target.py`.

## Schema — every mission has exactly these sections

| Section | Contract |
|---|---|
| **Goal** | One paragraph: the job and its deliverable. |
| **Input source** | What the mission consumes — ALWAYS parameters supplied by the invoker/adapter, never hardcoded. A corpus path, a backlog file, a scenario id. External trackers (Linear, Notion, GitHub issues) never appear in a mission — an adapter may feed from them and hand the mission a local file/path. |
| **Done-criteria** | The exact conditions that end the run (the completion sentinel, bounds, per-item verdicts). Never open-ended. |
| **Rails** | The mission's non-negotiables, layered ON TOP of the engine RUNBOOK's HARD RULES and the adapter's product rails — a mission may tighten rails, never loosen them. |
| **Options** | Named flags with defaults. Options are **generic hooks**: the flag's meaning is defined here; its implementation is the adapter's (e.g. `check_figma: on` means "run the adapter's figma-check procedure if it defines one; absent → log a notice and continue"). |

Optional extra sections (after the schema ones): **Procedure** (numbered
steps), **Driver: wake / Driver: goal** (pacing specifics), **Watchdog**.

## Rules

- Missions are product-agnostic — this repo is public. The litmus test from
  the README applies to every line.
- A mission must survive context compaction: durable state lives in the run
  journal (`runs/<id>/journal.md`), re-read every iteration.
- Bounded always: every mission derives a deadline and/or an item cap from
  its inputs, with a default. Never unbounded.
- **Code-producing missions MUST include the pre-PR quality gate** in their
  finish steps: run `/simplify` then `/code-review` over the branch diff,
  apply high-confidence findings, re-verify + static checks, THEN open the
  PR (one gate pass, no looping). bug-hunt §4 is the reference wording —
  copy it into any new mission that commits code.

## Current missions

Distinguished by what decides the work and what the engine is FOR:

- `bug-hunt.md` — **explore** the running app to DISCOVER unknown bugs;
  (optionally) fix the clear ones → PR. The original QA-tester loop; the engine
  is the eyes that find defects.
- `scenario-exec.md` — **regression-verify** a predefined scenario corpus; one
  verdict per scenario; write the run log back. No code changes; the corpus
  decides what, the engine drives it.
- `feature-dev.md` — **build** ONE feature from a spec; prove each acceptance
  criterion live (the engine is the proof gate) → PR. Code-producing.
- `improvement.md` — **triage + work** a KNOWN backlog of non-bug improvements
  (paper cuts, tech debt, perf, a11y); do the safe ones behavior-preserving,
  defer every owner-decision → PR. Code-producing.
