<!--
  Canonical source of the `app-pilot-rules` AGENTS block — the single source of
  truth for app-pilot's project-agent conventions.

  It is injected verbatim (the BEGIN…END block below) into each project's
  AGENTS.md, so the rules stay uniform across every project that uses app-pilot.
  Today that injection is a manual copy; a future `app-pilot` injector will
  refresh it in place. Edit HERE (the source) — never hand-edit the copy inside a
  project's AGENTS.md; a refresh would overwrite it.

  Generic + public by design: no project, machine, secret, or personal
  specifics. Those live in the project's own (unmanaged) AGENTS.md sections.
-->
<!-- BEGIN:app-pilot-rules -->
## QA & visual evidence (managed by app-pilot — do not hand-edit this block)

- **Screenshots / before-after montages → `scripts/app-pilot/app-pilot publish <img> --feature <slug>`; NEVER commit them.** `publish` hosts the image on the hidden, append-only `refs/app-pilot-assets/store` ref (no branch → no "Compare & pull request" banner, nothing to merge) and prints a commit-pinned `<img>` tag to paste into the PR body. Committing a PNG to a PR branch lands it in `main` on squash-merge — that's the exact failure mode this prevents.
- **A UI "it works" claim requires shown evidence, not code-reading** — a published screenshot or a rig run (`scripts/app-pilot/app-pilot …`). "Looks right in the source" is not verification.
<!-- END:app-pilot-rules -->
