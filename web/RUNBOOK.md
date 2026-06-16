# app-pilot RUNBOOK — how the AI runs a QA round (engine spine)

The **AI drives + evaluates + (by default) fixes**; the Playwright MCP is its
eyes/hands and the project's `scripts/app-pilot/app-pilot` is the bookkeeping. The human says
e.g. *"find and fix bugs in the send flow for 1h"* or *"report only, 30m"*,
then reviews the result. The discipline is identical to the mobile engine's;
the mechanics are web-native.

**Read order for a run: this file → the project's `product/RUNBOOK.md`** (its
tester modes, rails, scopes, static checks) **→ the project's `target.py`**.
Where this spine says "per product", the addendum decides.

## Two modes (what to do with bugs)
- **find-and-fix (default):** find bugs AND fix the ones with a clear,
  verifiable root cause — on a dedicated branch, one commit per fix, ending in
  a PR. Escalate (log only) the ambiguous / architectural ones.
- **report-only:** find + log, no code changes. Triggered by "report only" /
  "just find" / "don't fix".

## Tester modes (which world — target.py MODE)
Defined per product in `product/RUNBOOK.md`. The universal pattern:
- A **local/mock** mode (default): writes are local → exercising real flows is
  allowed AND wanted. Preflight: if the project pins a `BACKEND_URL`, it must
  answer (`app-pilot health` checks; if DOWN, STOP — health prints the start command).
- A **deterministic frontend** mode (MSW or similar), if the product defines
  one: UI/flow/design checks only; ground-truth invariants don't apply.
- A **staging/real** mode, if defined: the tester cannot log in itself (OAuth);
  a human signs in once in the MCP browser session. Rails flip to
  **read-mostly**: never click Send / Confirm / Approve / Submit / Delete.

## Eyes and hands — the Playwright MCP
- `browser_navigate(url)` — go to `app-pilot target --url` + path
- `browser_snapshot()` — the ARIA tree: roles, names, states. Prefer it over
  screenshots for finding things. If you dump a snapshot / ARIA tree (or any
  scratch file) to disk, write it under the active run dir (`runs/<run>/`),
  **never** the repo root or project cwd — stray files there pollute the target
  repo's git status.
- `browser_click` / `browser_type` / `browser_select_option` — by element ref
  from the snapshot (no pixel guessing, no occlusion problem)
- `browser_take_screenshot()` — in-session eyes (use `app-pilot shot <label> <path>`
  instead when you want the image ARCHIVED in the run folder)
- `browser_console_messages()` — **check every iteration**: errors and
  warnings are findings (hydration mismatches especially)
- `browser_network_requests()` — **check every iteration**: 4xx/5xx responses
  the UI swallowed are findings
- **"Occurred" vs "surfaced".** A captured 4xx/5xx means an error *occurred* —
  separate that from whether it was *shown* to the user. Apps usually show feedback
  as **transient toasts that auto-dismiss** (~seconds) in a dedicated region distinct
  from any in-app "notifications"/bell UI. After an action that can fail, snapshot the
  toast region **immediately** (before it dismisses); never conclude "no error shown"
  from one empty region. The project addendum names the app's toast selector.
- `browser_resize(w, h)` — responsive probes

## Run a QA loop
1. **Own the tester server:** `app-pilot serve` → `app-pilot health` (exit 0 = server +
   backend green). Your own dev server is untouched.
2. **(fix mode) Clean tree + branch:** require clean `git status` — if dirty,
   STOP and have the human commit/stash. Then create `qa-auto/<scope>-<STAMP>`
   off the current branch; note the base branch for the PR.
3. **Start a run:** `app-pilot init --scope <scope> --driver <wake|goal> --label <STAMP>`.
4. **Seed `runs/<id>/journal.md`**: mode, tester mode, bound (deadline + a
   step cap), base branch, HARD RULES, nav map, plan. The journal IS the
   loop's state — re-read it every iteration; it survives compaction.
5. **Self-pace** per the invoked skill (`ScheduleWakeup` ≈90s) — or in
   watchdog mode (`/loop 3m /app-pilot <args> --driven`) the harness
   re-fires on a fixed timer even if an iteration crashed; the skill then
   never self-schedules, and post-finish firings are journal-guarded no-ops
   until the loop is cancelled.
6. **Each iteration:** re-read journal FIRST. Then: STEP0 stop-check →
   STEP1 `app-pilot health` → STEP2 `browser_console_messages` +
   `browser_network_requests` (new errors/failed requests = findings) →
   STEP3 snapshot/screenshot → assess → `app-pilot note` bugs → STEP4 (fix mode)
   Fix flow → STEP5 navigate deeper → STEP6 update journal.
7. **Finish (bound reached):** append the final **`## Summary`** section to
   `findings.md` (that exact heading is the completion sentinel). Run the
   product's **ground-truth sweep** first (local mode): `app-pilot check` — each
   failure is a finding. (fix mode) commits exist → push `qa-auto/<...>` +
   open a PR; else report the branch name.

## Scopes
Product-defined — see `product/RUNBOOK.md` for the scope keywords, the route
map, and routing quirks (e.g. slug-scoped routes). Universal rule: derive
routes from the nav in the first ARIA snapshot — don't guess.

## Fix flow (find-and-fix mode, per bug)
1. **Triage:** CODE_BUG (clear, localized → fix) · PLATFORM_LIMITATION
   (needs new dependency, infra, design decision → log + skip) ·
   TEST_ARTIFACT (your own setup/expectation — e.g. backend down, mock
   handler missing → discard, fix the setup).
2. **Fix — strict scope guard:** smallest change, repo style. Fix the buggy
   *pattern* everywhere it repeats, not just one screen.
3. **Verify:** the dev server hot-reloads; re-drive the repro via the MCP;
   confirm gone, console clean, no new failed requests, then the project's
   static checks pass (`product/RUNBOOK.md` names them). Re-check screens
   already PASSed this run — regressions = failed verify.
4. **Commit or revert:** one atomic commit per verified fix. Unverified → revert.
5. **Stuck-loop cap:** max 2 attempts per bug, then escalate as a finding.

## PR evidence for visual fixes (host via `app-pilot publish` — NEVER the PR branch)
A find-and-fix run that changed anything ON-SCREEN should SHOW it in the PR body:
- **Before/after montage per visual fix** — same screen, pre- vs post-fix, side by
  side. **Capture the failing state with an archival `app-pilot shot` when you LOG the
  bug** — that is the before half; `browser_take_screenshot` is in-session only
  and leaves nothing to montage at Finish. `after` = the verified fix after the
  hot reload. Build it with ImageMagick (`magick montage …`) at full res;
  **never downscale the source** (bakes in blur).
- **Host it via `app-pilot publish` — NEVER on the PR/run branch:** `app-pilot publish
  <montage.png> --feature <flow>-<topic> [--caption "…"]`. It appends the PNG
  to the hidden, append-only `refs/app-pilot-assets/store` ref (no branch → no
  "recent pushes" banner, nothing to merge; created/seeded on first use) and
  prints a commit-pinned `<img src="…/blob/<sha>/<feature>/<file>?raw=true"
  width="580">` tag for the PR body. Images share no history with `main` and
  never appear in any branch or Files-changed. **Never `git add` a PNG on the
  run branch** (on squash-merge it lands in `main`).
- **One-line "what changed" caption above each image** so the diff reads at a glance.

**The montage gate is MECHANICAL, not a judgment call** — never infer
visual-vs-logic from a fix's title or category. At Finish, for EVERY committed
fix, compare its before/after pair: `magick compare -metric AE before.png
after.png null:` (or view them side by side). ANY non-zero pixel diff → the
montage is mandatory, even for an "a11y/logic" fix. Only a byte-identical pair
(a truly non-visual fix) skips it — and those cite the ARIA-snapshot diff as
the PR evidence instead. No before shot captured = treat as differing (montage
from the closest available state, and note the gap).

## HARD RULES (non-negotiable)
- **Branch isolation:** fixes land on `qa-auto/<stamp>` only; never commit to
  the human's branch. **Verify-or-revert.** **≤2 attempts per bug.**
- **Console + network sweep every iteration** — a clean-looking screen with a
  500 in the network log is a finding, not a pass.
- **Navigate via the ARIA snapshot** (roles/names), not coordinates. An
  element you can't address by role/name is itself an accessibility finding.
- **Money/destructive-flow audit (local mode):** before EVERY click on a
  Confirm/Send/Approve/Submit-style control: `app-pilot shot` + `app-pilot act CONFIRM <what>`.
  In staging those clicks are FORBIDDEN. Product rails: `product/RUNBOOK.md`.
- **Ground-truth sweep before Finish (local mode, if the product has one):**
  `app-pilot check` (registry: `product/INVARIANTS.md`). Bracket risky actions with
  `app-pilot snapshot` / `app-pilot diff --expect-new N` (double-submit probe).
- **Recovery hierarchy:** in-app navigation → `browser_navigate` back to a
  known route → page reload → `app-pilot serve` (server restart) last.
- **Image-processing error = stop the loop (cost hazard, never self-heals in-session).**
  If the console shows `API Error: an image in the conversation could not be processed
  and was removed`, or a screenshot read comes back with no image, an oversized
  image (>2000px on a side — the model API's cap once a conversation carries
  many images) is in the history. ONE such image poisons every later image
  read in the session, including already-sent ones, and every strip-and-retry
  invalidates the prompt cache, so all remaining turns bill at near-full price.
  Do NOT keep QA-ing through it and do NOT retry the read — write current state
  to `findings.md`, end the session, resume fresh. Web-specific prevention:
  archival `app-pilot shot` images are FULL-PAGE (long routes blow past 2000px tall)
  and belong in the run folder, NOT in the conversation — use the MCP's
  viewport-sized `browser_take_screenshot()` for in-session eyes, and read
  archived shots / montages / Figma exports only via a `sips -Z 1800` copy.
- **No new dependencies / installs** in the loop — log instead.
- Self-recover (`app-pilot health` / `app-pilot serve`), don't ask.

## Active bug-hunt checklist (probe, don't just happy-path)
At least 1-2 per round: console-error sweep on every route visited ·
failed/4xx/5xx network responses the UI swallowed · hydration-mismatch
warnings · forms: invalid amounts (0, negative, huge, `1,23`), required-empty,
rapid double-submit · cross-path consistency (same entity via two routes) ·
empty vs populated states · responsive breakpoints (`browser_resize`
375/768/1440) on key screens · keyboard nav + focus visibility on one flow per
round · query-cache staleness (mutate, check other screens reflect).

## Design verification (on demand — `product/FIGMA_MAP.md`)
`/check-figma <screen> [--strict]`: resolve the node in the product's
FIGMA_MAP.md, fetch the Figma render (MCP `get_screenshot` → curl into
`runs/<id>/figma/`), capture the app at the same route + viewport (`app-pilot shot`),
judge structure+tokens by default. Strict mode may MEASURE (computed styles vs
Figma variables) — see FIGMA_MAP.

## Limits
- The wake loop is session-scoped (terminal open, Mac awake).
- Deterministic-frontend mode: no backend behavior under test; staging: read-only.
- A fresh `app-pilot shot` context sees mock-auth states only — staging screenshots
  must come from the MCP's logged-in session.

## Cleanup
`app-pilot stop` · run output in `runs/<timestamp>__<scope>/` (gitignored).
