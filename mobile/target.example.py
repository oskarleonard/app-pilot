# target.example.py — copy into YOUR project as scripts/app-pilot/target.py and
# adapt. Generic placeholder values — replace with your app's. Per-app values
# to derive (see PORTING.md): DEVICE_NAME (a sim model no other project's tester
# uses), PORT (distinct from dev Metro + every other tester), BUNDLE + SCHEME
# (app.config.ts), MODE/METRO_ENV (your mock-auth flag), TAB_ORDER (read
# `app-pilot tree`, don't guess), LAUNCHER_LABELS, LOG_PROCESS_HINT, and the
# /tmp artifact paths (namespace per project!).
# Everything in the CONFIG section is a knob; the machinery (per-machine sim
# resolution via target.local, the --field CLI) comes from the shared engine.
"""Target config for the app-pilot tester (MOBILE) — the project's pin."""
import os

from _harness import targetkit

# ───────────── CONFIG — everything in this section is yours to edit ─────────────

DEVICE_NAME = "iPhone 16 Pro"  # a sim model NO other project's tester uses on this machine
PORT = 8092  # tester Metro port — distinct from your dev Metro (8081) + every other tester
BUNDLE = "com.example.myapp.dev"  # dev-flavor bundle id (app.config.ts)
SCHEME = "myapp"  # app.config.ts `scheme` — dev-client deep links
UDID_ENV = "MYAPP_PILOT_UDID"  # env override for the per-machine sim pin (target.local)

# Tester mode + the env the tester's Metro bundles with (your app's mock flags).
MODE = targetkit.mode_from_env("MYAPP_PILOT_MODE", default="mock", allowed=("mock", "staging"))
METRO_ENV = {
    "EXPO_PUBLIC_AI_TESTER": "true",
    **({"EXPO_PUBLIC_MOCK_AUTH": "true"} if MODE == "mock" else {}),
}

# Ground truth (omit or None = no backend; health/doctor skip the ping).
BACKEND_URL = "http://localhost:8080"
BACKEND_HINT = "cd ../my-backend && make run"

# idb CLI location (machine setup: see the engine README).
IDB = os.path.expanduser("~/.idb-venv/bin/idb")

# Bottom-tab order (left->right) — read the live a11y tree (`app-pilot tree`), don't guess.
TAB_ORDER = ["home", "settings"]

# app_state() launcher detection — generic Expo dev-client labels usually suffice.
LAUNCHER_LABELS = [
    "development servers",
    "enter url manually",
    "there was a problem loading the project",
    "failed to load app",
]

# OS crash-log stream predicate (substring of the app's process image path).
LOG_PROCESS_HINT = "myapp"

# Process-hygiene artifacts — namespace per project!
METRO_LOG = "/tmp/myapp-pilot-metro.log"
PIDFILE = "/tmp/myapp-pilot-metro.pid"
CRASHLOG = "/tmp/myapp-pilot-crash.log"
CRASHLOG_PID = "/tmp/myapp-pilot-crash.pid"

WINDOW = f'window "{DEVICE_NAME}"'  # legacy osascript reference only

# ───────────────────── machinery — don't edit below this line ─────────────────────

UDID = targetkit.resolve_udid(DEVICE_NAME, env_var=UDID_ENV, near=__file__)

if __name__ == "__main__":
    targetkit.cli(globals())
