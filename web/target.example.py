# target.example.py — copy into YOUR project as scripts/app-pilot/target.py and
# adapt. Generic placeholder values — replace with your app's. Per-app values:
# TESTER_PORT (never your dev port), MODE/MODE_ENV (your app's mock/msw envs),
# SERVER_LOG/PIDFILE (namespace per project!).
# Dev-server launch (engine defaults: `bun run dev` at the repo root):
#   SERVER_CMD = ["npm", "run", "dev"]   # any argv; PORT env is set for you
#   SERVER_CWD = "apps/web"              # monorepo subdir, default repo root
# Everything in CONFIG is a knob; the machinery comes from the shared engine.
"""Target config for the app-pilot tester (WEB) — the project's pin."""
from _harness import targetkit

# ───────────── CONFIG — everything in this section is yours to edit ─────────────

TESTER_PORT = 3002  # never your dev port (e.g. web dev 3000, storybook 6006)

# Ground truth (omit or None = no backend; health skips the ping).
BACKEND_URL = "http://localhost:8080"
BACKEND_HINT = "cd ../my-backend && make run"

# Dev-server launch: argv + repo subdir (engine sets PORT in the env).
SERVER_CMD = ["bun", "run", "dev"]
SERVER_CWD = "apps/web"  # monorepo subdir; "" = repo root

# Process-hygiene artifacts — namespace per project!
SERVER_LOG = "/tmp/myapp-pilot-web.log"
PIDFILE = "/tmp/myapp-pilot-web.pid"

# Pre-PR cross-vendor CODE review (`app-pilot review`) — OPT-IN, off by default.
# When on, the QA pass shells out to the standalone `ensemble-ai` CLI to review
# the branch diff, so the PR is "born reviewed" (behavior verdict + code findings
# in one run trail). Degrades gracefully if `ensemble-ai` isn't installed. Omit
# this dict (or enabled=False) to disable. Keep account/secret knobs in the
# gitignored target.local.py, never here.
REVIEW = {
    "enabled": False,                # flip to True to run review in the QA pass
    "reviewers": ["codex", "grok"],  # or omit → every configured reviewer
    "base": None,                    # base ref override (default: auto vs default branch)
    "sandbox": None,                 # ensemble-ai sandbox profile override
    "allow_sensitive": False,        # review even if the diff carries sensitive paths
    "fail_on_high": False,           # v1 report-only; True → a HIGH fails the review step
}

# ── per-developer overrides (OPTIONAL) ──────────────────────────────────────
# A gitignored `target.local.py` next to this file is exec'd HERE — plain
# python overriding any knob above (`TESTER_PORT = 3103`). Mode is chosen per
# run via the env var below; the browser (headless or not) is your .mcp.json.
# Team config never goes in the overlay. Gitignore `target.local*`.
targetkit.apply_local(globals(), __file__)

# ── derived + mode-computed — don't edit below this line ───────────────────

APP_URL = f"http://localhost:{TESTER_PORT}"

# Tester mode + the env the tester's dev server runs with, per mode.
MODE = targetkit.mode_from_env("MYAPP_PILOT_MODE", default="local", allowed=("local", "msw", "staging"))
MODE_ENV = {
    "local": {
        "NEXT_PUBLIC_API_URL": f"{BACKEND_URL}/api/v1",
        "NEXT_PUBLIC_MSW_MODE": "none",
        "NEXT_PUBLIC_MOCK_AUTH": "true",
    },
    "msw": {"NEXT_PUBLIC_MSW_MODE": "full"},
    "staging": {},
}[MODE]
# Every var ANY mode may set — scrubbed from the inherited shell env before
# MODE_ENV overlays, so a flag exported in your shell can't bleed into a run
# in another mode (e.g. staging inheriting mock-auth).
SCRUB_ENV = ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_MSW_MODE", "NEXT_PUBLIC_MOCK_AUTH"]

# ───────────────────── machinery — don't edit below this line ─────────────────────

if __name__ == "__main__":
    targetkit.cli(globals())
