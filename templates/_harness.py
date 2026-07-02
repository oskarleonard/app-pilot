"""Locate the shared app-pilot and expose its helper lib (targetkit).

Installed per project next to target.py — copy from app-pilot/templates/,
never edit. Resolution mirrors the app-pilot shim: $APP_PILOT_HOME -> ~/.app-pilot
(one-line path file) -> ~/programming/projects/app-pilot.
"""
import os
import sys


def root():
    env = os.environ.get("APP_PILOT_HOME")
    if env:
        return env
    pin = os.path.expanduser("~/.app-pilot")
    if os.path.exists(pin):
        v = open(pin).read().strip()
        if v:
            return v
    return os.path.expanduser("~/programming/projects/app-pilot")


def _checked_root():
    r = root()
    if not os.path.isdir(os.path.join(r, "common")):
        sys.exit(
            f"app-pilot: harness not found at '{r}'. Fix one of:\n"
            f"  git clone https://github.com/oskarleonard/app-pilot \"$HOME/programming/projects/app-pilot\"\n"
            f"  echo /path/to/app-pilot > ~/.app-pilot\n"
            f"  export APP_PILOT_HOME=/path/to/app-pilot"
        )
    return r


def core_dir():
    """Mobile engine core — for project scripts that import common/idb_ui."""
    return os.path.join(_checked_root(), "mobile", "core")


sys.path.insert(0, os.path.join(_checked_root(), "common"))
import targetkit  # noqa: E402,F401  (usage: `from _harness import targetkit`)
