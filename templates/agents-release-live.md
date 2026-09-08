<!--
  Canonical source of the LIVE `release-state` AGENTS block.

  `app-pilot inject-rules` renders this into a project's AGENTS.md (between the
  BEGIN/END markers) when `RELEASE = "live"` in the rig's
  scripts/app-pilot/target.py; its sibling agents-release-pre-release.md is the
  default "pre-release" variant. Idempotent. A hand-pasted copy of this rule
  OUTSIDE the markers is left alone (reported) — delete it so the managed block
  is the only copy.

  Edit HERE (the source) — never hand-edit the copy inside a project's AGENTS.md;
  a refresh would overwrite it.

  Generic + public by design: no project, machine, secret, or personal
  specifics. The compatibility stance is a property of the app, read from its
  own target.py — this template knows nothing about any external system.
-->

<!-- BEGIN:release-state -->
## Release state: LIVE (managed by app-pilot — do not hand-edit this block)

This app is **live**: real users run it, so **compatibility binds**.

- Migrations are forward-only; data shapes users already hold are preserved.
- No breaking schema/shape changes to shipped data — add, don't rewrite.
- Merges land only after the owner's own testing.

Source of truth: `RELEASE = "live"` in `scripts/app-pilot/target.py`. Set it back to `"pre-release"` only if the app returns to pre-release, then re-run `app-pilot inject-rules`.
<!-- END:release-state -->
