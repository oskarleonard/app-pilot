# sim-qa — command cheatsheet (mobile engine)

One front door per project: **`scripts/sim-qa/qa <command>`** (a shim into
this engine). Layers: **`core/devserver.py`** (Metro / app lifecycle + crash
capture), **`core/qa.py`** (run journal + screenshot + log), **`core/idb_ui.py`**
(tap by accessibility label). Design: `README.md`. Procedure: `RUNBOOK.md`.

## Lifecycle — the commands you run by hand

| Command | Does |
|---------|------|
| `qa doctor`  | First-time machine check (sim, idb, app build, backend) — every FAIL prints its fix |
| `qa serve`   | Take over Metro on the tester port (owned + logged), start crash stream, force-reload the app from THIS Metro |
| `qa health`  | Metro up? backend up (if pinned)? app vs launcher? idb companion? |
| `qa status`  | What holds the port, the tester's pid, log sizes |
| `qa recover` | Reconnect the app; restart Metro if down; **respawn the idb companion if dead** |
| `qa reload`  | Fallback reload (terminate + relaunch) when Fast Refresh doesn't apply — LAST resort |
| `qa logs [N]`    | Last N lines of the owned Metro log (JS warns/console/bundling) |
| `qa crashes [N]` | Crash-pattern hits from the OS log stream (native/red-box/fatal) |
| `qa stop`    | Kill the tester's Metro + crash stream (scoped to the tester port) |

> After `qa stop`, start your own Metro again and reopen the app from it.

## Eyes & hands — the QA loop runs these

```bash
qa init --scope <scope> [--driver wake|goal] [--label L]   # → run dir (scopes: product-defined)
qa shot <label>                               # screenshot + center RGB log
qa tree                                       # labelled a11y elements (what's tappable)
qa tap --label "AXLabel" [--role R] [--force] # tap by a11y label (refuses off-viewport/occluded; --force overrides)
qa tap --tab <name>                           # tap a bottom tab (target.py TAB_ORDER)
qa tap --frac 0.5,0.85                        # fraction fallback for unlabelled targets
qa type <text> [--label L] [--role R] [--clear] [--enter]
qa scroll [down|up] [--amount 0.35]           # scroll native lists (off-viewport frames refuse taps)
qa note <finding text>                        # append to findings.md
qa act <audit text>                           # append to actions.log
qa find <label>                               # locate without tapping
qa companion [ensure]                         # idb companion check / respawn
```

## Ground truth — logic bugs the screen can't show

```bash
qa check                          # assert the product's invariant registry (exit 1 on fail)
qa snapshot --out /tmp/b.json     # snapshot state before a risky action
qa diff /tmp/b.json --expect-new 1  # delta probes (double-submit detector)
```

Delegated to the project's `product/qa_api.py`; registry + rules in
`product/INVARIANTS.md`. Without that layer these commands no-op.
Run `check` at the end of every QA loop (RUNBOOK has the full procedure).

## PR evidence

```bash
qa publish <img.png> --feature <slug> [--name F] [--caption "…"] [--width N]
```

Hosts the image on the repo's append-only `qa-assets` orphan branch (created
on first use) and prints the `<img>` tag for the PR body — montages never
touch the PR branch or `main`. See RUNBOOK "PR evidence".

## Design verification — screen vs Figma (on demand)

```text
/check-figma <screen> [state] [--strict]
```

Registry + full procedure: the project's **`product/FIGMA_MAP.md`**
(screen→node mapping, version pointers, accepted deviations). Default mode
judges structure + tokens — live data is never a finding; `--strict` adds
px-level nits at a higher false-positive rate.

## Modes & process hygiene

- Modes are project-defined in `target.py` (env-switched; see the project's
  `product/RUNBOOK.md` for what each mode means and its rails).
- The tester is **pinned** in `target.py` (sim UDID via `target.local`, Metro
  port, bundle, tab order). It only ever touches that sim/port.
- Owned-process artifacts (pid/log files) are the `/tmp/...` paths named in
  `target.py` — namespaced per project.
- See/kill lingering manually: `lsof -ti tcp:<port>` · `qa stop`.
- Run outputs live under the project's `runs/<timestamp>__<scope>/` (gitignored).
