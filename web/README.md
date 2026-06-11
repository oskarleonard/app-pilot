# web-qa — agent-driven QA for web apps (web engine)

Lets the AI **see and drive a web app in a real browser**, verify its own
changes, run autonomous QA rounds, assert ground-truth invariants the UI can't
show, and compare screens against Figma. Same discipline as the mobile engine;
the simulator-specific eyes/hands are replaced by the **Playwright MCP**,
which is strictly better on web: real ARIA tree, native console + network
introspection, no gesture-system workarounds.

## One-time setup (per developer, per project)

The agent's eyes/hands need the Playwright MCP in the project. Pin
`@playwright/mcp` as a devDependency and add `.mcp.json` at the project root
(keep it per-person if the team prefers):

```json
{
  "mcpServers": {
    "playwright": {
      "command": "node_modules/.bin/playwright-mcp",
      "args": ["--browser", "chromium", "--viewport-size", "1440,900"]
    }
  }
}
```

Restart the Claude session afterwards; the `browser_*` tools appear.
**Headless:** add `"--headless"` to the args when you don't want to watch it
test (per project — e.g. on for utility projects, off when you like seeing
the run). `qa shot` archival screenshots are headless regardless.

## How an onboarded project looks

```
<project>/scripts/qa/
├── qa                   # shim → this engine (templates/shim-web)
├── target.py            # the pin: tester port, mode env, server cmd/cwd
├── product/             # optional: qa_api.py + INVARIANTS.md + FIGMA_MAP.md
│                        #           + RUNBOOK.md addendum (modes/rails/scopes)
├── ext/                 # optional: project-specific subcommands
└── runs/                # per-run output (gitignored)
```

## The division of labor

- **Playwright MCP** = live eyes/hands: navigate, click by role/name, type,
  read the ARIA snapshot, read console messages + network requests,
  screenshot the live session.
- **`scripts/qa/qa`** = everything around it: the pinned tester server (your
  own dev server is never touched), the compaction-proof run journal + audit
  log, archival full-page screenshots, the ground-truth sweep, and qa-assets
  publishing for PR evidence.

## Guardrails (non-negotiable)

- The tester owns ONLY its pinned port — never kills your dev server.
- Money/destructive flows: per the product rails (`product/RUNBOOK.md`);
  universal minimum — every confirm is logged (`qa act`) + screenshotted.
  Forbidden in staging-style modes.
- Console-error and failed-request sweeps are part of every QA iteration —
  see RUNBOOK.md.
