"""Shared primitives for the app-pilot tester. Stdlib only.

Vision: `xcrun simctl io <udid> screenshot` + a center crop (`sips`) decoded
by a tiny PNG reader.
Input: `idb ui tap` at DEVICE coordinates — same channel as `simctl` (over
the simulator daemon socket).

Both halves are independent of where the Simulator window is on macOS: the
daemon answers regardless of focus / Space / minimize state. The previous
input path used `osascript "click at {x, y}"` (which actually goes through
the macOS Accessibility hierarchy, NOT raw mouse events — so it also
produced synthetic, a11y-mediated taps identical to idb's). That path works
in normal conditions where the Simulator window is on a visible Space, BUT
its window-geometry query (`osascript ... get position of window 1`) can
race against transient window states (mid-launch, briefly minimized, mid
Space transition) and return empty → IndexError, or stale coords → tap
lands on the wrong window. The idb path has no window-state dependency at
all, so those failure modes can't occur.

Tap fidelity is identical between the two: both produce synthetic
UIKit touches that go through the responder chain. Both have the SAME
limitation for `react-native-gesture-handler` gestures (backdrop tap, drag
to dismiss) — see RUNBOOK.md "gorhom bottom-sheets" for the tester-escape
workaround we use for that orthogonal case.
"""
import os
import struct
import subprocess
import sys
import zlib

# `target.py` lives in the PROJECT's qa dir (e.g. scripts/app-pilot/), NOT in the
# harness — that's the boundary between the portable engine and per-project
# config. The project's shim exports APP_PILOT_PROJECT_DIR; a vendored copy of
# this folder inside a project still works via the one-level-up fallback.
sys.path.insert(0, os.environ.get("APP_PILOT_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import target  # noqa: E402

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

# Fallback iPhone 17 Pro logical screen size (target.py pins this device).
# Used only if the runtime probe via idb's a11y tree fails.
_DEFAULT_W, _DEFAULT_H = 402, 874


def device_size(udid=None):
    """(width, height) of the target device in logical points.

    Probes the live a11y tree via `idb describe-all` (Application root frame)
    so we adapt automatically if `target.UDID` ever points at a different
    device. Falls back to the iPhone 17 default if the probe fails (e.g. app
    not foregrounded yet, idb-companion not responding).
    """
    if udid is None:
        udid = target.UDID
    try:
        import idb_ui  # imported lazily to avoid circulars (idb_ui has its own deps)

        return idb_ui.screen_size(udid)
    except Exception:
        return _DEFAULT_W, _DEFAULT_H


def tap_center(udid=None):
    """Device-coord (x, y) at the center of the screen."""
    w, h = device_size(udid)
    return w // 2, h // 2


def frac_point(fx, fy, udid=None):
    """Device-coord (x, y) at fractional (fx, fy) of the screen."""
    w, h = device_size(udid)
    return round(fx * w), round(fy * h)


def screenshot(path, udid="booted"):
    subprocess.run(["xcrun", "simctl", "io", udid, "screenshot", path], **_QUIET)


def center_crop(src, dst, size=60):
    subprocess.run(["sips", "-c", str(size), str(size), src, "--out", dst], **_QUIET)


def decode_png(path, max_rows=None):
    """Decode a PNG into (width_px, height_px, channels, row-major bytes).

    Stdlib only — same hand-rolled decoder as the original `avg_rgb` used,
    but exposes the raw pixel buffer so callers can sample arbitrary regions.

    `max_rows`: optional cap on the number of rows to decode. The PNG
    format's PNG-filter row dependencies mean we can't randomly access
    row N without decoding rows 0..N-1, but we CAN stop early once we
    have what we need. Setting this to (height * fraction) when the
    caller only needs the top portion of the image roughly cuts pure-
    Python decode time by the same fraction. Returns `h` set to the
    decoded row count, not the original PNG height.
    """
    data = open(path, "rb").read()
    pos, idat, w, h, ct = 8, b"", 0, 0, 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos : pos + 4])[0]
        typ, chunk = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _bd, ct = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw, stride = zlib.decompress(idat), w * ch
    rows_to_decode = h if max_rows is None else min(h, max_rows)

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    out, prev, i = bytearray(), bytes(stride), 0
    for _ in range(rows_to_decode):
        f = raw[i]
        i += 1
        line = bytearray(raw[i : i + stride])
        i += stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                line[x] = (line[x] + paeth(a, b, c)) & 255
        out += line
        prev = line
    return w, rows_to_decode, ch, bytes(out)


def avg_rgb(path):
    """Average (R, G, B) of a small PNG. Stdlib only (no Pillow).

    Used by qa.py's per-shot center-RGB log line. For arbitrary sub-region
    sampling on the full screenshot, use `decode_png` + `pixel_avg`.
    """
    w, h, ch, out = decode_png(path)
    r = g = b = n = 0
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * ch
            if ch < 3:  # grayscale/palette — treat the single channel as gray
                r, g, b, n = r + out[o], g + out[o], b + out[o], n + 1
            else:
                r, g, b, n = r + out[o], g + out[o + 1], b + out[o + 2], n + 1
    return r // n, g // n, b // n


def pixel_avg(decoded, cx, cy, half=3):
    """Average (R, G, B) of a (2*half+1)² box around pixel (cx, cy).

    `decoded` is the tuple returned by `decode_png`. Returns None if every
    sample is out-of-bounds. Cheap: a few dozen Python int adds per call.
    """
    w, h, ch, out = decoded
    cx, cy = int(cx), int(cy)
    r = g = b = n = 0
    for dy in range(-half, half + 1):
        py = cy + dy
        if py < 0 or py >= h:
            continue
        row = py * w * ch
        for dx in range(-half, half + 1):
            px = cx + dx
            if px < 0 or px >= w:
                continue
            o = row + px * ch
            if ch < 3:  # grayscale/palette — single channel as gray
                r += out[o]
                g += out[o]
                b += out[o]
            else:
                r += out[o]
                g += out[o + 1]
                b += out[o + 2]
            n += 1
    if n == 0:
        return None
    return r // n, g // n, b // n


def click(x, y, udid=None):
    """Tap at device coords via `idb ui tap` (headless — works regardless of
    where the Simulator window is, including hidden / on another Space).

    Pass an actual UDID; "booted" doesn't work here — idb rejects it with
    `Cannot spawn companion for booted` (unlike simctl which accepts the
    alias). Defaults to target.UDID so callers usually don't have to pass it.

    stderr is NOT silenced — if idb errors (wrong UDID, companion crashed,
    etc.) the message reaches the caller's log so we don't silently lose taps.
    """
    if udid is None:
        udid = target.UDID
    subprocess.run(
        [target.IDB, "ui", "tap", str(round(x)), str(round(y)), "--udid", udid],
        stdout=subprocess.DEVNULL,  # idb is chatty on success; only stderr matters
    )


def activate_simulator():
    """Bring the Simulator window to the foreground. NOT load-bearing — `idb`
    based input + `simctl` screenshots both work headless. Kept as a utility
    for ad-hoc human debugging when you want to watch a run by eye."""
    subprocess.run(
        ["osascript", "-e", 'tell application "Simulator" to activate'], **_QUIET
    )
