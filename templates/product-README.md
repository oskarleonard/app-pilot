# product/ — the project's QA brain (template)

Everything the engine must NOT know about your product lives here, next to
the shim. All files optional; add what the project has.

```
product/
├── RUNBOOK.md      # addendum the agent reads AFTER the engine RUNBOOK:
│                   #   - tester modes: what each MODE means for THIS app,
│                   #     auth stubbing, what's a no-op, recovery quirks
│                   #   - rails: money/destructive-flow rules per mode
│                   #   - scopes: keyword → surfaces table
│                   #   - static checks: the exact commands a fix must pass
│                   #     (e.g. `npm run check`, `bun run typecheck`)
│                   #   - app-specific labels (e.g. a tester-escape button)
├── app_pilot_api.py       # ground truth: implements `check`, `snapshot --out f`,
│                   #   `diff f [--expect-new N]` against WHATEVER the truth
│                   #   source is (local REST backend, SQLite, store dump).
│                   #   `app-pilot check/snapshot/diff` route here automatically.
├── INVARIANTS.md   # living registry the checker implements 1:1 —
│                   #   IDs + rules + evidence; fix both together or neither
└── FIGMA_MAP.md    # design-verification registry for /check-figma:
                    #   screen → node-id, version pointers, accepted deviations
```

A team can keep this layer in a central QA repo instead and check it out
here (or symlink it) — the engine only cares that the files exist at
`<qa dir>/product/`.
