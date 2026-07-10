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
# Every var ANY mode may set — scrubbed from the inherited shell env before
# METRO_ENV overlays, so a flag exported in your shell can't bleed into a run
# in another mode (e.g. staging inheriting mock-auth).
SCRUB_ENV = ["EXPO_PUBLIC_AI_TESTER", "EXPO_PUBLIC_MOCK_AUTH"]

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

# app_state() POSITIVE app detection — a11y label(s) visible ONLY inside YOUR
# app's running UI (an in-app tab title, screen header, or content string — read
# `app-pilot tree`, don't guess). STRONGLY recommended: when set, health/recover
# report 'app' ONLY when one is actually visible, so a silently-failed launch
# (home screen frontmost) reads 'unknown' instead of a false 'app' the verdict
# would pass. Unset = the old optimistic default (assume 'app' when not the
# launcher/home screen) — weaker, can't confirm your app.
#   ⚠ MUST be app-EXCLUSIVE. Do NOT use iOS system-app names ("Settings", "Home",
#   "Safari", …) or your app's own DISPLAY NAME — those also label icons on the
#   home screen, so a missed launch would still match one and falsely PASS. Pick
#   something that shows up only while your app is actually running.
APP_LABELS = ["My Feed", "Compose"]  # ← replace with your app's own in-app labels

# app_state() springboard (iOS home-screen) detection. Matched as an EXACT icon
# label (tolerant of a trailing badge like ", 3 new items"), so an in-app "Open
# in Safari" button is NOT mistaken for the home screen. Default ["safari"] is a
# brand name → survives non-English locales (the old check also required
# "messages" = "Meddelanden" in sv, so a localized home screen was misread as the
# app — a false PASS). Override only if your own UI shows an exact "Safari" label.
SPRINGBOARD_LABELS = ["safari"]

# OS crash-log stream predicate (substring of the app's process image path).
LOG_PROCESS_HINT = "myapp"

# Process-hygiene artifacts — namespace per project!
METRO_LOG = "/tmp/myapp-pilot-metro.log"
PIDFILE = "/tmp/myapp-pilot-metro.pid"
CRASHLOG = "/tmp/myapp-pilot-crash.log"
CRASHLOG_PID = "/tmp/myapp-pilot-crash.pid"

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
# python overriding any knob above (`PORT = 8192`, `DEVICE_NAME = "iPhone 15"`).
# Mode is chosen per run via the env var above. The sim UDID keeps its own
# auto-written pin (`target.local`). Gitignore `target.local*`.
targetkit.apply_local(globals(), __file__)

# ── derived — don't edit below this line ───────────────────────────────────
WINDOW = f'window "{DEVICE_NAME}"'  # legacy osascript reference only

# ───────────────────── machinery — don't edit below this line ─────────────────────

UDID = targetkit.resolve_udid(DEVICE_NAME, env_var=UDID_ENV, near=__file__)

if __name__ == "__main__":
    targetkit.cli(globals())
