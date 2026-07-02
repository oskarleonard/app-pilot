# app-pilot RUNBOOK — how the AI runs a QA round (engine spine)

The **AI drives + evaluates + (by default) fixes**; the scripts are just eyes/hands
on the iOS simulator. The human says e.g. *"find and fix bugs in the send flow for
1h"* or *"report only, 30m"*, then reviews the result (a PR + a findings list).
All commands go through the PROJECT's front door: **`scripts/app-pilot/app-pilot <cmd>`**.

**Read order for a run: this file → the project's `product/RUNBOOK.md`** (its
tester modes, rails, scopes, static checks) **→ the project's `target.py`**
(the pin). Where this spine says "per product", the addendum decides.

## Two modes (what to do with bugs)
- **find-and-fix (default):** find bugs AND fix the ones with a clear, verifiable root
  cause — on a dedicated branch, one commit per fix, ending in a PR. Escalate (log
  only) the ambiguous / architectural / native ones.
- **report-only:** find + log, no code changes. Triggered by "report only" /
  "just find" / "don't fix".

## Tester modes (what world the app runs in — target.py MODE)
Defined per product in `product/RUNBOOK.md`. The universal pattern:
- A **mock/local** mode (auth stubbed, app pointed at local data) is the default
  world: writes are local, so exercising real flows is allowed AND wanted.
  Preflight: if the project pins a `BACKEND_URL`, it must answer (`app-pilot health`
  checks; if DOWN, STOP and tell the human the start command — health prints it).
- A **staging/real** mode (if the product defines one) flips the rails to
  **read-mostly**: never tap Confirm / Send / Approve / Submit / Delete-style
  controls — observe and screenshot only.

## Two loop drivers (pick at invocation time)
- **wake** (`/app-pilot <mission> wake …`, the default) — `ScheduleWakeup`-driven,
  one-step invocation. The mission does preflight + every iteration + every
  reschedule itself. Best for interactive dev sessions where you start it and
  walk away.
- **goal** (`/app-pilot <mission> goal …`) — `/goal`-driven, two-step invocation.
  The mission does preflight then prints a ready-to-paste `/goal …` command; from
  there `/goal`'s Stop hook drives every turn. Required for `claude -p` /
  Remote Control / CI pipelines.
- **Watchdog variant:** `/loop 3m /app-pilot <args> --driven` makes the
  HARNESS the pacemaker — it re-fires the skill on a fixed timer even if an
  iteration crashed before self-scheduling. The skill then never schedules its
  own wakes; post-finish firings are journal-guarded no-ops until cancelled.
- Both follow the SAME iteration body (§6) and the same Fix flow / HARD RULES.

## Run a QA loop
1. **Own Metro:** `app-pilot serve` (starts Metro AND force-reloads the app from it — a
   foregrounded app may be running another Metro's bundle) → `app-pilot health` (metro UP
   + backend UP (if pinned) + app state `app` + idb companion UP + no fatal crash
   since serve — all green before iter 1; anything off → `app-pilot recover`).
2. **(fix mode) Clean tree + branch:** require a clean `git status` — if dirty, STOP
   and have the human commit/stash first (never entangle their work). Then create +
   checkout `qa-auto/<scope>-<STAMP>` off the current branch; remember the base
   branch for the PR.
3. **Start a run:** `app-pilot init --scope <scope> --driver <wake|goal> --label <STAMP>`
   → run dir `runs/<auto-ts>__<scope>__<driver>-<STAMP>/`.
4. **Seed `runs/<id>/journal.md`** with: mode (find-and-fix/report-only), tester mode,
   bound (deadline + screenshot cap), base branch, the HARD RULES, a nav-map, a plan,
   next-steps. The journal IS the loop's state — re-read it every iteration; it
   survives compaction.
5. **Self-pace** per the invoked skill (`ScheduleWakeup` ≈90s, or `/goal`'s Stop hook).
6. **Each iteration:** Re-read `runs/<id>/journal.md` FIRST (durable state). Then:
   - STEP0 stop-check (`date` + screenshot count; at bound → §7 Finish)
   - STEP1 `app-pilot health` (anything down → `app-pilot recover`)
   - STEP2 `app-pilot logs` + `app-pilot crashes` (note real warns/errors + crash-pattern hits)
   - STEP3 Read latest screenshot → assess → `app-pilot note` any bug
   - STEP4 (fix mode) if fixable → run the **Fix flow**
   - STEP5 navigate (rules below) → `app-pilot shot <label>`
   - STEP6 update journal (Tested / Nav map / Next steps).
   - **After dismissing a sheet**, verify via `app-pilot tree`: the sheet's own labels
     must be GONE. Background content being present does NOT prove the sheet
     closed — gorhom keeps the background reachable in the a11y tree.
7. **Finish (bound reached):** append the final **`## Summary`** section to
   `findings.md` — that exact heading is the run's completion sentinel (the
   file itself exists from init; the `/goal` driver greps for the heading);
   run the product's ground-truth sweep first (§ below); (fix mode) if
   `git log <base>..qa-auto/<scope>-<STAMP> --oneline` shows commits, push the branch
   and open a PR into the base (`gh pr create --base <base> --fill`) — if no
   remote/auth, leave the branch local and report its name. Report and stop.

## PR evidence for visual fixes (MANDATORY when a fix changes the screen)
A find-and-fix run that changed anything ON-SCREEN must SHOW the change in the PR
body, not just describe it:
- **Before/after montage per visual fix** — same screen, pre- vs post-fix, side by
  side. **Capture the failing state with an archival `app-pilot shot` when you LOG the
  bug** — that is the before half; at Finish it's too late to recreate it.
  `after` = the verified fix captured on a **cold reload** (`app-pilot reload`), NOT a
  Fast-Refresh frame — Fast-Refresh screenshots can show transient clipping
  that isn't in shipped code.
- **High-res source, width-constrained display.** Render the montage at full res
  (~600px/frame); **never downscale the source** (bakes in blur). Constrain only
  the DISPLAY in the PR body: `<img src="…?raw=true" width="580" />` —
  **580px is the standard.**
- **One-line "what changed" caption above each image** so the diff reads at a glance.
- **Host images via `app-pilot publish` — NEVER on the PR/run branch.** Run
  `app-pilot publish <montage.png> --feature <flow>-<topic> [--caption "…"]`: it
  appends the PNG to the hidden, append-only `refs/app-pilot-assets/store` ref (no
  branch → no "recent pushes" banner, nothing to merge; created/seeded on
  first use) and prints a commit-pinned `<img …>` tag to paste into the PR
  body. Images share no history with `main` and never appear in any branch
  or Files-changed. **Never `git add` a PNG on the run branch** — on
  squash-merge that lands it in `main`.

**The montage gate is MECHANICAL, not a judgment call** — never infer
visual-vs-logic from a fix's title or category. At Finish, for EVERY committed
fix, compare its before/after pair: `magick compare -metric AE before.png
after.png null:` (or view them side by side). ANY non-zero pixel diff → the
montage is mandatory, even for an "a11y/logic" fix. Only a byte-identical pair
(a truly non-visual fix) skips it — and those cite the a11y-tree / `app-pilot find`
diff as the PR evidence instead. No before shot captured = treat as differing
(montage from the closest available state, and note the gap).

## Scopes (which surfaces to visit)
Product-defined — the scope keywords and their surface tables live in
`product/RUNBOOK.md`. Universal rule: derive the live nav-map from `app-pilot tree`
on the first iteration — don't guess labels.

## Fix flow (find-and-fix mode, per bug)
1. **Triage — classify first:**
   - **CODE_BUG** — clear, localized root cause (dead handler, backwards label,
     missing null-guard, crash with a stack) → **fix it.**
   - **PLATFORM_LIMITATION** — native/needs-rebuild, push notifications,
     third-party auth/wallet, performance, anything not verifiable on-screen,
     or needs a new dependency → **log + skip.**
   - **TEST_ARTIFACT** — the "bug" is in your own repro/expectation (e.g. BE
     down, mock-auth limitation), not the app → discard, don't log it.
2. **Fix — strict scope guard:** change ONLY the failing behaviour's code. No new
   files, no refactors/extractions, no routing changes; if it's visual, touch only
   styling. Smallest change, in the codebase's style — BUT fix the buggy *pattern*
   in all its instances, not just the one screen. (JS/TSX hot-reloads via Fast Refresh.)
   Priority when several: P0 render/crash → P1 logic/nav → P2 a11y → P3 visual polish.
3. **Verify — replay + regression check:** edits Fast-Refresh in ~1-2s; if a change
   doesn't apply (red box, or a non-component edit), `app-pilot reload` (cold restart).
   Replay the repro; confirm the bug is gone, the screen is sane, Metro/crash logs
   clean, and the project's static checks pass (`product/RUNBOOK.md` names them).
   THEN re-check screens you already passed this run — if the fix broke a
   previously-PASS screen, that's a **regression** (treat as a failed verify).
4. **Commit or revert:** verified + no regression → commit just that fix (message =
   bug + repro + why), one commit per fix. Not verified / regressed → revert.
5. **Stuck-loop cap:** max **2 fix attempts per bug**. If the 2nd still fails to
   verify, STOP fixing it — log an escalated finding noting "tried A, then B —
   neither verified" — and move on. Record each attempt in the journal so a
   post-compaction resume never re-tries a fix already known to fail.

## HARD RULES (non-negotiable)
- **Branch isolation:** fixes land on `qa-auto/<stamp>` ONLY. NEVER commit to or push
  the human's branch or `main`; never force-push. The PR is the review gate.
- **Verify-or-revert:** never keep an unverified fix.
- **Bounded fixing:** ≤ 2 fix attempts per bug, then escalate — never spiral.
- **Tap by accessibility label (idb):** `app-pilot tree` lists every labelled element +
  frame; tap with `app-pilot tap --label "AXLabel"` (content) or `app-pilot tap --tab <name>`
  (tab names: target.py `TAB_ORDER`; the iOS 26 floating pill is probed via
  describe-point — naive segment math taps empty glass). `--frac fx,fy` is a
  last-resort fallback for unlabelled targets. Always `tree` first so you tap a
  real element, not a pixel guess. An element the tester can't find = a missing
  `accessibilityLabel` = **itself a finding**.
- **Frames are viewport-relative — check before tapping.** `app-pilot tree` reports
  a11y frames for OFF-SCREEN scrollable content too: `y < 0` = scrolled past,
  `y >` screen height = below the fold, and anything overlapping the Tab Bar
  group's frame is occluded by the floating pill. Taps at those coords hit
  nothing or the tab bar. **`app-pilot tap --label` refuses such targets itself** and
  tells you to scroll first (`--force` overrides, e.g. for system-dialog
  buttons). `app-pilot scroll down|up [--amount 0.4]`, re-`tree`, then tap. Scrolling
  works on native RN ScrollView/FlatList; RNGH-handled gestures (gorhom drag,
  swipeables) ignore synthesized touches.
- **Money/destructive flows:** follow the product rails in `product/RUNBOOK.md`.
  Universal minimum: EVERY tap on a Confirm / Send / Approve / Submit-style
  button must be preceded by `app-pilot shot` and logged via `app-pilot act CONFIRM <what>`
  so the human can audit the run afterwards. In a staging/real mode these taps
  are FORBIDDEN.
- **Recovery hierarchy — prefer in-app navigation; `app-pilot reload` is the LAST resort.**
  1. **Stuck on a bottom sheet?** → tap its own labelled Close/Cancel button if
     it has one; else the product's tester-escape label (see `product/RUNBOOK.md`
     — only present in tester-driven bundles).
  2. **Stuck mid-flow?** → labelled Back / Cancel buttons, or `app-pilot tap --tab <home>`.
  3. **`app-pilot tree` returns EMPTY / taps silently no-op (but the screenshot shows a
     populated screen)?** → the **idb companion died**. `app-pilot recover` self-heals.
     Don't mistake an empty tree for "nothing on screen" — cross-check a screenshot.
  4. **Genuinely stuck** (red box, hung JS, unresponsive after companion respawn,
     lost track of the nav stack) → `app-pilot reload`.
- **Gorhom bottom-sheets — backdrop tap and drag-down DON'T work** (RNGH ignores
  idb-synthesized touches). Dismiss via the sheet's own labelled buttons, or the
  product's tester-escape. If a sheet that should have closed didn't, dismiss and
  re-check `app-pilot tree` before declaring downstream state a bug.
- **Native `UISwitch` (raw RN `<Switch>`) — taps DON'T flip it** (verified: idb
  taps no-op even dead-center; a short horizontal swipe across its frame DOES
  toggle it). Apps using Pressable-based switch primitives are immune — prefer a
  whole-row Pressable toggle pattern over a tester workaround.
- **Image-processing error = stop the loop (cost hazard, never self-heals in-session).**
  If the console shows `API Error: an image in the conversation could not be processed
  and was removed`, or a screenshot read comes back with no image, an oversized image
  (>2000px on a side — the model API's cap once a conversation carries many images) is
  in the history. ONE such image poisons every later image read in the session,
  including already-sent ones, and every strip-and-retry invalidates the prompt
  cache, so all remaining turns bill at near-full price. Do NOT keep QA-ing through
  it and do NOT retry the read — write current state to `findings.md`, end the
  session, resume fresh. `app-pilot shot` downscales to ≤1800px precisely to prevent this;
  if the banner appears anyway, some other path shipped a full-res image — likely a
  PR-evidence **montage** (read back a `sips -Z 1800` copy, keep the full-res file
  for the PR) or a raw `simctl io screenshot`.
- **No new dependencies / installs / native rebuilds** in the loop — log those instead.
- **Self-recover, don't ask** (scoped to target.py's sim/port): `app-pilot health` / `app-pilot recover`.

## Active bug-hunt checklist (do these, don't just happy-path-navigate)

Visiting each screen and seeing it looks "fine" is coverage breadth without depth.
The patterns below only show up when you actively probe — sprinkle 1-2 per QA
round, not every item every iter. **Do not end the loop early** — STEP0 exits ONLY
on deadline or shot-cap; "the happy path looks done" is the signal to go *deeper*.

### Modal & overlay residue
- After every sheet dismissal: `app-pilot tree` → the sheet's labels must be gone.
- Modal-from-modal: close the inner one, verify the outer one is still in the
  expected state.

### Forms & validation
- Numeric inputs: `0`, negative, absurdly large, `1,23` vs `1.23`, letters, empty.
  Expected: clean validation errors, never NaN/crash/silent-accept.
- Rapid double-tap on submit-style buttons — double-submit guard.
- Required-field-empty submits; whitespace-only text fields.

### Cross-path consistency
- Same entity via two paths (list → detail vs other entry point) — identical data?
- Open a sheet, switch tab, come back — note which behaviour you observe
  (still open vs dismissed); surface to product if unclear which is intended.

### Empty vs populated states
- Fresh local data = mostly empty states; after exercising flows, revisit the
  same screens populated. Both must render cleanly (no clipped empty-state art,
  no spinner-forever).
- Mutate something → do OTHER screens showing that entity update (cache
  invalidation bugs hide here)?

### Settings → runtime effect
- Change one setting per round, verify it's reflected everywhere it appears,
  then tab away/back (persisted?), then `app-pilot reload` (still persisted? —
  client-store vs server state confusion).

### Permission/role gating (if the product has roles)
- Permission-gated UI that's *visible but dead* (tap does nothing) is a finding.
  Testing OTHER roles needs different accounts — observe + log, don't mutate roles.

## Design verification (on demand — `product/FIGMA_MAP.md`)
When asked to check a screen against design ("check X against Figma",
`/check-figma X`): resolve the node in the product's **FIGMA_MAP.md** (it
decodes the Figma file structure and carries the `current` pointer per screen),
fetch the Figma render via MCP `get_screenshot` (curl the PNG into
`runs/<id>/figma/`), capture the sim in the SAME screen+state, view both, and
judge in **structure+tokens** mode by default (`--strict` only on request).
Data differences are never findings; missing/extra elements, layout order,
token/typography drift are. Log each as a `[design]` finding; record
team-blessed divergences in the screen's accepted-deviations list. Screens not
in the map yet: follow FIGMA_MAP's "Adding a screen" recipe first.

## Limits
- Both drivers are session-scoped — they fire only while this terminal/session
  stays alive and the Mac stays awake. Not a background daemon.
- Visual / crash / flow / on-screen-logic bugs + JS-TSX fixes only. Can't judge
  push notifications, native-only flows, real OAuth, performance, or anything
  not visible on screen.
- RNGH-gesture surfaces (swipe-to-X, drag) can't be exercised via idb — log as
  not-automatable rather than reporting "broken".

## Ground-truth sweep (`product/app_pilot_api.py` — MANDATORY at end of loop, if present)
Screenshots verify rendering; they cannot verify arithmetic. Before §7 Finish,
run **`app-pilot check`** — it asserts the registry in **`product/INVARIANTS.md`**
against the product's ground truth. Exit 1 = one logged finding PER failed
invariant — paste the full output into `findings.md`. (Projects without a
ground-truth layer: the command no-ops; skip this section.)

Additionally, bracket risky actions with the delta probes:
`app-pilot snapshot --out /tmp/before.json` → do the action in the app →
`app-pilot diff /tmp/before.json --expect-new 1` (exactly-one-created / status
transitions / nothing-ever-disappears). The double-submit probe (rapid
double-tap on a submit control) is `--expect-new 1` — two new rows = a real bug.

**Seeded data is static — write paths are only under test when the round
CREATES something.** `app-pilot check` prints a coverage line and warns when nothing
was live-created — every find-and-fix round should drive at least one create
or cancel through the app so the invariants also run against rows the
production write path just produced.

When a triaged failure turns out to be the CHECKER's fault (over-strict rule,
wrong field), fix `product/app_pilot_api.py` AND its row in `product/INVARIANTS.md`
together — the registry must always match the implementation.

## Cleanup
`app-pilot stop` (kill the tester's Metro + crash stream) · `app-pilot status` · then your
own dev server. Run output: `runs/<timestamp>__<scope>/` (gitignored).
