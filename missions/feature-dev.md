# Mission: feature-dev

## Goal
Build ONE specified feature from a spec onto a dedicated branch, prove each of
its acceptance criteria live on the project's pinned tester (the engine is the
proof gate, not the author), and open a PR with that evidence. This is the
developer-from-a-spec loop: the spec decides WHAT to build and when it's done;
the engine decides HOW to verify it really works. Deliverable:
`runs/<id>/build-log.md` with a per-criterion verdict table and a final
`## Summary`, plus the PR when commits exist.

## Input source
All parameters — supplied by the invoker/adapter, never hardcoded here.

| Parameter | Meaning |
|---|---|
| `spec` | Path to the spec file: acceptance criteria, scope, constraints, the PR convention. The invoker resolves it from wherever specs live (a backlog, a tracker export, a local file) and hands over a path — a mission never reads an external tracker itself. |
| `request` | The user's free-text scope/constraints (`$ARGUMENTS`) — narrows or augments the spec. |
| `base` | The branch to build off and PR into. Default: the current branch at launch. |

The spec's **acceptance criteria** become both the Done-criteria and the
live-verification checklist. No spec supplied → see Options `derive_spec`.

## Done-criteria
The run ends when EVERY acceptance criterion is either **PASS** (implemented
AND observed working live, with evidence) or **BLOCKED** (≤2 attempts spent,
logged with a repro + reason — never a guessed pass), the `## Summary` section
is appended to `build-log.md` (that exact heading is the completion sentinel),
and — IF commits exist on the branch — a PR is open into `base`. No commits
(e.g. report-only, or fully blocked) → report the branch + derived spec +
blockers; never open an empty PR. Bound: a **time ceiling** (`request` time
hint, default **90 min**) AND the criteria list itself; whichever ends first.
Never unbounded.

## Rails
The engine RUNBOOK's HARD RULES + the adapter's product rails apply in full.
Layered on top (this mission commits code, so they are strict):

- **Branch + PR only, on `feat/<slug>-<STAMP>`** — never commit/push the human's
  branch or `base` or main; the PR is the review gate. **Never merge.**
- **Write-fence:** before the first edit, state the one repo + the one branch
  you may write; everything else is read-only. A change wanted outside that
  fence is a logged follow-up, not an edit.
- **The spec is the contract — build only what it asks.** No gold-plating, no
  unrequested refactors, fallbacks, or abstractions: the simplest thing that
  satisfies the criterion. Scope you discover beyond the spec → log it as a
  follow-up idea in the build log, don't build it.
- **Verify-or-revert, per criterion, ≤2 attempts.** A criterion that won't go
  green is BLOCKED + logged, not faked and not left half-applied (revert the
  dead attempt). Never two rounds grinding the same stuck criterion — log it,
  move to the next.
- **Live-proof gate (the reason this runs on the engine):** verify the EXACT
  final commit through the REAL changed path with REAL artifacts — drive the
  feature on the tester and capture evidence per criterion (`app-pilot tree`/`app-pilot shot`
  on mobile; ARIA snapshot on web). Static checks (the adapter's
  `tsc`/test/lint/build) are necessary but NOT sufficient — a green suite with
  no live observation is an unverified criterion.
- **First contact with an unscanned repo = report-only:** derive/read the spec,
  plan, name the branch — but make no commits until granted (Options `mode`).
- **Money/destructive-flow audit** (same as bug-hunt): `app-pilot shot` before and
  `app-pilot act CONFIRM <what>` on every Confirm/Send/Approve/Submit the feature
  introduces; forbidden outright in a staging/real mode. Product rails name the
  app's no-go actions.
- **The author does not solely grade the work.** Done-criteria are objective
  (each criterion observed live); recommend a fresh, non-author verifier on the
  PR — the maker's reasoning trail biases its own grading.
- Recovery hierarchy per the engine RUNBOOK; self-recover, don't ask.

## Options
| Flag | Default | Meaning (implementation is the adapter's) |
|---|---|---|
| `mode` | `build` | "plan only" / "report only" in the request → `report-only`: produce the (derived) spec + the criteria checklist + the branch name + a build plan, no commits. First-contact default. |
| `derive_spec` | `auto` | No `spec` path given: `auto` → derive a thin spec into `runs/<id>/spec.derived.md` (status: derived) from `request` + `product/RUNBOOK.md`, print it, and build to it; `off` → STOP and ask for a spec. |
| `check_figma` | `off` | When on: for each built screen the adapter's `product/FIGMA_MAP.md` maps, run the adapter's design-verification procedure; record a `[design]` note per screen. No map/procedure → log a notice, continue. |
| `--driven` | absent | Plumbing flag: a fixed-interval `/loop` is the pacemaker (see Watchdog in bug-hunt — identical rules). Strip it from parsed constraints. |

---

## 1 · Parse intent (state what you parsed)
- **mode** → per the Options table (first contact ⇒ `report-only`).
- **spec** → the path; read it now. Absent ⇒ `derive_spec`.
- **bound** → a time hint from `request` (default **90 min**); derive a
  **deadline** (ISO = `date` + minutes). The criteria list is the other bound.
- **extra constraints** (focus, exclusions, "don't touch X") → into the
  journal's HARD RULES.

## 2 · Resolve the spec
- Read `spec` (or derive it per `derive_spec`). Extract the **acceptance
  criteria** as an explicit, numbered checklist — each one must be observable
  on the tester or by a check the spec names. An untestable criterion is a spec
  bug: note it and propose an observable restatement before building.
- Print the criteria list + the bound. This is the contract you will verify
  against; nothing outside it gets built.

## 3 · Set up
- Engine preflight per bug-hunt §2: read `target.py` (state the sim/port/URL +
  tester mode); `app-pilot serve` → `app-pilot health` (off → `app-pilot recover`); **never build
  against a dead backend.**
- **Require a clean `git status`** — dirty → STOP and ask the human to
  commit/stash. Compute `STAMP=$(date +%Y%m%d-%H%M%S)` ONCE; create + checkout
  `feat/<slug>-<STAMP>` off `base`; record `base` for the PR.
- `app-pilot init --scope <slug> --driver <wake|goal> --label <STAMP>` → seed
  `runs/<id>/journal.md`: the criteria checklist, tester mode, deadline, base
  branch, the **write-fence**, HARD RULES (incl. user constraints), and the
  build plan. Seed `build-log.md` with the empty criteria table —
  `build-log.md` is mission-owned, write verdicts to it directly; `app-pilot note` /
  `findings.md` is for incidental defects you trip over, not the criteria.
- One line before building: **mode · feature slug · #criteria · deadline ·
  target · tester mode** + the caveat that the loop runs only while this
  session stays open and the Mac stays awake.

## 4 · Build + verify loop (engine RUNBOOK §6 pacing; journal-tracked)
Re-read `runs/<id>/journal.md` FIRST every iteration (compaction-proof). Then:
STEP0 stop-check — exit to §5 on ANY of: deadline reached · all criteria
terminal (PASS/BLOCKED) →
STEP1 `app-pilot health` (down → `app-pilot recover`) →
STEP2 pick the next un-met criterion; implement the **smallest** change that
satisfies it (the spec is the ceiling, not a floor to gold-plate) →
STEP3 run the adapter's static checks (`product/RUNBOOK.md` names them —
`tsc`/test/lint/build); red → fix or revert (≤2 attempts, then BLOCKED) →
STEP4 **live-proof:** drive the real path on the tester, observe the criterion
holding, `app-pilot shot <criterion-label>`; mark **PASS** (with evidence path) or
**BLOCKED** (repro + reason) in `build-log.md` immediately →
STEP5 commit the increment (reviewable, one concern per commit) →
STEP6 update the journal (Done / Remaining / Next).

## 5 · Finish (Done-criteria met)
- **Ground-truth sweep:** `app-pilot check` (adapter's invariants; absent → no-op).
  Each failure is a finding folded into the build log — a regression here
  blocks the PR until fixed or reverted.
- Append the per-criterion verdict table + a final `## Summary` (criteria
  PASS/BLOCKED counts, evidence paths, any out-of-scope follow-ups) to
  `build-log.md`.
- **Pre-PR quality gate (when commits exist) — BEFORE pushing:** run the
  built-in review skills over the branch diff: `/simplify` first (reuse/
  extraction findings a human reviewer would request) then `/code-review`
  (correctness). Apply the high-confidence findings as additional commits;
  after ANY gate change, re-run the affected criteria's live checks and the
  product static checks. One gate pass only — don't loop. Skills unavailable in
  the session → note it in the build log and proceed.
- IF commits exist on `feat/<slug>-<STAMP>`: push + open a PR into `base` per
  the **product PR convention** (`product/RUNBOOK.md`). The PR body carries the
  criteria→evidence table so a reviewer sees, per criterion, the live proof.
  ELSE leave the branch local and report its name + the blockers.
- (wake) do NOT schedule again · (--driven) cancel the pacemaker · report and
  stop. Recommend a fresh non-author verifier as the next step.

## Driver notes
Same pacing machinery as bug-hunt: **wake** = `ScheduleWakeup` ≈90 s with the
mandatory end-of-turn status footer (substitute **criteria N/M PASS** for the
shot count); **goal** = §1–§3 preflight then print the one `/goal` line whose
exit condition is "every acceptance criterion is PASS or BLOCKED AND (commits ⇒
PR open) OR deadline reached"; **`--driven`** watchdog rules are identical to
bug-hunt (never also call `ScheduleWakeup`; one iteration per firing; cancel
the pacemaker at §5).
