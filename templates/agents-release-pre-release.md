<!--
  Canonical source of the PRE-RELEASE `release-state` AGENTS block.

  `app-pilot inject-rules` renders this into a project's AGENTS.md (between the
  BEGIN/END markers) when `RELEASE` in the rig's scripts/app-pilot/target.py is
  absent or "pre-release"; its sibling agents-release-live.md is the "live"
  variant. Idempotent. A hand-pasted copy of this rule OUTSIDE the markers is
  left alone (reported) — delete it so the managed block is the only copy.

  Edit HERE (the source) — never hand-edit the copy inside a project's AGENTS.md;
  a refresh would overwrite it.

  Generic + public by design: no project, machine, secret, or personal
  specifics. The compatibility stance is a property of the app, read from its
  own target.py — this template knows nothing about any external system.
-->

<!-- BEGIN:release-state -->
## Release state: PRE-RELEASE (managed by app-pilot — do not hand-edit this block)

This app is **pre-release**: nobody but its owner runs it, so there is **no backward compatibility to keep**. Do NOT write compatibility code.

- No legacy fallbacks, id aliases, or old-shape readers — change the shape and fix every caller.
- No compat-preserving schema/export bumps, and no migrations that keep unshipped data.
- Change the shape, fix every caller, delete the dead path; dev data is wipe-and-reinstall.

Source of truth: `RELEASE` in `scripts/app-pilot/target.py` (absent = pre-release). Flip it to `"live"` once the app ships to real users, then re-run `app-pilot inject-rules`.
<!-- END:release-state -->
