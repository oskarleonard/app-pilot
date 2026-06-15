# Mission: improvement

## Goal
Work a backlog of KNOWN, non-bug improvements — paper cuts, tech debt, perf
hot-paths, accessibility gaps, localized refactors, safe dependency bumps —
landing the clear ones as verified, behavior-preserving changes on a dedicated
branch, ending in a PR. This is not exploration (that's bug-hunt) and not
feature work (that's feature-dev): the backlog already decided WHAT; this
mission TRIAGES it, does the safe ones, and hands every owner-decision back
instead of guessing. Deliverable: `runs/<id>/improvements.md` with one verdict
per item (DONE / SKIPPED / DEFERRED, each with a reason + evidence) and a final
`## Summary`, plus the PR when DONE commits exist.

## Input source
All parameters — supplied by the invoker/adapter, never hardcoded here.

| Parameter | Meaning |
|---|---|
| `backlog` | Path to the backlog file. Each item: a short title, the rough shape of the change, and why it's worth doing. The invoker resolves it from wherever the backlog lives and hands over a path — a mission never reads an external tracker itself. |
| `selection` | Which items to work: `top-N`, an id/glob, a labelled subset, or `all`. Default: the top items up to `cap`. |
| `request` | Free-text scope/constraints (`$ARGUMENTS`). |
| `base` | Branch to build off and PR into. Default: the current branch at launch. |

## Done-criteria
Every SELECTED item has exactly one verdict — **DONE** (changed + verified),
**SKIPPED**(reason), or **DEFERRED**(reason) — in `improvements.md`, the log
ends with `## Summary` (the completion sentinel), and IF any DONE commits exist
a PR is open into `base`. Bound: an **item cap** (default **3** landed items —
keeps the PR reviewable) AND a **time ceiling** (`request` hint, default **60
min**); whichever ends first, the rest are reported as not-run. An item past
≤2 attempts → DEFERRED(blocked) + reason. Never unbounded.

## Rails
The engine RUNBOOK's HARD RULES + the adapter's product rails apply in full.
On top of them:

- **Branch + PR only, on `improve/<label>-<STAMP>`** — never the human's branch
  or `base` or main; never merge. **Write-fence:** state the one repo + branch
  you may write before the first edit; everything else is read-only.
- **Triage is the job — surface owner-decisions, don't guess them.** Per item:
  - **DO** it only if it is clear, localized, low-risk, and behavior-preserving
    (rename, extract a helper, move a token, add an a11y attribute, a contained
    perf fix, a safe patch-level bump).
  - **SKIPPED → bug-hunt** if the item is actually a behavioral defect (a fix
    that changes observed output is a bug, not an improvement).
  - **DEFER → owner** if it is architectural, cross-cutting, parity-/product-
    intent-sensitive (would alter a surface someone verified on purpose), needs
    a new dependency or a native rebuild, or has more than one defensible
    answer. A DEFERRED item gets a crisp write-up (what, the options, the
    trade-off) — decision-ready, not a raw pile.
- **Behavior-preserving by default** (`behavior: preserve`): the change must not
  alter observed behavior; prove it identical on the tester + static checks. An
  item that intends a visible change must be invoked `behavior: change` and name
  the expected delta up front, which then becomes its acceptance check.
- **Verify-or-revert, per item, ≤2 attempts:** the adapter's static checks
  (`tsc`/test/lint/build) green AND a tester spot-check of the touched surface
  (live-proof: unchanged, or the authorized delta). No "works" without evidence;
  a dead attempt is reverted, not left half-applied.
- **First contact with an unscanned repo = report-only:** triage + plan, no
  commits, until granted (Options `mode`).
- **Money/destructive-flow audit** when a touched surface includes such a flow
  (same universal rule as bug-hunt).
- **The author does not solely grade the work** — verdicts are objective
  (static green + behavior-identical live check); recommend a fresh non-author
  verifier on the PR.
- Recovery hierarchy per the engine RUNBOOK; self-recover, don't ask.

## Options
| Flag | Default | Meaning (implementation is the adapter's) |
|---|---|---|
| `mode` | `apply` | "report only" / "triage only" in the request → `report-only`: produce the per-item triage (DO/SKIP/DEFER + reasons) and stop, no commits. First-contact default. |
| `cap` | `3` | Max items to LAND in one run (PR stays reviewable); the rest are reported not-run. |
| `behavior` | `preserve` | `preserve` = refuse any change that alters observed output (verify identical). `change` = a visible delta is intended; the item must name it (becomes the acceptance check). |
| `check_figma` | `off` | When on: for touched screens the adapter's `product/FIGMA_MAP.md` maps, run the design-verification procedure as a `[design]` note. |
| `--driven` | absent | Plumbing flag — fixed-interval `/loop` pacemaker (bug-hunt Watchdog rules, identical). Strip from parsed constraints. |

---

## Procedure
1. **Parse intent** (state what you parsed): mode, `backlog` path, `selection`,
   `cap`, `behavior`, time bound → derive a **deadline** (ISO = `date` +
   minutes). First contact ⇒ `report-only`.
2. **Resolve + triage the backlog:** read it; classify each selected item
   **DO / SKIP(bug→bug-hunt) / DEFER(owner-decision)** with a one-line reason
   each. Print the triaged queue + the bound BEFORE touching code — the triage
   is the mission's first deliverable and stands on its own in report-only mode.
3. **Set up:** engine preflight per bug-hunt §2 (`qa serve` → `qa health` →
   `qa recover`); require a clean `git status` (dirty → STOP); `STAMP` once;
   create `improve/<label>-<STAMP>` off `base`; `qa init`; seed
   `runs/<id>/journal.md` with the queue + dispositions + rails (write-fence,
   `behavior` mode) + base branch. Seed `improvements.md` with the verdict
   table — it is mission-owned, write verdicts to it directly (`qa note` /
   `findings.md` is only for incidental defects you trip over).
4. **Per DO item** (one or two per iteration, journal-tracked, re-read the
   journal first):
   a. Make the smallest localized change.
   b. Adapter static checks green; red → fix or revert (≤2, then DEFERRED).
   c. **Live spot-check** the touched surface on the tester (`qa shot`):
      behavior preserved (or the authorized `change` delta observed).
   d. Commit (one item per commit, message = the item title); write the
      **DONE** verdict + evidence path into `improvements.md` immediately.
5. **Finish:** `qa check` ground-truth sweep (failures → log notes, block the
   PR until resolved); append the verdict table + `## Summary` (totals per
   verdict + the **DEFERRED owner-decisions list**, so the human gets a
   decision-ready summary, not a pile; any selected item not reached within the
   bound is listed as `not-run (bound)`, so every selected item has a
   disposition). **Pre-PR quality gate** (when commits
   exist, before pushing): `/simplify` then `/code-review` over the diff, apply
   high-confidence findings, re-verify the touched items + re-run static checks;
   one pass, no loop (skills absent → note it, proceed). IF DONE commits exist:
   push + open a PR into `base` per the **product PR convention**, body = the
   verdict table + the DEFERRED list; ELSE report the triage, no empty PR.
   (wake) don't reschedule · (--driven) cancel the pacemaker · report + stop.

## Driver notes
Same pacing machinery as bug-hunt/scenario-exec: **wake** = `ScheduleWakeup`
≈90 s with the mandatory status footer (substitute **items N/M done** for the
shot count); **goal** = preflight then print the `/goal` line whose exit is
"every selected item has a verdict AND (DONE commits ⇒ PR open) OR deadline";
**`--driven`** watchdog rules identical to bug-hunt.
