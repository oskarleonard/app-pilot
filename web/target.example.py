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
APP_URL = f"http://localhost:{TESTER_PORT}"

# Ground truth (omit or None = no backend; health skips the ping).
BACKEND_URL = "http://localhost:8080"
BACKEND_HINT = "cd ../my-backend && make run"

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

# Dev-server launch: argv + repo subdir (engine sets PORT in the env).
SERVER_CMD = ["bun", "run", "dev"]
SERVER_CWD = "apps/web"  # monorepo subdir; "" = repo root

# Process-hygiene artifacts — namespace per project!
SERVER_LOG = "/tmp/myapp-pilot-web.log"
PIDFILE = "/tmp/myapp-pilot-web.pid"

# ───────────────────── machinery — don't edit below this line ─────────────────────

if __name__ == "__main__":
    targetkit.cli(globals())
