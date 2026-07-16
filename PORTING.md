# Onboarding a project (and the gotchas that cost a day each)

The engines are project-agnostic; onboarding = writing the project layer.
Read the engine's `README.md` + `RUNBOOK.md` first — they carry ~80% of the
operating knowledge. This file carries the rest: what a project writes, the
per-app values, and the empirical platform gotchas.

## What a project writes vs gets for free

| Piece | Action |
|---|---|
| Engine (`mobile/core` or `web/core` + dispatcher) | **Free.** Lives in this repo; never copy it into a project. |
| `scripts/.../app-pilot` shim + `_harness.py` | Copy both from `templates/` (never edited). |
| `target.py` | **Write per project** from `target.example.py` — the CONFIG section only; the machinery (UDID auto-resolve + `target.local` pin, `--field` CLI) comes from `common/targetkit.py`. See "Per-app values". |
| `product/` (app_pilot_api.py + INVARIANTS.md + FIGMA_MAP.md + RUNBOOK addendum) | **Re-derive per product** — this asserts THIS app's ground truth and rails. Port the *pattern* (see "Ground-truth layer"), never the rules. |
| `ext/` | Only if the project needs extra mechanics (e.g. an autoplay layer for timed gameplay — sub-3s response windows an LLM can't keep up with live). |
| `.claude/commands/app-pilot*.md` | Thin per-project pointers: "follow the engine RUNBOOK + product/RUNBOOK.md". The Rails sections are the per-app customization point. |
| `AGENTS.md` `app-pilot-rules` block | `app-pilot inject-rules` (or `python3 <engine>/common/inject_rules.py <dir>` for a rig-less repo) inserts/refreshes the block from `templates/agents-app-pilot-rules.md` into the project's `AGENTS.md` — **idempotent**. Single source of truth (screenshots → `publish`, never commit); edit the template + re-run, never the project copy. AGENTS.md must be canonical first (`CLAUDE.md` = `@AGENTS.md`). |

## Per-app values (target.py)

Mobile:
- `DEVICE_NAME` — the sim model to auto-discover on first run; **the durable
  pin is the UDID in `target.local`** (model names duplicate across iOS
  runtimes and rot when sims are recreated — never treat the name as the
  key). Orchestrators aim any rig at a specific sim via the uniform
  `APP_PILOT_UDID`; the rig's own `UDID_ENV` wins over it (deliberate narrow
  override beats fleet plumbing).
- `PORT` — distinct from the app's dev Metro AND every other tester; use
  `targetkit.tester_port(<default>)` so pooled/lane runs override it
  uniformly via `APP_PILOT_PORT`. On a machine shared by multiple agent
  systems, allocate the number from a machine-level map (e.g. a
  `machine.json` both systems read at build time) instead of by convention.
- `BUNDLE` + `SCHEME` — from `app.config.ts` (dev-flavor bundle id; URL scheme
  for dev-client deep links).
- `TAB_ORDER` — read the live a11y tree (`app-pilot tree`), don't guess.
- `LAUNCHER_LABELS` — strings distinctive of the Expo dev-launcher AND the
  dev-client error screen ("there was a problem loading the project",
  "failed to load app").
- `APP_LABELS` — **strongly recommended** — a11y label(s) visible ONLY inside
  your app's running UI (an in-app tab title / header / content string). With it,
  `health`/`recover` report `app` only when one is visible, so a missed launch
  reads `unknown` instead of a false `app`. Unset = the old optimistic default
  (can't positively confirm your app). **MUST be app-exclusive:** never an iOS
  system-app name (`Settings`/`Home`/`Safari`) nor your app's own display name —
  those also label home-screen icons, so a missed launch would still match one
  and falsely PASS (label-grep can't distinguish that case; a frontmost-bundle-id
  probe would, but idb exposes none today — follow-up).
- `SPRINGBOARD_LABELS` — iOS home-screen signal; default `["safari"]` (a brand
  name, so locale-safe). Matched as an **exact icon label** (tolerant of a `", N
  new items"` badge), so an in-app "Open in Safari" button isn't mistaken for the
  home screen. Checked BEFORE `APP_LABELS` so a detected home screen wins. Override
  only if your own UI shows an exact "Safari" label. NOTE the trade: a legacy rig
  (no `APP_LABELS`) whose UI shows an exact "Safari" label now reads `springboard`
  (a false FAIL — re-check; safer than a false PASS).
- `LOG_PROCESS_HINT` — substring of the app's process name (crash-log predicate).
- `/tmp/<project>-tester-*` artifact paths — **namespace per project**.
- `MODE`/`METRO_ENV` — the app's own mock/dev flags. Gotcha: Expo's dev
  transform spreads `.env*` files OVER inline env — flag vars must have NO
  `.env*` entry to propagate.
- Optional: `BACKEND_URL` (health/doctor ping it; omit/None = no backend),
  `BACKEND_HINT` (the fix command printed when it's down).

Web:
- `TESTER_PORT` — never your dev port; `APP_URL`. Use
  `targetkit.tester_port(<default>)` — pooled/isolated runs override via
  `APP_PILOT_PORT`, a plain run keeps the pin.
- `MODE`/`MODE_ENV` — the app's msw/mock-auth envs per mode.
- `SERVER_CMD` (argv, default `["bun", "run", "dev"]`; `PORT` env is set for
  you) + `SERVER_CWD` (monorepo subdir, default repo root).
- `SERVER_LOG`/`PIDFILE` — namespace per project.
- Optional: `BACKEND_URL`/`BACKEND_HINT` as above.
- Headless: `app-pilot shot` is always headless. The agent's live eyes are the
  Playwright MCP — toggle headless in the project's `.mcp.json` args.

### Web gotcha — Next 16 allows ONE dev server per project dir

A second `next dev` (the tester's) boots, detects the developer's instance,
and self-terminates ("Another next dev server is already running"). Fix: a
distDir env hook in the app's `next.config` —
`distDir: process.env.NEXT_DIST_DIR || ".next"` — plus
`MODE_ENV = {"NEXT_DIST_DIR": ".next-qa"}` in target.py (gitignore
`.next-qa/`). Without the hook, the tester only runs while the dev server is
down.

## Empirical gotchas — mobile/iOS (don't relearn these)

1. **idb rejects `"booted"` as a UDID** — pass the real UDID (`simctl`
   accepts the alias; `idb` errors "Cannot spawn companion for booted").
2. **Synthesized taps lose to react-native-gesture-handler** — gorhom
   backdrop-tap/drag-down never fire. Sheets need a labelled escape: an
   in-flow gorhom `TouchableOpacity` (NOT RN Pressable — a11y sees it but
   onPress never fires inside the sheet's gesture context; NOT
   position:absolute — same failure; NOT opacity:0 — iOS drops alpha=0 from
   the a11y tree). Gate it on a tester env var your `METRO_ENV` sets.
3. **Gorhom's container is accessible-by-default** (role 'adjustable') — it
   collapses ALL sheet content out of the a11y tree. `accessible={false}`
   on the container un-collapses.
4. **iOS 26 NativeTabs**: items don't appear in `describe-all` (only a 'Tab
   Bar' group), and the group frame is FULL-WIDTH while the visual pill is
   centered/narrower — naive segment math taps empty glass. `core/idb_ui.py`
   probes via `describe-point` (already handled; keep it).
5. **a11y frames are viewport-relative** — `y<0` scrolled past, `y>screen`
   below the fold, tab-bar band occluded. Core's tap guardrail enforces this.
6. **Light-themed apps break pixel-based app detection** — `app_state()`
   greps the a11y tree (`LAUNCHER_LABELS` / `APP_LABELS` / `SPRINGBOARD_LABELS`)
   instead. Pin `APP_LABELS` so a frontmost app is confirmed POSITIVELY — without
   it a silently-failed launch (home screen) can read as a false `app`. The
   `APP_LABELS` you pin must be app-EXCLUSIVE (see "Per-app values"): a
   system-app name or your app's display name also labels a home-screen icon, so
   it would still match a missed launch.
7. **The Simulator can be headless** — `simctl`/`idb` work with the window
   hidden/unfocused/on another Space.
8. **First boot after adding a JS dep may crash native** — transitive NATIVE
   modules are NOT autolinked. A `NativeModule: X is null` red box right
   after onboarding is the app's dependency gap, not the tester's fault.
9. **Stale ESLint cache after npm install** — import/no-unresolved ghosts;
   clear the app's ESLint cache.
10. **`simctl openurl` pops an "Open in <app>?" confirm** when invoked from
    outside the app — core auto-approves it; budget polls for slow dialogs.

## Ground-truth layer (`product/app_pilot_api.py`) — port the pattern, not the file

1. Find the app's ground truth (local BE REST, SQLite, a store dump, …). If
   only a remote prod API exists, this layer may not apply — that's fine;
   `app-pilot check` no-ops without the file.
2. Read the schema/serving code FIRST and classify: **real invariants** =
   denormalized state that can drift (counters incremented in place, soft
   references with no FK, pagination merges); **tautological** = computed on
   read (asserting those is worthless — document them so nobody re-adds them).
3. One registry file (`product/INVARIANTS.md`) = IDs + rules + evidence; the
   checker implements exactly the registry; fix both together or neither.
4. Make checks **mode-aware** and report **seeded-vs-live coverage** (a sweep
   over fixtures only exercises read paths — warn when the round created
   nothing).
5. `snapshot`/`diff` delta probes around risky actions (exactly-one-created,
   nothing-ever-disappears, double-submit).

## Not portable, fundamentally

- Invariant rules, scope keywords, rails, TAB/launcher label sets — per app.
- The app's a11y-label conventions — the tester is only as good as the app's
  `accessibilityLabel` coverage (an unfindable element is itself a finding).
- Timed gameplay (sub-3s windows) needs a project `ext/` autoplay layer —
  deliberately not in the engine.

## Smoke test for a fresh onboarding

```bash
scripts/app-pilot/app-pilot doctor      # every FAIL prints its fix; resolves + pins the sim
scripts/app-pilot/app-pilot serve       # owns Metro/dev server, force-reloads the app
scripts/app-pilot/app-pilot health      # exit 0 = all green
scripts/app-pilot/app-pilot tree        # (mobile) labelled elements visible?
scripts/app-pilot/app-pilot init --scope all --label onboarding-smoke
scripts/app-pilot/app-pilot shot home
scripts/app-pilot/app-pilot stop
```

All green → wired. Expect the smoke test itself to surface real app bugs —
prior onboardings found shipping issues on day one.
