# web-qa — command cheatsheet (web engine)

One front door per project: **`scripts/qa/qa <command>`** (a shim into this
engine). The agent's live eyes/hands are the **Playwright MCP** (`browser_*`
tools — setup in README.md). Operating procedure: RUNBOOK.md.

## Tester server (pinned port — your dev server is never touched)

| Command | Does |
|---------|------|
| `qa serve`  | Start the tester's dev server in the active mode (exit 1 if it never comes up) |
| `qa health` | Server up? Backend up (if the project pins one)? Exit 1 when anything is down |
| `qa status` | Pid, port holders, log size |
| `qa logs [N]` | Last N lines of the tester server log (compile errors live here) |
| `qa stop`   | Kill the tester's server (this port only) |

Modes are project-defined in `target.py` (env-switched — see the project's
`product/RUNBOOK.md`).

## Run bookkeeping + archival evidence

```text
qa init --scope <scope> [--driver wake|goal] [--label L]   # scopes: product-defined
qa shot <label> [path]     # full-page screenshot of APP_URL+path into the run
                           # (fresh headless context — mock modes only; staging
                           # uses the MCP's in-session browser_take_screenshot)
qa note <finding text>
qa act <audit text>
```

## Ground truth — logic bugs the screen can't show (local mode)

```text
qa check                          # assert the product's invariant registry
qa snapshot --out /tmp/b.json     # snapshot state before an action
qa diff /tmp/b.json --expect-new 1  # delta probes (double-submit detector)
```

Delegated to the project's `product/qa_api.py` (no-op without one).
Registry: `product/INVARIANTS.md`.

## PR evidence

```text
qa publish <img.png> --feature <slug> [--caption "…"]   # → qa-assets branch + <img> tag
```

## Design verification — screen vs Figma (on demand)

```text
/check-figma <screen> [--strict]
```

Registry + procedure: the project's **`product/FIGMA_MAP.md`**.

## Playwright MCP quick reference (the agent's hands)

| Tool | Use |
|---|---|
| `browser_navigate` | open `qa target --url` + path |
| `browser_snapshot` | ARIA tree — roles/names/states; prefer over pixels |
| `browser_click` / `browser_type` | act on snapshot element refs |
| `browser_console_messages` | EVERY iteration — errors/warnings are findings |
| `browser_network_requests` | EVERY iteration — swallowed 4xx/5xx are findings |
| `browser_take_screenshot` | in-session eyes (archival → `qa shot`) |
| `browser_resize` | responsive probes (375 / 768 / 1440) |

## Process hygiene

- Tester server pid/log: the `/tmp/...` paths named in `target.py`
  (namespaced per project).
- See/kill manually: `lsof -ti tcp:<port>` · `qa stop`.
- Run outputs live under the project's `runs/<timestamp>__<scope>/` (gitignored).
