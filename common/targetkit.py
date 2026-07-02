"""Shared machinery for project target.py files — keeps them values-only.

A project's target.py is the CONFIG surface: every line above its machinery
tail is a knob. The derivations live here, once, instead of being pasted
into every project:

  UDID = targetkit.resolve_udid(DEVICE_NAME, env_var=UDID_ENV, near=__file__)
  MODE = targetkit.mode_from_env("X_QA_MODE", default="mock", allowed=(...))
  if __name__ == "__main__":
      targetkit.cli(globals())
"""
import json
import os
import re
import subprocess
import sys


def mode_from_env(env_var, default, allowed=None):
    """Tester mode from an env var; a typo must not silently select a mode."""
    mode = os.environ.get(env_var, default)
    if allowed and mode not in allowed:
        sys.exit(f"app-pilot: invalid {env_var}={mode!r} — expected one of {' | '.join(allowed)}")
    return mode


def _runtime_version(runtime_key):
    m = re.search(r"iOS-(\d+)-(\d+)", runtime_key)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _discover_udid(device_name):
    """Best available sim named device_name: booted first, then newest iOS."""
    try:
        out = subprocess.run(
            ["xcrun", "simctl", "list", "-j", "devices", "available"],
            capture_output=True, text=True, timeout=15,
        )
        runtimes = json.loads(out.stdout)["devices"]
    except Exception:
        return None
    candidates = [
        (d.get("state") == "Booted", _runtime_version(runtime), d["udid"])
        for runtime, devices in runtimes.items()
        for d in devices
        if d.get("name") == device_name
    ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def resolve_udid(device_name, env_var, near):
    """The per-machine sim pin: env override -> target.local next to `near`
    (written on first resolve, so discovery runs at most once per machine)
    -> auto-discover a sim named device_name."""
    env = os.environ.get(env_var)
    if env:
        return env
    pin_path = os.path.join(os.path.dirname(os.path.abspath(near)), "target.local")
    try:
        pin = open(pin_path).read().strip()
        if pin:
            return pin
    except OSError:
        pass
    udid = _discover_udid(device_name)
    if not udid:
        sys.exit(
            f"app-pilot: no simulator named {device_name!r} found.\n"
            f"Create one (Xcode > Devices & Simulators), or pin one explicitly:\n"
            f"  echo <UDID> > {pin_path}   (or export {env_var}=<UDID>)"
        )
    try:
        open(pin_path, "w").write(udid + "\n")
    except OSError:
        pass  # read-only checkout — resolution still works, just re-runs next time
    return udid


def cli(ns):
    """`python3 target.py --field` printer for build scripts (e.g. `npm run
    ios` reading --udid). Builds the field set from whatever the project
    defines; default field: --udid (mobile) else --url (web)."""
    spec = [
        ("--udid", "UDID"),
        ("--port", "PORT"),
        ("--port", "TESTER_PORT"),
        ("--url", "APP_URL"),
        ("--window", "WINDOW"),
        ("--bundle", "BUNDLE"),
        ("--mode", "MODE"),
    ]
    fields = {flag: str(ns[key]) for flag, key in spec if key in ns}
    default = "--udid" if "--udid" in fields else "--url"
    key = sys.argv[1] if len(sys.argv) > 1 else default
    if key not in fields:
        sys.exit(f"target.py: unknown field {key!r}; pick from {list(fields)}")
    print(fields[key])
