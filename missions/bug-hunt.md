# Mission: bug-hunt

## Goal
Autonomously explore the app on the project's pinned tester (sim or browser),
find bugs, and — in fix mode — fix the clear ones (verified, on a dedicated
branch, ending in a PR). Deliverable: `runs/<id>/findings.md` with a final
`## Summary`, plus the PR when fixes landed.

## Input source
The user's free-text request (scope, bound, constraints) — parsed in §1.
Scope keywords come from the adapter's `product/RUNBOOK.md`, never from here.

## Done-criteria
STEP0 of an iteration exits the loop when ANY of: deadline reached ·
screenshot/iteration cap reached · `## Summary` already present in
`findings.md` (that exact heading is the completion sentinel — the file
itself exists from init, so its existence is NOT a signal). Then §4 Finish
runs exactly once.

## Rails
The engine RUNBOOK's HARD RULES + the adapter's product rails apply in full.
Mission-level reminders (the ones that gate every round):
- **Fixes only on `qa-auto/<scope>-<STAMP>`** — never commit/push the human's
  branch or main; the PR is the review gate. **Verify-or-revert** every fix;
  ≤2 attempts per bug.
- **Triage:** fix clear/localized frontend bugs; **log + skip** ambiguous,
  architectural, native/needs-rebuild, third-party-auth/wallet, or
  new-dependency ones (the engine RUNBOOK's Fix flow defines the classes).
- **Money/destructive-flow audit:** `app-pilot shot` BEFORE and `app-pilot act CONFIRM
  <what>` on EVERY Confirm/Send/Approve/Submit interaction; in a
  staging/real mode do them only where the product rails allow writes
  (read-mostly is the default). Product rails name the app's specific no-go
  actions (e.g. sign-out under mock auth).
- **(mobile)** Tap by a11y label (`app-pilot tree` first); an unlabelled interactive
  element is itself a finding. Sheets: dismiss via labelled buttons or the
  product's tester-escape; verify dismissal via `app-pilot tree`.
- **(web)** Console + network sweep every iteration — a clean screen with a
  500 in the log is a finding. Navigate by ARIA roles/names, never
  coordinates; an unaddressable element is itself a finding.
- **Ground-truth sweep before Finish:** `app-pilot check` (delegates to the
  adapter's `product/app_pilot_api.py`; absent → no-op). Exit 1 = one logged finding
  per failed invariant — include the full output in findings. Bracket risky
  actions with `app-pilot snapshot` / `app-pilot diff --expect-new N` (double-submit probe).
- **Active bug-hunt** — follow the engine RUNBOOK's checklist (forms,
  cross-path consistency, empty-vs-populated, settings→runtime,
  double-submit): 1–2 probes per round. Don't end early — time remaining
  means go deeper.
- Recovery hierarchy per the engine RUNBOOK; self-recover, don't ask.

## Options
| Flag | Default | Meaning (implementation is the adapter's) |
|---|---|---|
| `mode` | `find-and-fix` | "report only" / "just find" / "don't fix" in the request → `report-only` (no code changes). |
| `check_figma` | `off` | When on: after covering a screen that the adapter's `product/FIGMA_MAP.md` maps, run the adapter's design-verification procedure on it; no map/procedure → log a notice, continue. |
| `--driven` | absent | Plumbing flag: a fixed-interval `/loop` is the pacemaker (see Watchdog). Strip it from parsed constraints. |

---

## 1 · Parse intent (state what you parsed)
- **mode** → per the Options table.
- **scope** → one of the adapter's scope keywords (`product/RUNBOOK.md`);
  "the app"/"everything" → `all`. Default `all`.
- **bound** → a **time** ("1h"→60 min, "30m"→30) OR a **coverage** goal
  ("until screens stop repeating", "be thorough"). Default **20 min**.
  Coverage still gets a hard ceiling — **never unbounded.** **Sanity floor:
  < 15 min is too short** (cold-start + first iter leave no headroom) — warn
  and confirm before continuing.
- **extra constraints** (free text — honor them): focus areas, exclusions,
  depth. Bake into the journal's HARD RULES.
- Derive a **deadline** (ISO timestamp = current `date` + minutes) + a
  **screenshot/iteration cap** (~1 per 90 s ⇒ ≈ minutes × ⅔, min 8).

## 2 · Set up
- Read the adapter's `target.py`; state which sim/port/URL + tester mode this
  drives (only that one).
- **Preflight:** `app-pilot health` must be green. If the backend is DOWN, STOP and
  tell the user the start command (health prints the adapter's hint). Do NOT
  start a loop against a dead backend — every screen becomes a TEST_ARTIFACT.
- **Compute the stamp ONCE:** `STAMP=$(date +%Y%m%d-%H%M%S)`; reuse it for
  the branch (`qa-auto/<scope>-<STAMP>`) and `app-pilot init --label`.
- **(fix mode)** require a clean `git status` — dirty → STOP and ask the
  human to commit/stash. Create + checkout `qa-auto/<scope>-<STAMP>` off the
  current branch; note the base branch for the PR.
- `app-pilot serve` → `app-pilot health` (anything off → `app-pilot recover`).
  **(mobile)** after `serve`, give the cold bundle a moment: `sleep 5`, or
  loop on `app-pilot tree` until a known top-level label appears.
  **(web)** `browser_navigate` to `app-pilot target --url`; take the first ARIA
  snapshot to build the nav map (MCP missing → STOP; setup is in the
  project's qa README).
- `app-pilot init --scope <scope> --driver <wake|goal> --label <STAMP>` → run dir
  `runs/<auto-ts>__<scope>__<driver>-<STAMP>/`; seed `runs/<id>/journal.md`
  per the engine RUNBOOK (mode, tester mode, deadline + cap, base branch,
  HARD RULES incl. user constraints, nav-map, plan).
- Tell the user one line before iter 1: **mode · scope · deadline · target ·
  tester mode** — plus the caveat: the loop runs only while this session
  stays open and the Mac stays awake.

## Iteration body (both drivers — engine RUNBOOK §6)
Re-read `runs/<id>/journal.md` FIRST (durable state). Then:
STEP0 stop-check (`date` + shot count vs Done-criteria; at bound → §4) →
STEP1 `app-pilot health` (down → `app-pilot recover`) →
STEP2 **(mobile)** `app-pilot logs` + `app-pilot crashes` / **(web)**
`browser_console_messages` + `browser_network_requests` (real errors,
crash-pattern hits, swallowed 4xx/5xx = findings) →
STEP3 read the latest screenshot/snapshot → assess → `app-pilot note` any bug →
STEP4 (fix mode) if fixable → the engine RUNBOOK's **Fix flow** →
STEP5 navigate deeper (engine + product rules) → `app-pilot shot <label>` →
STEP6 update the journal (Tested / Nav map / Next steps).

## Driver: wake (`ScheduleWakeup` self-pacing)
At the END of every iteration call `ScheduleWakeup`:
- `delaySeconds` ≈ 90 (keeps the prompt cache warm).
- `prompt` = the original invocation verbatim, so the loop re-enters. Its
  first action must be re-reading `runs/<id>/journal.md` (compaction-proof).
- `reason` = one-liner of current state.

**End-of-turn status footer (mandatory)** — every iteration's last message
ends with this table, so the user can tell run-state at a glance:

```text
| | |
|---|---|
| **State** | ⏳ Waiting · iter N/~M done |
| **Shots** | Y / <cap> |
| **Time** | now HH:MM · deadline HH:MM · ~K min remaining |
| **Next wake** | #N+1 at HH:MM (delay Xs) |
| **Last action** | what THIS iter just did |
| **Next action** | what the NEXT iter will do (journal Plan) |
```

`🏁 Finished · N iters, Y shots` on the final turn — omit Next wake/action.

**Interactive pings mid-loop:** answer normally; do NOT schedule a defensive
extra wake (the pending one still fires and resumes via the journal). On
STOP/CANCEL: summarize; the pending wake reads the journal and exits
gracefully.

## Driver: goal (`/goal` Stop-hook pacing)
`/goal` is a Claude Code UI command — the harness rejects skill-side
invocation; only the user, `claude -p`, or Remote Control can start it. So
this driver does §1–§2 preflight, then prints **one fenced block with exactly
the command to paste**, and stops (no looping, no scheduling):

```text
/goal Drive the QA loop per the engine RUNBOOK "Run a QA loop" §6 iteration steps (read <adapter>/RUNBOOK.md for the pointers). Mode: <mode>. Scope: <scope>. Branch: qa-auto/<scope>-<STAMP>. Run dir: <adapter>/runs/<id>/. Re-read runs/<id>/journal.md FIRST inside every iteration. Exit when ANY of: (a) Bash `date` ≥ <deadline ISO>, (b) `ls <adapter>/runs/<id>/screenshots | wc -l` ≥ <cap>, (c) `grep -q '^## Summary' <adapter>/runs/<id>/findings.md` succeeds. After exit, append the `## Summary` section to findings.md (if not already). IF `git log <base>..qa-auto/<scope>-<STAMP> --oneline` shows commits, push the branch and open a PR into <base> per the product PR convention; ELSE leave the branch local and report its name (don't open an empty PR).
```

Add one line above the block: **mode · scope · deadline · target · tester
mode** + the session-scoped caveat. After the paste, the Stop hook paces
every turn through the same iteration body; end each iteration with a
one-line summary (the overlay covers liveness). CI note: `/goal` works under
`claude -p` / Remote Control — script the preflight and a PR-trigger
pipeline becomes viable.

## Watchdog (`--driven`)
A fixed-interval `/loop` (front door: the project's `/app-pilot-watchdog`,
composing `/loop 3m /app-pilot <args> --driven`) re-fires the wake shim
on a timer EVEN IF an iteration crashed — that is the point. In this mode:
- **Never call `ScheduleWakeup`** — two pacemakers double-fire.
- At setup: `CronList`, find the recurring job whose prompt is this
  invocation verbatim, record its job ID in the journal header.
- Each firing runs ONE iteration; the journal rules; STEP0 still exits.
- At §4 Finish, **cancel the pacemaker yourself**: `CronDelete` the recorded
  ID (fallback: `CronList` + verbatim match; ≥2 matches → ambiguous, leave it
  and tell the user which IDs).
- A post-finish firing means the delete failed: see `## Summary`,
  `CronDelete` again, reply "run complete — pacemaker cancelled", stop.
- Footer "Next wake" row becomes `harness-paced (fixed interval)`.

## 4 · Finish (Done-criteria met)
- **Ground-truth sweep first:** `app-pilot check` — each failure is a finding;
  include the full output in findings.
- Append the final `## Summary` section to `runs/<id>/findings.md`.
- **Pre-PR quality gate (fix mode, when commits exist) — BEFORE pushing:**
  run the built-in review skills over the branch diff: `/simplify` first
  (reuse/extraction findings a human reviewer would request — inline helpers
  that belong in shared utils, derivation logic that belongs in its own
  module) and then `/code-review` (correctness). Apply the high-confidence
  findings as additional commits; after ANY gate change, re-verify the
  affected fixes' repros and re-run the product static checks. One gate pass
  only — don't loop. If the skills aren't available in the session, note
  that in findings and proceed.
- IF commits exist on `qa-auto/<scope>-<STAMP>`: push + open a PR into the
  base per the **product PR convention** (`product/RUNBOOK.md` — e.g. some
  repos want title-only bodies + self-assign). ELSE leave the branch local
  and report its name.
- (wake) do NOT schedule again · (--driven) cancel the pacemaker · report
  and stop.
