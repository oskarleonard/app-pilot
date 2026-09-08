<!--
  Canonical source of the `release-state` AGENTS block — the single source of
  truth for app-pilot's compatibility-stance rule.

  Two variants below (PRE-RELEASE / LIVE). `app-pilot inject-rules` renders the
  one that matches `RELEASE` in the rig's scripts/app-pilot/target.py (absent =
  pre-release) into the project's AGENTS.md, between the BEGIN/END markers, next
  to the app-pilot-rules block. Idempotent. A hand-pasted copy of this rule
  OUTSIDE the markers is left alone (reported) — delete it so the managed block
  is the only copy.

  Edit HERE (the source) — never hand-edit the copy inside a project's
  AGENTS.md; a refresh would overwrite it.

  Generic + public by design: no project, machine, secret, or personal
  specifics. The compatibility stance is a property of the app, read from its
  own target.py — this template knows nothing about any external system.
-->

<!-- VARIANT:pre-release -->
<!-- BEGIN:release-state -->
## Release state: PRE-RELEASE (managed by app-pilot — do not hand-edit this block)

This app is **pre-release**: nobody but its owner runs it, so there is **no backward compatibility to keep**. Do NOT write compatibility code.

- No legacy fallbacks, id aliases, or old-shape readers — change the shape and fix every caller.
- No compat-preserving schema/export bumps, and no migrations that keep unshipped data.
- Change the shape, fix every caller, delete the dead path; dev data is wipe-and-reinstall.

Source of truth: `RELEASE` in `scripts/app-pilot/target.py` (absent = pre-release). Flip it to `"live"` once the app ships to real users, then re-run `app-pilot inject-rules`.
<!-- END:release-state -->
<!-- /VARIANT:pre-release -->

<!-- VARIANT:live -->
<!-- BEGIN:release-state -->
## Release state: LIVE (managed by app-pilot — do not hand-edit this block)

This app is **live**: real users run it, so **compatibility binds**.

- Migrations are forward-only; data shapes users already hold are preserved.
- No breaking schema/shape changes to shipped data — add, don't rewrite.
- Merges land only after the owner's own testing.

Source of truth: `RELEASE = "live"` in `scripts/app-pilot/target.py`. Set it back to `"pre-release"` only if the app returns to pre-release, then re-run `app-pilot inject-rules`.
<!-- END:release-state -->
<!-- /VARIANT:live -->
