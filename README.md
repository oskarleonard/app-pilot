# app-pilot — agent-driven QA engines (iOS simulator + web)

Reusable "eyes & hands" for an AI agent that **operates your running app**:
reads the live accessibility tree, taps/clicks by label, screenshots, hunts
bugs, verifies its own fixes, and asserts backend ground truth the screen
can't show. No pre-written test scripts — the agent explores; these engines
are its deterministic mechanics.

One clone per machine serves every project. Fix a harness bug once, here —
every project picks it up on the next `git pull`. That replaces the old
copy-per-project workflow where improvements died in whichever repo got them.

```
app-pilot/
├── mobile/        # iOS-simulator engine (Expo dev-build apps; simctl + idb)
│   ├── qa         # engine front door (invoked via a project shim)
│   ├── core/      # Metro lifecycle, a11y tap/scroll, crash capture, run bookkeeping
│   ├── RUNBOOK.md # generic operating procedure for the agent
│   └── target.example.py
├── web/           # web engine (agent eyes/hands = the Playwright MCP)
│   ├── qa, core/, RUNBOOK.md, target.example.py
├── missions/      # job briefs the agent runs on the engines (bug-hunt,
│                  #   scenario-exec, ... — schema in missions/_format.md)
├── common/        # shared: publish.py (app-pilot-assets) + targetkit.py (target machinery)
├── templates/     # project shims + _harness.py + product/ layer template
└── PORTING.md     # onboarding a new project + hard-won platform gotchas
```

## The layering contract

The engine is **product-agnostic**. Everything project-specific lives in the
project, layered over the engine through four well-known places in the
project's qa dir (`scripts/app-pilot/` for mobile, `scripts/app-pilot/` for web):

| Layer | File(s) | Required? |
|---|---|---|
| **Pin** | `target.py` (+ gitignored `target.local`) — sim/port/bundle/mode env, server cmd | yes |
| **Ground truth & product brain** | `product/` — `app_pilot_api.py` (`app-pilot check/snapshot/diff`), `INVARIANTS.md`, `FIGMA_MAP.md`, `RUNBOOK.md` addendum (modes, rails, scopes) | no |
| **Project commands** | `ext/<name>{,.py,.sh}` — any extra subcommand (`qa <name>`), e.g. an autoplay layer for timed gameplay | no |
| **Output** | `runs/` (gitignored) | auto |

`product/app_pilot_api.py` owns *whatever* the project's ground truth is — a local
REST backend, SQLite, a state-store dump. The engine only defines the CLI
contract (`check`, `snapshot --out f`, `diff f [--expect-new N]`); without the
file, those commands no-op with a notice.

A team can also keep the product layer in a dedicated repo (e.g. a central
QA-scenario repo) and point `product/` at that checkout — the engine doesn't
care where the dir comes from.

**Missions** sit on top of all of this: `missions/*.md` are job briefs
(bug-hunt, scenario-exec, ...) launched by ~10-line shims in each project's
`.claude/commands/`. One mission, N projects, zero copy drift — see
`missions/_format.md` for the schema and invocation contract.

## Install (once per machine)

```bash
git clone https://github.com/oskarleonard/app-pilot ~/programming/projects/app-pilot
```

Projects resolve the harness in this order:
1. `APP_PILOT_HOME` env var
2. `~/.app-pilot` — a one-line file containing the path
3. `~/programming/projects/app-pilot` (default)

If you cloned elsewhere: `echo /path/to/app-pilot > ~/.app-pilot`.

## Onboard a project (minutes)

1. Copy the shim: `templates/shim-mobile` → `<project>/scripts/app-pilot/app-pilot`
   (or `templates/shim-web` → `<project>/scripts/app-pilot/app-pilot`), `chmod +x`; copy
   `templates/_harness.py` next to it.
2. Copy `mobile/target.example.py` (or `web/`) next to it as `target.py` and
   edit its CONFIG section — values only; the machinery (sim auto-resolve,
   the `--field` CLI) comes from `common/targetkit.py` via `_harness.py`.
3. Gitignore `runs/`, `target.local`, `__pycache__/` in that dir.
4. Optional: add `product/` (start from `templates/product-README.md`) and
   `ext/`.
5. Smoke test: `app-pilot doctor` → `app-pilot serve` → `app-pilot health` → (mobile) `app-pilot tree`.

PORTING.md has the full recipe plus the empirical gotchas that cost a day
each if rediscovered.

## Rules of the repo

- **Nothing product-specific lands here.** Litmus test for every line:
  *would this still make sense for a completely different app?* App names,
  URLs, scope lists, invariant rules, Figma nodes → the project's `product/`.
- **Fix here, not in a project.** If a bug is found mid-QA-run in some
  project, the fix belongs in this repo (commit + push), so every other
  project inherits it.
- Engines per platform stay separate (`mobile/` vs `web/` — different
  mechanics); genuinely shared code goes to `common/`.
