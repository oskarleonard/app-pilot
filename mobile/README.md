# sim-qa — simulator eyes & hands for the AI (mobile engine)

Lets the AI **see and drive an iOS simulator**: screenshot → read the a11y
tree → tap by accessibility label → drive flows. The human says *"QA the send
flow for 1h, find and fix bugs"*; the AI drives + evaluates + fixes on a
branch → PR.

The **AI drives + evaluates** (decides what to test, judges screenshots,
writes findings); the scripts are **dumb mechanics** (screenshot / tap / log /
Metro lifecycle). Tooling: `xcrun simctl` + `idb`. Works with Expo dev-build
apps.

## First-time setup (per machine)

```bash
brew tap facebook/fb && brew install idb-companion        # native daemon
python3 -m venv ~/.idb-venv && ~/.idb-venv/bin/pip install fb-idb   # idb CLI
<project>/scripts/sim-qa/qa doctor                        # checks everything;
                                                          # every FAIL prints its fix
```

> `idb` will NOT be on your PATH (`zsh: command not found: idb` is expected) —
> the venv keeps it isolated and the tooling calls it by absolute path
> (pinned in the project's `target.py`). `qa doctor` verifies the location.

`doctor` also resolves the project's simulator: the target device
(`DEVICE_NAME` in `target.py`) is discovered on first run — preferring a
booted one, then the newest iOS — and pinned to the gitignored `target.local`,
so the choice is stable per machine forever after. To retarget: delete
`target.local` (re-discovers) or write a UDID into it.

## How an onboarded project looks

```
<project>/scripts/sim-qa/
├── qa                   # shim → this engine (templates/shim-mobile)
├── target.py            # the project's pin (sim / port / bundle / mode env)
├── target.local         # per-machine UDID pin (gitignored, auto-written)
├── product/             # optional: qa_api.py + INVARIANTS.md + FIGMA_MAP.md
│                        #           + RUNBOOK.md addendum (modes/rails/scopes)
├── ext/                 # optional: project-specific subcommands
└── runs/                # per-run output (gitignored)
```

The engine itself (this folder: `core/`, the dispatcher, this README,
RUNBOOK.md) is shared by every project — fix things HERE.

## Pinning — parallel testers coexist

`target.py` pins the tester to **one sim model + one Metro port**, per
project. Different projects use different sims + ports, and your own dev
Metro keeps its port — they all coexist. The tester never kills Metro on
another port or drives another sim.

The tester **repoints the installed dev app** to its own Metro via a
dev-client deep link. To get your own dev session back afterwards: `qa stop`,
then start your own Metro and reopen the app from it.

## QA loop — model-driven, compaction-proof

- `core/qa.py` = deterministic mechanics + logging (cheap, no model).
- The model decides what to test, VIEWS select screenshots, writes findings,
  updates the journal — paced by `/qa-tester-wake` (ScheduleWakeup) or
  `/qa-tester` (/goal), defined per project in `.claude/commands/`.
- **State lives on disk** (`runs/<id>/journal.md`), re-read each iteration, so
  a mid-run context compaction is survivable. See RUNBOOK.md.

## Guardrails (non-negotiable)

- **Verify-before-act**: screenshot + confirm the screen before tapping.
- **Money/destructive flows**: per the product's rails (`product/RUNBOOK.md`);
  universal minimum — every Confirm/Send/Approve is logged + screenshotted.
- **Full audit**: every action lands in `actions.log` + a screenshot.

## Cost

Saving screenshots is free (local I/O); the model *viewing* them costs tokens.
The loop stays cheap by using the logged `center_rgb` signal for routine steps
and only viewing screens that look off or are key.
