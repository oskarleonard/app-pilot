# Mission: scenario-exec

## Goal
Execute a corpus of predefined QA scenarios (steps → expected results)
against the project's pinned tester and produce an **execution log**: one
verdict per scenario — PASS / FAIL / SKIPPED — with evidence and notes,
written back where the corpus keeps its run logs. This is regression
verification, not exploration: the corpus decides WHAT to test; the engine
decides HOW to drive the app.

## Input source
All parameters — supplied by the invoker (a thin per-corpus file that fills
them; nothing here is hardcoded):

| Parameter | Meaning |
|---|---|
| `corpus_dir` | Where scenario files live (markdown). |
| `selection` | Which scenarios to run: a file, an ID/glob, a release checklist, or "all". |
| `automatable_marker` | The metadata field + values that gate execution (e.g. `Automatable: yes` = run fully; `partial` = run the automatable steps, mark the rest SKIPPED(manual); `no` = SKIPPED). |
| `platform_field` | The metadata field that routes a scenario to a rig (e.g. `Platforms: web, mobile`) + the invoker's platform→adapter-dir map. This session executes scenarios for ONE adapter; others are SKIPPED(other-platform) in the log. |
| `runlog_dir` + `runlog_naming` | Where the execution log is written back and how the file is named. |
| `env_label` | The environment tag for the log (e.g. `local`). |

## Done-criteria
Every selected scenario has exactly one verdict in the run log, and the log
ends with a `## Summary` section (totals per verdict, issues filed/flagged,
environment, run duration). Bound: a per-scenario time cap (default **10
min** — a scenario that exceeds it gets FAIL(timeout) with evidence) and an
overall deadline derived from `count × cap` (confirm with the user when the
selection is large).

## Rails
The engine RUNBOOK's HARD RULES + the adapter's product rails apply in full.
On top of them:
- **NO code changes, no fixes, no branches.** A scenario failure is a
  logged verdict + evidence, never a fix-in-place. (Bugs worth fixing →
  hand to the bug-hunt mission afterwards.)
- **No verdict without observed evidence**: PASS requires every Expected
  assertion observed (screenshot per assertion via `app-pilot shot`); FAIL requires
  the failing observation + a minimal repro note. Ambiguity (precondition
  impossible, role unavailable, flow blocked by the environment) is
  SKIPPED(reason) — never a guessed verdict.
- **Preconditions are setup, not findings**: build them through the app when
  possible; impossible in this environment → SKIPPED(precondition) with the
  reason.
- **Negative cases count**: a scenario's "Negative cases" are assertions too
  — probe them before issuing PASS.
- Money/destructive steps follow the engine's universal audit
  (`app-pilot shot` + `app-pilot act CONFIRM <what>`) and the adapter's mode rails; where
  the adapter has a ground-truth layer, bracket write-steps with
  `app-pilot snapshot` / `app-pilot diff --expect-new N`.
- The run journal (`runs/<id>/journal.md`) is the durable state: scenario
  queue, current position, verdicts so far — re-read it every iteration
  (compaction-proof).

## Options
| Flag | Default | Meaning (implementation is the adapter's) |
|---|---|---|
| `stop_on_fail` | `off` | When on: stop after the first FAIL (report what remains as not-run). |
| `check_figma` | `off` | When on: for screens the scenario touches that the adapter's `product/FIGMA_MAP.md` maps, also run the design-verification procedure; record as a `[design]` note on the scenario, not a verdict change. |
| `fix` | `off` | Reserved — v1 never fixes. If a user asks for fixing, run bug-hunt after this mission instead. |

---

## Procedure
1. **Resolve the selection**: read the corpus per the parameters, parse each
   scenario's metadata table; filter by `automatable_marker` and
   `platform_field`. Print the resulting queue (IDs + titles) and the derived
   bound before starting.
2. **Set up the world**: engine preflight per the bug-hunt mission §2 minus
   branching (no branch — no code changes): `app-pilot serve` → `app-pilot health` →
   `app-pilot init --scope <selection-label> --driver <wake|goal> --label <STAMP>`;
   seed the journal with the queue + rails + bound.
3. **Per scenario** (one or two per iteration, journal-tracked):
   a. Preconditions → satisfy or SKIPPED(reason).
   b. Steps → drive via the engine (tree/tap/type on mobile; ARIA
      snapshot/click/type on web). A step that cannot be performed
      (unfindable element, gesture limitation) → FAIL(step N unreachable) if
      the step is the subject, else SKIPPED(not-automatable-here); log which.
   c. Expected (+ Negative cases) → assert each with evidence.
   d. Verdict + notes into the run log immediately (the log grows as you go —
      a crashed session loses nothing).
4. **Write-back**: the run log lives at `runlog_dir` per `runlog_naming`,
   in the corpus's own convention (the invoker describes it). Keep
   screenshots in the adapter's `runs/<id>/` and reference them by filename.
5. **Finish**: `app-pilot check` ground-truth sweep (if the adapter has one) —
   failures become log notes; append `## Summary` (the completion sentinel)
   to BOTH the run log and `findings.md`; `app-pilot stop`; report totals.

## Driver notes
Same pacing machinery as bug-hunt (wake = `ScheduleWakeup` ≈90 s with the
mandatory status footer, iterating the scenario queue; goal = preflight then
print the `/goal` line whose exit condition is "every queued scenario has a
verdict OR deadline"; `--driven` watchdog rules identical).
