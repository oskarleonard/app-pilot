# missions/ — the format

A **mission** is a markdown brief the agent reads and follows: one job
description running on the shared engine ("hands and eyes"). The engine
RUNBOOK says HOW to operate the app; the project's `product/RUNBOOK.md` says
what's TRUE for this app; the mission says WHAT TO DO and when it's done.
Missions version with the engine — same repo, same reason the RUNBOOK does.

## Invocation contract

Missions are launched by a ~10-line **shim** in each project's
`.claude/commands/` (or any prompt that supplies the same three things):

- **driver** — `wake` (ScheduleWakeup self-pacing) or `goal` (/goal Stop-hook
  pacing). Missions define behavior per driver; shims hardcode one each.
- **adapter dir** — the project's app-pilot layer (`scripts/app-pilot/`):
  `target.py` (pin) · `product/` (truth, rails, registries) · `ext/` ·
  `runs/`. Every project-specific fact the mission needs resolves here.
- **request** — the user's free-text arguments (`$ARGUMENTS`).

Read order at launch: this mission → the engine RUNBOOK
(`<harness>/{mobile,web}/RUNBOOK.md`) → the adapter's `product/RUNBOOK.md` →
`target.py`.

## Schema — every mission has exactly these sections

| Section | Contract |
|---|---|
| **Goal** | One paragraph: the job and its deliverable. |
| **Input source** | What the mission consumes — ALWAYS parameters supplied by the invoker/adapter, never hardcoded. A corpus path, a backlog file, a scenario id. External trackers (Linear, Notion, GitHub issues) never appear in a mission — an adapter may feed from them and hand the mission a local file/path. |
| **Done-criteria** | The exact conditions that end the run (the completion sentinel, bounds, per-item verdicts). Never open-ended. |
| **Rails** | The mission's non-negotiables, layered ON TOP of the engine RUNBOOK's HARD RULES and the adapter's product rails — a mission may tighten rails, never loosen them. |
| **Options** | Named flags with defaults. Options are **generic hooks**: the flag's meaning is defined here; its implementation is the adapter's (e.g. `check_figma: on` means "run the adapter's figma-check procedure if it defines one; absent → log a notice and continue"). |

Optional extra sections (after the schema ones): **Procedure** (numbered
steps), **Driver: wake / Driver: goal** (pacing specifics), **Watchdog**.

## Rules

- Missions are product-agnostic — this repo is public. The litmus test from
  the README applies to every line.
- A mission must survive context compaction: durable state lives in the run
  journal (`runs/<id>/journal.md`), re-read every iteration.
- Bounded always: every mission derives a deadline and/or an item cap from
  its inputs, with a default. Never unbounded.
- **Code-producing missions MUST include the pre-PR quality gate** in their
  finish steps: run `/simplify` then `/code-review` over the branch diff,
  apply high-confidence findings, re-verify + static checks, THEN open the
  PR (one gate pass, no looping). bug-hunt §4 is the reference wording —
  copy it into any new mission that commits code.
- **Machine record — non-negotiable.** `app-pilot init` stamps a neutral
  `runs/<id>/run.json` (schema in `common/runlog.py`) at run-dir creation
  (`init --target <repo#N|ticket>` stamps what the run is against when the
  mission has one), and every mission's finish steps MUST settle it:
  `app-pilot close --status done|failed|abandoned --verdict pass|fail|mixed`
  (`--findings <json>`, `--gate … --gate-reason …`, `--oracle-questions
  <json>` optional — see "Run record" below) as the run's closing step — the close owns
  run.json and its own audit lines; nothing else touches the run dir after it
  (driver teardown — cancel pacemaker, report — may follow). The markdown stays
  the human artifact; run.json is what dashboards and tools consume. A run
  that dies unclosed can be settled by consumers from the dir's mtime — a run
  that never opened is invisible, which is why the open lives in `init`, not
  in mission prose.

## Run record — findings, gate, oracle questions, judge

What `close` writes into run.json beyond status and verdict. Every field here
is optional in the record, so a run.json written before it still parses;
`common/runlog.py` validates a field only when it is present. A mission may
make fields mandatory for its own new findings (bug-hunt does).

### Findings (`--findings <json>`)
A JSON array; each entry has `id`, `severity`, `title` (`ticket` optional),
plus these evidence fields:

| Field | Values | Meaning |
|---|---|---|
| `class` | `parity` · `copy` · `prd-gap` · `cross-surface` · `number` · `functional` · `console` · `network` · `crash` | parity = the app differs from its design frame; copy = text differs from its source, compared character for character; prd-gap = built differently from, or missing against, the written requirement; cross-surface = one entity renders differently across its render sites or against its source record; number = a quantity is computed or formatted wrong; functional = behaviour; console / network = logged errors, swallowed 4xx/5xx; crash. |
| `expected` | text | what the oracle says, naming its source |
| `observed` | text | what the app did |
| `designRef` | `{fileKey, nodeId, band?, renderHash?, render?}` | the exact frame compared against: design file and node, the release band the frame sits in, a hash of the render used, the render's path under the run dir. Parity findings carry it. |
| `region` | `{image, space, imageW, imageH, x, y, w, h, transform?}` | best-effort box on a capture. `image` = run-dir path; `space` = what the numbers count in — `points` (mobile a11y frames), `pixels` (the image's own pixels), `viewport` (web bounding rects, viewport-relative, not full-page); `imageW`/`imageH` = the capture's size in that space; `transform` maps the space onto the image when they differ (e.g. a @3x scale, a scroll offset). Consumers validate it against the real image and fall back to the crop — a confidently wrong box is worse than none. |
| `repro` | `[step, …]` | ordered steps from a named start state |
| `basis` | `observed` · `measured` · `verified-in-source` | how it was established: seen on screen · measured (computed style, sampled pixel, backend record) · confirmed by reading the code or template |
| `certainty` | `confirmed` · `suspected` | suspected = applicability is uncertain (e.g. the signed-in role or data state differs from what the oracle covers). Kept separate from `basis`. |
| `judge` | `raised` · `lowered` · `added` | written only by the judge pass (below) |

### Gate verdict (`--gate`, `--gate-reason` repeatable)
`gate` is the release decision; `verdict` (`pass|fail|mixed`) stays as the
run's outcome summary, and severity only orders the fixing. Exactly one of:

- **`PASS`** — every required state was captured and compared, and every
  confirmed mismatch is fixed and re-tested on the candidate build.
- **`PASS_WITH_EXCEPTIONS`** — as PASS, except some confirmed mismatches are
  carried as disclosed exceptions: `by-design` · `pre-existing` · `won't-fix` ·
  `accepted-deviation`. One `gateReason` per exception:
  `<kind>: <finding id> — <reason> [<citation>]` (the citation whenever one is
  claimed).
- **`INCOMPLETE`** — a required state was not captured, an oracle for a
  required screen could not be established, evidence is missing, or the run
  died. One `gateReason` per gap. Never a warning that still permits PASS.

Rules:
- **Required states** are the list the invoker supplied (route × platform ×
  state, overlays included). Without one, the run writes its required-state
  list into the journal before the first flow leg; coverage is judged against
  that list, never against what the run happened to visit.
- A confirmed `low` still has to be fixed or disclosed. Dismissing a finding
  is limited to false positives and duplicates, with the evidence for it.
- An open oracle question never permits PASS: if it leaves a required
  screen's oracle unresolved → INCOMPLETE; otherwise it is disclosed as a
  `gateReason` (`oracle-question: <screen> — <statement>`).
- A confirmed mismatch that is neither fixed and re-tested nor disclosed
  keeps the gate at INCOMPLETE (`open: <finding id> — fix and re-test
  pending`) — the gate is not reached until the fix is re-tested; `verdict`
  carries `fail`/`mixed` meanwhile. A report-only run with open findings
  therefore ends INCOMPLETE.
- An unanswered `insufficientEvidence` request (below) is missing evidence.
- The journal header states what the gate covers and excludes and the build
  it was judged on.
- runlog enforces the mechanical part: a non-PASS gate needs ≥1 reason;
  PASS and PASS_WITH_EXCEPTIONS need `--status done`.

### Oracle questions (`--oracle-questions <json>`)
`[{screen, platform?, citations: [≥1], statement, suggestedRecipient?}]` —
a disagreement between sources that the run must not settle by itself: frame
vs requirement vs a dated decision, a frame contradicting an app-wide
convention, or a correctness claim in operator text with no source behind it.
They are neither findings nor scope cuts. `suggestedRecipient`: `design` when
the frame is the odd one out, `product` when intent is unknown or the sources
contradict, `engineering` when the app contradicts every source.

### Judge seat (optional)
A second, **blind** pass at settle, in a fresh context, over the capture
manifest: every required state's capture (full screen at original resolution
plus crops), the frozen design render, viewport and capture dimensions, the
text / accessibility output, the requirement lines and accepted deviations.
It **must not receive the driver's findings or severities**, and it answers
per enumerated element per screen rather than "anything different?". How it
is seated (model, effort, tooling) is the invoker's business; the engine only
defines what it writes:
- on findings, `judge: raised` (severity raised on a driver finding) ·
  `lowered` · `added` (a finding the driver did not log);
- `insufficientEvidence[]` (`--insufficient-evidence <json>`):
  `[{screen, need, platform?, state?}]` — a targeted recapture request. Run
  the recapture and re-judge, or carry it into an INCOMPLETE gate.

## Current missions

Distinguished by what decides the work and what the engine is FOR:

- `bug-hunt.md` — **explore** the running app to DISCOVER unknown bugs;
  (optionally) fix the clear ones → PR. The original QA-tester loop; the engine
  is the eyes that find defects.
- `scenario-exec.md` — **regression-verify** a predefined scenario corpus; one
  verdict per scenario; write the run log back. No code changes; the corpus
  decides what, the engine drives it.
- `feature-dev.md` — **build** ONE feature from a spec; prove each acceptance
  criterion live (the engine is the proof gate) → PR. Code-producing.
- `improvement.md` — **triage + work** a KNOWN backlog of non-bug improvements
  (paper cuts, tech debt, perf, a11y); do the safe ones behavior-preserving,
  defer every owner-decision → PR. Code-producing.
