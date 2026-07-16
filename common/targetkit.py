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


def tester_port(default, env_var="APP_PILOT_PORT"):
    """The tester's port: orchestrator env override -> the rig's pinned default.

    Pooled/isolated runs (worktree workers, dashboard fire lanes) export
    APP_PILOT_PORT so N copies of the same rig stop fighting over the port; a
    plain developer run keeps the pinned default. (Port + UDID are all this
    isolates — the rig's own /tmp artifacts (PIDFILE, METRO_LOG, CRASHLOG*)
    are still one set per rig, so same-rig lanes clobber each other's pidfile
    and crash capture. Namespace those per worker before running lanes of ONE
    rig concurrently.)

    Call it AFTER apply_local and BEFORE anything derived: the fleet override
    must outrank the per-developer overlay (matching resolve_udid, where env
    beats the target.local pin), and every derived value (APP_URL, SERVER_CMD)
    must flow from the result:

        TESTER_PORT = 3002
        targetkit.apply_local(globals(), __file__)
        TESTER_PORT = targetkit.tester_port(TESTER_PORT)
        APP_URL = f"http://localhost:{TESTER_PORT}"

    Called at the knob site instead, a gitignored target.local.py pinning
    TESTER_PORT would silently beat the orchestrator and collide the lanes.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        sys.exit(f"app-pilot: {env_var}={raw!r} is not a port number")
    if not 1 <= port <= 65535:
        sys.exit(f"app-pilot: {env_var}={raw!r} is out of range (1-65535)")
    return port


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


def resolve_udid(device_name, env_var, near, uniform_env="APP_PILOT_UDID"):
    """The per-machine sim pin: rig env override -> APP_PILOT_UDID -> target.local
    next to `near` (written on first resolve, so discovery runs at most once per
    machine) -> auto-discover a sim named device_name.

    APP_PILOT_UDID is the UNIFORM orchestrator override: a pooled/lane runner
    can aim any rig at a specific sim without knowing that rig's private
    env-var name. The rig-specific env_var stays higher-precedence — it is a
    deliberate narrow override (a developer debugging ONE rig), while the
    uniform name is fleet plumbing. That only reads as deliberate when the rig
    var is set FOR the run, so a conflict says so on stderr: inherited
    ambiently (a shell profile, a stale worker env) it would otherwise defeat
    fleet aim silently, and the orchestrator can't clear a name it doesn't
    know."""
    rig = os.environ.get(env_var, "").strip()
    uniform = os.environ.get(uniform_env, "").strip()
    if rig and uniform and rig != uniform:
        sys.stderr.write(
            f"app-pilot: {env_var}={rig} beats {uniform_env}={uniform} "
            f"(rig-specific env wins); unset it for fleet aim to apply.\n"
        )
    for val in (rig, uniform):
        if val:
            return val
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
            f"  echo <UDID> > {pin_path}\n"
            f"  (or export {env_var}=<UDID>, or the uniform {uniform_env}=<UDID>)"
        )
    try:
        open(pin_path, "w").write(udid + "\n")
    except OSError:
        pass  # read-only checkout — resolution still works, just re-runs next time
    return udid


def apply_local(ns, near, filename="target.local.py"):
    """Per-developer knob overrides — the gitignored half of the pin.

    target.py calls this AFTER its plain knobs and BEFORE anything derived:

        TESTER_PORT = 3002
        targetkit.apply_local(globals(), __file__)
        TESTER_PORT = targetkit.tester_port(TESTER_PORT)  # fleet env > overlay
        APP_URL = f"http://localhost:{TESTER_PORT}"   # computed AFTER overrides

    The file (default `target.local.py`, next to target.py, gitignored) is
    plain python — e.g. `TESTER_PORT = 3103` or `DEVICE_NAME = "iPhone 15"` —
    exec'd into the pin's namespace. Missing file = no-op. Errors in it
    propagate loudly with the overlay's own path in the traceback (it's the
    developer's file). Team config never goes here — anything every developer
    needs belongs in target.py. (The sim UDID keeps its own auto-written pin,
    `target.local` — see resolve_udid; gitignore both with `target.local*`.)

    Also refreshes the product/ mount: every engine command imports target.py
    (which calls this), while ensure_product_mount's other caller — cli() —
    only covers `target --field`. Without this, a fresh checkout/worktree had
    NO product layer during stop/serve/health/init until something ran
    --field (hit live on the first mobile pilot fire, 2026-07-14).
    """
    try:
        ensure_product_mount(near)
    except OSError as err:
        sys.stderr.write(f"app-pilot: product mount skipped: {err}\n")
    path = os.path.join(os.path.dirname(os.path.abspath(near)), filename)
    try:
        with open(path) as fh:
            src = fh.read()
    except OSError:
        return
    exec(compile(src, path, "exec"), ns)


def load_env_profile(*paths, required=()):
    """First existing file among `paths`, parsed as KEY=VAL lines -> (dict, path).

    dotenv-lite: blank lines and #-comments skipped, split on the first '=',
    values verbatim (no quote/escape handling — profiles are trusted local
    files). Projects use this for gitignored env profiles (which backend/auth
    instance a real-API tester mode talks to). Callers may pass fallback
    paths; note that gitignored files are not materialized in detached
    worktrees — the automation that creates such a checkout should inject the
    profile before boot. Exits actionably when no path exists or a `required`
    key is missing/empty — a half-loaded profile must not boot a tester
    against the wrong backend."""
    tried = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        tried.append(p)
        if not os.path.isfile(p):
            continue
        env = {}
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        missing = [k for k in required if not env.get(k)]
        if missing:
            sys.exit(f"app-pilot: profile {p} is missing {', '.join(missing)} — fill it in first")
        return env, p
    sys.exit("app-pilot: no env profile found — tried:\n  " + "\n  ".join(tried))


def ensure_product_mount(near, env_var="APP_PILOT_PRODUCT_DIR"):
    """Optional central product layer. A one-line `product.pin` next to
    target.py (path to a shared checkout's product dir — relative to the
    adapter dir, or absolute, ~ ok) turns `product/` into a maintained
    symlink to that checkout. Resolution: env override -> gitignored
    product.pin.local (per-developer path) -> product.pin (team default) ->
    (pin target missing: stderr hint + `product.local/` fallback). The first
    redirect migrates a real `product/` dir to `product.local/` — that stays
    the committed fallback for machines without the shared checkout. No pin
    file = no-op, so plain local-product projects never notice this.

    Rides every target.py import (via apply_local) plus the --field CLI, so
    the mount is fresh before ANY engine command reads product/ paths —
    stop/serve/health/init import target as a module and never reach cli().
    """
    adapter = os.path.dirname(os.path.abspath(near))
    mount = os.path.join(adapter, "product")
    pin = os.environ.get(env_var, "").strip()
    if not pin:
        # Per-developer redirect first (gitignored — same idea as
        # target.local.py), then the committed team pin.
        for name in ("product.pin.local", "product.pin"):
            try:
                with open(os.path.join(adapter, name)) as f:
                    pin = f.read().strip()
            except OSError:
                continue
            if pin:
                break
    if not pin:
        return  # no pin — this project keeps a plain local product/
    src = os.path.abspath(os.path.join(adapter, os.path.expanduser(pin)))
    fallback = os.path.join(adapter, "product.local")
    if not os.path.isdir(src):
        sys.stderr.write(
            f"app-pilot: product pin target missing ({src}) — falling back to product.local.\n"
            "  Clone the shared QA repo (path in product.pin) for the central product layer.\n"
        )
        if not os.path.isdir(fallback):
            return  # nothing to mount; engine's no-product notices apply
        src = fallback
    if os.path.isdir(mount) and not os.path.islink(mount):
        if os.path.isdir(fallback):
            sys.stderr.write(
                "app-pilot: both product/ (real dir) and product.local/ exist — "
                "not mounting; merge or remove one.\n"
            )
            return
        os.rename(mount, fallback)  # one-time migration to the fallback slot
    if os.path.islink(mount):
        if os.readlink(mount) == src:
            return
        os.remove(mount)
    elif os.path.exists(mount):
        return  # a FILE named product — never touch
    os.symlink(src, mount)


def cli(ns):
    """`python3 target.py --field` printer for build scripts (e.g. `npm run
    ios` reading --udid). Builds the field set from whatever the project
    defines; default field: --udid (mobile) else --url (web)."""
    if "__file__" in ns:
        try:
            ensure_product_mount(ns["__file__"])
        except OSError as err:
            sys.stderr.write(f"app-pilot: product mount skipped: {err}\n")
    spec = [
        ("--udid", "UDID"),
        ("--port", "PORT"),
        ("--port", "TESTER_PORT"),
        ("--url", "APP_URL"),
        ("--origin", "PUBLIC_ORIGIN"),
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
