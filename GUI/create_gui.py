# Author: Paul Wyers
# Copyright (C) 2025 Paul Wyers
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import json
import math
import os
import re
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from tkinter import (
    StringVar, OptionMenu, Label, Canvas, Entry, Toplevel, Button,
    Checkbutton, filedialog, messagebox,
)

from matplotlib.font_manager import FontProperties, findSystemFonts
from matplotlib.textpath import TextPath
import numpy as np
from shapely.geometry import LineString, Polygon
import shapely.affinity

# Settings file lives next to this script, not in whatever directory the app
# happens to be launched from.
SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "machine_settings.json"
)

DEFAULT_SETTINGS = {
    "text_cut_depth": 0.2,
    "label_cutout_depth": 1.6,
    "pass_depth": 0.4,
    "tool_diameter": 0.3,
    "safe_z": 5.0,
    "offset_x": 0.0,
    "offset_y": 0.0,
    "feed_rate": 300,
    "plunge_rate": 100,
    "spindle_rpm": 10000,
    "laser_power": 1000,
    "frame_power": 5.0,
    "tool_mode": "Spindle",
    "cutout_padding": 2.0,
    "laser_kerf": 0.15,
    "tab_width": 3.0,
    "tab_height": 0.4,
    "material_width": 1000,
    "material_height": 600,
    "machine_target": "",   # last-used machine connection (COM port / IP / ws URL)
    "machine_baud": 115200,
}

cnc_settings = DEFAULT_SETTINGS.copy()


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                cnc_settings.update(json.load(f))
        except (ValueError, OSError):
            pass  # corrupt/unreadable settings file: fall back to defaults


def save_settings():
    with open(SETTINGS_FILE, "w") as f:
        json.dump(cnc_settings, f, indent=2)


# ---------------------------------------------------------------------------
# Geometry — no GUI dependencies, shared by the preview and the G-code export
# so the two can never drift apart.
# ---------------------------------------------------------------------------

# Fonts are rendered at a fixed size, then scaled so that capital letters come
# out at the requested height in mm. (FontProperties size is a point size for
# the em box — it is NOT the printed glyph height, so it can't be used as mm.)
FONT_RENDER_SIZE = 100.0

_cap_height_cache = {}


def cap_height(font_path):
    if font_path not in _cap_height_cache:
        tp = TextPath((0, 0), "X", prop=FontProperties(fname=font_path, size=FONT_RENDER_SIZE))
        h = tp.get_extents().height
        _cap_height_cache[font_path] = h if h > 0 else FONT_RENDER_SIZE
    return _cap_height_cache[font_path]


_text_geom_cache = {}


def text_geometry(label, font_path, font_height_mm):
    """Shapely geometry for a label with letter counters (the hole in O, A, e…)
    as real holes, scaled so capitals are font_height_mm tall.

    Origin is the bottom-left of the text bounding box, Y up (machine-style).
    Returns None for labels with no printable outline.
    """
    key = (label, font_path, font_height_mm)
    if key in _text_geom_cache:
        return _text_geom_cache[key]
    tp = TextPath((0, 0), label, prop=FontProperties(fname=font_path, size=FONT_RENDER_SIZE))
    geom = None
    # TextPath returns every contour as a plain ring — outer shapes and holes
    # alike. XOR-ing them together (even-odd rule) rebuilds the true glyph
    # shapes with their holes.
    for ring in tp.to_polygons():
        if len(ring) < 3:
            continue
        p = Polygon(ring)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            continue
        geom = p if geom is None else geom.symmetric_difference(p)
    if geom is None or geom.is_empty:
        return None
    scale = font_height_mm / cap_height(font_path)
    geom = shapely.affinity.scale(geom, xfact=scale, yfact=scale, origin=(0, 0))
    minx, miny, _, _ = geom.bounds
    geom = shapely.affinity.translate(geom, xoff=-minx, yoff=-miny)
    if len(_text_geom_cache) > 256:
        _text_geom_cache.clear()
    _text_geom_cache[key] = geom
    return geom


def geom_polygons(geom):
    """Iterate the Polygon parts of a Polygon/MultiPolygon/GeometryCollection."""
    for part in getattr(geom, "geoms", [geom]):
        if part.geom_type == "Polygon":
            yield part
        elif hasattr(part, "geoms"):
            yield from geom_polygons(part)


def geom_rings(geom):
    """All rings (exteriors and holes) of a geometry, as coordinate arrays."""
    for poly in geom_polygons(geom):
        yield np.asarray(poly.exterior.coords)
        for interior in poly.interiors:
            yield np.asarray(interior.coords)


def hatch_fill(geom, spacing):
    """Horizontal fill lines clipped to the geometry (holes are skipped)."""
    minx, miny, maxx, maxy = geom.bounds
    lines = []
    y = miny + spacing / 2
    while y < maxy:
        seg = geom.intersection(LineString([(minx - 1, y), (maxx + 1, y)]))
        for g in getattr(seg, "geoms", [seg]):
            if g.geom_type == "LineString" and g.length > 1e-9:
                coords = list(g.coords)
                lines.append((coords[0], coords[-1]))
        y += spacing
    return lines


def build_layout(labels, font_path, font_height_mm, spacing, padding,
                 material_width, material_height, snap_grid=None,
                 label_size=None, margin=0.0):
    """Stack labels upward from the work origin (bottom-left of material).

    Coordinates are "canvas" mm: origin top-left, Y increases downward (what
    the preview shows). The first label's box sits at the material's
    bottom-left corner, inset by margin on both axes — callers pass the
    kerf/tool radius as margin so the cutout toolpath starts exactly at
    X0 Y0. Each item's geom keeps its own origin (text bbox bottom-left,
    Y up); x/y_top place that box on the material.

    label_size: (width, height) in mm for fixed-size labels, or None to size
    each label from its text (bbox + padding). A fixed-size label whose text
    (plus padding clearance) doesn't fit is flagged fits=False — the caller
    decides whether to warn or refuse.
    """
    def snap(v):
        return round(v / snap_grid) * snap_grid if snap_grid else v

    items = []
    bottom = material_height - margin  # canvas y of the current stack bottom
    for label in labels:
        geom = text_geometry(label, font_path, font_height_mm)
        if geom is None:
            continue
        _, _, width, height = geom.bounds
        if label_size:
            label_w, label_h = label_size
            fits = (width + 2 * padding <= label_w + 1e-6
                    and height + 2 * padding <= label_h + 1e-6)
        else:
            label_w, label_h = width + 2 * padding, height + 2 * padding
            fits = True
        bx0 = snap(margin)
        by0 = snap(bottom - label_h)
        items.append({
            "label": label, "geom": geom,
            "x": bx0 + (label_w - width) / 2,
            "y_top": by0 + (label_h - height) / 2,
            "width": width, "height": height,
            "cutout": (bx0, by0, bx0 + label_w, by0 + label_h),
            "fits": fits,
        })
        bottom = by0 - spacing
    return items


# ---------------------------------------------------------------------------
# G-code generation (pure: layout + settings in, lines out)
# ---------------------------------------------------------------------------

def pass_depths(total, step):
    """Cutting depths for multi-pass work; the last pass lands exactly on total."""
    step = max(abs(step), 0.01)
    n = max(1, math.ceil(abs(total) / step))
    return [min(abs(total), i * step) for i in range(1, n + 1)]


def rect_segments_with_tabs(x0, y0, x1, y1, tab_width):
    """The rectangle perimeter split into segments, leaving a gap (tab) at the
    middle of each side."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    segments = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
        length = math.hypot(bx - ax, by - ay)
        if length <= tab_width * 2:
            segments.append([(ax, ay), (bx, by)])
            continue
        t0 = (length / 2 - tab_width / 2) / length
        t1 = (length / 2 + tab_width / 2) / length
        segments.append([(ax, ay), (ax + (bx - ax) * t0, ay + (by - ay) * t0)])
        segments.append([(ax + (bx - ax) * t1, ay + (by - ay) * t1), (bx, by)])
    return segments


def generate_gcode_lines(layout, settings, fill_text):
    """G-code for a layout produced by build_layout().

    Canvas Y (down) is converted to machine Y (up) here, in one place:
    machine_y = material_height - canvas_y. Nothing is mirrored — TextPath
    geometry is already Y-up, same as the machine.
    """
    H = settings["material_height"]
    laser = settings["tool_mode"] == "Laser"
    feed = settings["feed_rate"]
    plunge = settings["plunge_rate"]
    safe_z = settings["safe_z"]

    g = ["G21 ; units: mm", "G90 ; absolute positioning"]
    if laser:
        # GRBL dynamic laser mode: power only applies during G1 moves, so
        # travels (G0) don't burn. No Z motion needed.
        g.append(f"M4 S{settings['laser_power']:.0f} ; laser on (dynamic power)")
    else:
        g.append(f"G0 Z{safe_z:.3f}")
        g.append(f"M3 S{settings['spindle_rpm']:.0f} ; spindle on")
        g.append("G4 P2 ; wait for spindle to reach speed")

    # Work-origin offset: shifts the whole job away from machine home
    ox, oy = settings["offset_x"], settings["offset_y"]

    def polyline(points, depth):
        sx, sy = points[0]
        g.append(f"G0 X{sx + ox:.3f} Y{sy + oy:.3f}")
        if not laser:
            g.append(f"G1 Z{-depth:.3f} F{plunge:.0f}")
        first = True
        for px, py in points[1:]:
            f_part = f" F{feed:.0f}" if first else ""
            g.append(f"G1 X{px + ox:.3f} Y{py + oy:.3f}{f_part}")
            first = False
        if not laser:
            g.append(f"G0 Z{safe_z:.3f}")

    for item in layout:
        x, y_top, height = item["x"], item["y_top"], item["height"]
        # geom origin (text bbox bottom-left) in machine coordinates
        geom = shapely.affinity.translate(
            item["geom"], xoff=x, yoff=H - (y_top + height)
        )

        g.append(f"(Label: {item['label']})")
        for depth in pass_depths(settings["text_cut_depth"], settings["pass_depth"]):
            if fill_text:
                for start, end in hatch_fill(geom, settings["tool_diameter"] * 0.8):
                    polyline([start, end], depth)
            else:
                for ring in geom_rings(geom):
                    polyline([tuple(pt) for pt in ring], depth)

        # Cutout rectangle in machine coordinates, with the toolpath offset
        # outward by half the tool/kerf width so the finished label comes out
        # at the drawn size (the drawn rectangle is the label edge, not the
        # tool centre).
        r = (settings["laser_kerf"] if laser else settings["tool_diameter"]) / 2
        cx0, cy0, cx1, cy1 = item["cutout"]
        mx0, my0 = cx0 - r, H - cy1 - r
        mx1, my1 = cx1 + r, H - cy0 + r
        g.append(f"(Cutout for label: {item['label']})")
        total = settings["label_cutout_depth"]
        tab_h, tab_w = settings["tab_height"], settings["tab_width"]
        for depth in pass_depths(total, settings["pass_depth"]):
            # On the passes below tab height, leave gaps so the label stays
            # attached until snapped out (spindle only — tabs don't apply to laser).
            if not laser and tab_h > 0 and tab_w > 0 and depth > total - tab_h:
                for seg in rect_segments_with_tabs(mx0, my0, mx1, my1, tab_w):
                    polyline(seg, depth)
            else:
                polyline(
                    [(mx0, my0), (mx1, my0), (mx1, my1), (mx0, my1), (mx0, my0)],
                    depth,
                )

    g.append("M5 ; stop spindle/laser")
    g.append("M2 ; end program")
    return g


def _gword(line, letter, default):
    m = re.search(rf"{letter}(-?\d+\.?\d*)", line)
    return float(m.group(1)) if m else default


def simulate_gcode(lines):
    """Replay generated G-code into XY segments for the toolpath preview.

    Returns a list of (x0, y0, x1, y1, kind, z) in machine coordinates, where
    kind is 'rapid', 'engrave' or 'cutout' (from the block comments the
    generator emits) and z is the modal Z of the move (0 in laser mode).
    Simulating the real G-code means the preview shows exactly what the
    machine will receive — including passes, tabs and kerf offsets.
    """
    segments = []
    x = y = z = 0.0
    kind = "engrave"
    for line in lines:
        if line.startswith("(Label:"):
            kind = "engrave"
            continue
        if line.startswith("(Cutout"):
            kind = "cutout"
            continue
        m = re.match(r"G([01])\b", line)
        if not m:
            continue
        nx, ny, nz = _gword(line, "X", x), _gword(line, "Y", y), _gword(line, "Z", z)
        if nx != x or ny != y:
            segments.append(
                (x, y, nx, ny, "rapid" if m.group(1) == "0" else kind, nz)
            )
        x, y, z = nx, ny, nz
    return segments


def generate_dry_run_lines(layout, settings):
    """Trace the job's outer boundary without cutting anything.

    Spindle mode: moves at Safe Z with the spindle off, so you can watch the
    machine trace the job outline and check placement/clamp clearance.
    Laser mode: traces at Frame Power (a very low S value) with no Z motion,
    so the spot is visible while framing.
    """
    if not layout:
        return []
    H = settings["material_height"]
    laser = settings["tool_mode"] == "Laser"
    r = (settings["laser_kerf"] if laser else settings["tool_diameter"]) / 2
    ox, oy = settings["offset_x"], settings["offset_y"]

    # Outer bounds of all cutout toolpaths (kerf offset included), machine coords
    x0 = min(i["cutout"][0] for i in layout) - r + ox
    x1 = max(i["cutout"][2] for i in layout) + r + ox
    y0 = H - max(i["cutout"][3] for i in layout) - r + oy
    y1 = H - min(i["cutout"][1] for i in layout) + r + oy

    g = [
        "G21 ; units: mm",
        "G90 ; absolute positioning",
        "(Dry run: job boundary trace only - no cutting)",
    ]
    if laser:
        g.append(f"M4 S{settings['frame_power']:.0f} ; laser at frame power")
    else:
        g.append("M5 ; spindle off")
        g.append(f"G0 Z{settings['safe_z']:.3f} ; stay at safe height")
    g.append(f"G0 X{x0:.3f} Y{y0:.3f}")
    for px, py in [(x1, y0), (x1, y1), (x0, y1), (x0, y0)]:
        g.append(f"G1 X{px:.3f} Y{py:.3f} F{settings['feed_rate']:.0f}")
    g.append("M5")
    g.append("M2 ; end program")
    return g


# ---------------------------------------------------------------------------
# Machine link — GRBL over USB serial (a stock CNC 3018 is GRBL 1.1 on a
# COM port; the $$ dump and <Idle|WPos:...> reports come over that link)
# ---------------------------------------------------------------------------

_log_sink = [None]


def set_log_sink(fn):
    """Route app_log() messages somewhere (the GUI console). None = discard."""
    _log_sink[0] = fn


def app_log(message):
    sink = _log_sink[0]
    if sink:
        sink(str(message))


GRBL_SETTING_DESCRIPTIONS = {
    0: "Step pulse (µs)", 1: "Step idle delay (ms)", 2: "Step polarity mask",
    3: "Direction polarity mask", 4: "Invert step enable", 5: "Invert limit pins",
    6: "Invert probe pin", 10: "Status report mask", 11: "Junction deviation (mm)",
    12: "Arc tolerance (mm)", 13: "Report in inches", 20: "Soft limits enable",
    21: "Hard limits enable", 22: "Homing cycle enable", 23: "Homing direction mask",
    24: "Homing feed (mm/min)", 25: "Homing seek (mm/min)", 26: "Homing debounce (ms)",
    27: "Homing pull-off (mm)", 30: "Max spindle speed (RPM)",
    31: "Min spindle speed (RPM)", 32: "Laser mode enable",
    100: "X steps/mm", 101: "Y steps/mm", 102: "Z steps/mm",
    110: "X max rate (mm/min)", 111: "Y max rate (mm/min)", 112: "Z max rate (mm/min)",
    120: "X acceleration (mm/s²)", 121: "Y acceleration (mm/s²)",
    122: "Z acceleration (mm/s²)",
    130: "X max travel (mm)", 131: "Y max travel (mm)", 132: "Z max travel (mm)",
}


def sendable_lines(lines):
    """G-code lines worth transmitting: comments and blanks stripped."""
    out = []
    for line in lines:
        cmd = line.split(";", 1)[0].strip()
        if cmd and not cmd.startswith("("):
            out.append(cmd)
    return out


def parse_grbl_settings(lines):
    """$$ dump lines -> {setting_number: value_string}. Ignores everything
    else (status reports, ok, banners)."""
    out = {}
    for line in lines:
        m = re.match(r"\$(\d+)=(-?\d+\.?\d*)", line.strip())
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def await_ok(ser, context=""):
    """Read GRBL responses until ok (returns None) or error/ALARM (returns
    the message). Status chatter like <Idle|WPos:...> is ignored."""
    while True:
        resp = ser.readline().decode(errors="ignore").strip()
        if resp == "ok":
            return None
        if resp.startswith(("error", "ALARM")):
            app_log(f"RX {resp}")
            return resp
        if not resp:
            raise TimeoutError(f"no response from GRBL {context}".strip())
        app_log(f"RX {resp}")  # <status> reports, [MSG:...], banner: keep reading


class WebSocketLink:
    """GRBL over a websocket (ESP32/FluidNC/vendor wifi boards speak the same
    line protocol as serial, typically on ws://<ip>:81). Exposes the same
    write/readline interface as pyserial so the rest of the code is
    transport-agnostic."""

    def __init__(self, url, timeout=5):
        try:
            import websocket  # websocket-client; imported here so the GUI runs without it
        except ImportError:
            raise RuntimeError(
                "wifi connections need the websocket-client package — "
                "run: pip install websocket-client"
            ) from None

        self.timeout = timeout
        try:
            self.ws = websocket.create_connection(url, timeout=timeout)
        except websocket.WebSocketBadStatusException as exc:
            # A 200/HTML answer means we hit a web server, not a websocket —
            # typically ws://<ip> without :81, which lands on the web UI port
            raise RuntimeError(
                f"{url} answered as a web page, not a GRBL websocket. "
                "For ESP3D wifi boards enter just the IP address; for raw "
                "websocket GRBL include the port, e.g. ws://host:81 "
                f"(status {exc.status_code})"
            ) from None
        self.buffer = b""

    def write(self, data):
        if isinstance(data, bytes):
            data = data.decode("latin-1")
        self.ws.send(data)

    def readline(self):
        while b"\n" not in self.buffer:
            try:
                frame = self.ws.recv()
            except Exception:  # timeout / closed: report like a serial timeout
                return b""
            if isinstance(frame, str):
                frame = frame.encode("latin-1", errors="replace")
            self.buffer += frame
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line + b"\n"

    def reset_input_buffer(self):
        self.buffer = b""
        self.ws.settimeout(0.2)
        try:
            while True:
                self.ws.recv()  # drain pending frames
        except Exception:
            pass
        self.ws.settimeout(self.timeout)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ESP3DLink(WebSocketLink):
    """GRBL via an ESP3D-style wifi board (the usual 3018 wifi module).

    These boards take commands as HTTP GET /command?plain=<cmd> and push
    GRBL's serial output to websocket clients on port 81 — the websocket
    itself ignores incoming data. Confirmed against a live 3018: connecting
    ws://host:81 yields CURRENT_ID/ACTIVE_ID/PING control frames, and $$ via
    HTTP returns the settings dump as websocket frames ending in 'ok'."""

    def __init__(self, host, timeout=8):
        host = re.sub(r"^https?://", "", host).strip("/")
        host, _, ws_port = host.partition(":")
        super().__init__(f"ws://{host}:{ws_port or 81}", timeout=timeout)
        self.host = host

    def write(self, data):
        if isinstance(data, bytes):
            data = data.decode("latin-1")
        for cmd in data.replace("\r", "\n").split("\n"):
            if not cmd:
                continue
            url = (f"http://{self.host}/command?plain="
                   f"{urllib.parse.quote(cmd, safe='')}")
            urllib.request.urlopen(url, timeout=self.timeout).read()


def normalize_target(target):
    """Forgive sloppy URLs: 'ws:host:81' or 'ws:/host' -> 'ws://host:81'."""
    t = target.strip()
    m = re.match(r"^(wss?|https?):/{0,2}(.+)$", t, re.IGNORECASE)
    if m:
        return f"{m.group(1).lower()}://{m.group(2)}"
    return t


def link_kind(target):
    """'serial' (COM3, /dev/ttyUSB0), 'ws' (ws://host:81, raw bidirectional
    websocket GRBL like FluidNC), or 'esp3d' (bare IP / http:// address)."""
    if target.startswith(("ws://", "wss://")):
        return "ws"
    if target.startswith(("http://", "https://")) or ("." in target and "/" not in target):
        return "esp3d"
    return "serial"


def open_grbl(target, baud):
    """Open a GRBL link — see link_kind for accepted target forms."""
    target = normalize_target(target)
    kind = link_kind(target)
    if kind == "ws":
        app_log(f"Opening websocket {target}")
        link = WebSocketLink(target)
        # ESP3D-style boards ignore websocket input entirely; they announce
        # themselves with CURRENT_ID/ACTIVE_ID frames on connect. Detect that
        # and switch to HTTP command mode instead of timing out on $$.
        link.ws.settimeout(1.5)
        seen = []
        try:
            while len(seen) < 4:
                seen.append(link.ws.recv())
        except Exception:
            pass
        link.ws.settimeout(link.timeout)
        if any(str(f).startswith(("CURRENT_ID", "ACTIVE_ID")) for f in seen):
            host = re.sub(r"^wss?://", "", target).split("/", 1)[0]
            app_log(f"ESP3D board detected on {target} — "
                    f"switching to HTTP command mode ({host})")
            link.close()
            link = ESP3DLink(host)
        else:
            for f in seen:  # keep any real data we swallowed while probing
                if isinstance(f, str):
                    f = f.encode("latin-1", "replace")
                link.buffer += f
    elif kind == "esp3d":
        app_log(f"Opening ESP3D wifi link to {target}")
        link = ESP3DLink(target)
    else:
        try:
            import serial  # pyserial; imported here so the GUI runs without it
        except ImportError:
            raise RuntimeError(
                "serial connections need the pyserial package — "
                "run: pip install pyserial"
            ) from None

        app_log(f"Opening {target} at {baud} baud (serial)")
        link = serial.Serial(target, baud, timeout=5)
        link.write(b"\r\n\r\n")  # wake GRBL
        time.sleep(2)
    link.reset_input_buffer()
    return link


def home_machine(ser, timeout_s=90):
    """Run GRBL's homing cycle ($H) and wait for it to finish. Homing can
    take a long time, so empty reads are tolerated until timeout_s. Returns
    None on success or the GRBL error/ALARM message."""
    app_log("TX $H (homing…)")
    ser.write(b"$H\n")
    end = time.time() + timeout_s
    while time.time() < end:
        resp = ser.readline().decode(errors="ignore").strip()
        if resp == "ok":
            app_log("Homing complete")
            return None
        if resp.startswith(("error", "ALARM")):
            app_log(f"RX {resp}")
            return resp
        if resp:
            app_log(f"RX {resp}")
    raise TimeoutError(f"homing did not complete within {timeout_s}s")


def stream_gcode_serial(port, baud, lines, on_progress=None, abort=None, home=False):
    """Stream a job to GRBL call-and-response style (send a line, wait for
    ok). Simple and reliable for label-sized jobs. Returns (sent, errors).
    Setting the abort event feed-holds then soft-resets the controller.
    With home=True, a $H homing cycle runs first — nothing is streamed
    unless it succeeds."""
    cmds = sendable_lines(lines)
    errors = 0
    with open_grbl(port, baud) as ser:
        if home:
            err = home_machine(ser)
            if err:
                raise RuntimeError(f"homing failed ({err}) — nothing was sent")
        app_log(f"Streaming {len(cmds)} lines")
        for i, cmd in enumerate(cmds, 1):
            if abort is not None and abort.is_set():
                app_log("ABORT: feed hold + soft reset")
                ser.write(b"!")        # feed hold
                time.sleep(0.2)
                ser.write(b"\x18")     # soft reset: abandon the job
                return i - 1, errors
            app_log(f"TX {cmd}")
            ser.write((cmd + "\n").encode("ascii"))
            if await_ok(ser, f"at line {i} ({cmd!r})"):
                errors += 1
            if on_progress:
                on_progress(i, len(cmds))
    return len(cmds), errors


def grbl_read_settings(port, baud):
    """Query $$ and return {number: value_string}."""
    with open_grbl(port, baud) as ser:
        app_log("TX $$")
        ser.write(b"$$\n")
        lines = []
        while True:
            resp = ser.readline().decode(errors="ignore").strip()
            if resp == "ok":
                break
            if not resp:
                raise TimeoutError("no response to $$")
            app_log(f"RX {resp}")
            lines.append(resp)
    return parse_grbl_settings(lines)


def grbl_write_settings(port, baud, changes):
    """Write {number: value_string} as $n=value commands. Returns a list of
    GRBL error strings (empty = all accepted)."""
    problems = []
    with open_grbl(port, baud) as ser:
        for num, val in sorted(changes.items()):
            app_log(f"TX ${num}={val}")
            ser.write(f"${num}={val}\n".encode("ascii"))
            err = await_ok(ser, f"writing ${num}")
            if err:
                problems.append(f"${num}={val}: {err}")
    return problems


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def get_system_fonts():
    font_dict = {}
    for path in findSystemFonts(fontpaths=None, fontext="ttf"):
        try:
            name = FontProperties(fname=path).get_name()
            font_dict.setdefault(name, path)
        except Exception:
            pass
    return dict(sorted(font_dict.items()))


SETTINGS_FIELDS = [
    ("text_cut_depth", "Text Cut Depth (mm)"),
    ("label_cutout_depth", "Label Cutout Depth (mm)"),
    ("pass_depth", "Depth per Pass (mm)"),
    ("tool_diameter", "Tool Diameter (mm)"),
    ("safe_z", "Safe Z Height (mm)"),
    ("offset_x", "X Offset from Home (mm)"),
    ("offset_y", "Y Offset from Home (mm)"),
    ("feed_rate", "Feed Rate (mm/min)"),
    ("plunge_rate", "Plunge Rate (mm/min)"),
    ("spindle_rpm", "Spindle RPM"),
    ("laser_power", "Laser Power (S value)"),
    ("frame_power", "Frame Power (S value, laser dry run)"),
    ("cutout_padding", "Cutout Padding (mm)"),
    ("laser_kerf", "Laser Kerf (mm)"),
    ("tab_width", "Tab Width (mm, 0 = no tabs)"),
    ("tab_height", "Tab Height (mm, 0 = no tabs)"),
    ("material_width", "Material Width (mm)"),
    ("material_height", "Material Height (mm)"),
]

SNAP_GRID_MM = 5
CANVAS_W, CANVAS_H = 900, 550


def main():
    load_settings()

    system_fonts = get_system_fonts()
    if not system_fonts:
        messagebox.showerror(
            "No fonts found",
            "No TrueType fonts were found on this system. Install a TTF font and retry.",
        )
        return

    root = tk.Tk()
    root.title("CNC Label Maker")

    state = {
        "zoom": 1.0,
        "pan": [0.0, 0.0],   # screen-px offset from drag-panning
        "drag": None,
        "font_path": next(iter(system_fonts.values())),
    }

    # --- console window ---
    console_state = {"win": None, "text": None}
    log_history = []

    def append_console(line):
        text = console_state["text"]
        if text is not None and text.winfo_exists():
            text.config(state="normal")
            text.insert("end", line + "\n")
            text.see("end")
            text.config(state="disabled")

    def gui_log(message):
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        log_history.append(line)
        del log_history[:-5000]
        root.after(0, lambda: append_console(line))

    set_log_sink(gui_log)

    def open_console():
        if console_state["win"] is not None and console_state["win"].winfo_exists():
            console_state["win"].lift()
            return
        win = Toplevel(root)
        win.title("Console")
        text = tk.Text(win, width=100, height=26, state="disabled",
                       bg="black", fg="#66ff66", font=("Consolas", 9))
        scroll = tk.Scrollbar(win, command=text.yview)
        text.config(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)
        console_state["win"], console_state["text"] = win, text
        if log_history:
            text.config(state="normal")
            text.insert("end", "\n".join(log_history) + "\n")
            text.see("end")
            text.config(state="disabled")

    def parse_label_size(raw):
        """'Auto' -> None, '60x20' -> (60.0, 20.0); raises ValueError otherwise."""
        raw = raw.strip().lower().replace("×", "x")
        if raw in ("", "auto"):
            return None
        w, h = (float(p) for p in raw.split("x"))
        if w <= 0 or h <= 0:
            raise ValueError(raw)
        return (w, h)

    def read_inputs():
        """Widget values -> layout inputs, or None if a field is invalid."""
        try:
            font_height = float(font_height_entry.get())
            spacing = float(spacing_entry.get())
            label_size = parse_label_size(size_entry.get())
        except ValueError:
            return None
        text = entry.get("1.0", "end").strip()
        labels = [lbl.strip().rstrip(",") for lbl in text.splitlines() if lbl.strip()]
        return labels, font_height, spacing, label_size

    def current_layout():
        inputs = read_inputs()
        if inputs is None:
            return None
        labels, font_height, spacing, label_size = inputs
        laser = cnc_settings["tool_mode"] == "Laser"
        kerf_r = (cnc_settings["laser_kerf"] if laser else cnc_settings["tool_diameter"]) / 2
        return build_layout(
            labels, state["font_path"], font_height, spacing,
            cnc_settings["cutout_padding"], cnc_settings["material_width"],
            cnc_settings["material_height"],
            snap_grid=SNAP_GRID_MM if snap_var.get() else None,
            label_size=label_size, margin=kerf_r,
        )

    def update_preview():
        canvas.delete("all")
        mat_w, mat_h = cnc_settings["material_width"], cnc_settings["material_height"]

        if read_inputs() is None:
            canvas.create_text(
                200, 40, text="Invalid font height, spacing or label size", fill="red"
            )
            return
        layout = current_layout()

        # World (mm) -> screen (px): fit the whole material sheet into the
        # canvas at zoom 1, and zoom about the canvas centre so content stays
        # in view.
        scale = min(CANVAS_W / mat_w, CANVAS_H / mat_h) * 0.95 * state["zoom"]
        pan_x, pan_y = state["pan"]

        def sx(wx):
            return (wx - mat_w / 2) * scale + CANVAS_W / 2 + pan_x

        def sy(wy):
            return (wy - mat_h / 2) * scale + CANVAS_H / 2 + pan_y

        # Material boundary and work zero (machine origin = bottom-left)
        canvas.create_rectangle(sx(0), sy(0), sx(mat_w), sy(mat_h), outline="gray")
        zx, zy = sx(0), sy(mat_h)
        canvas.create_line(zx - 8, zy, zx + 8, zy, fill="green")
        canvas.create_line(zx, zy - 8, zx, zy + 8, fill="green")
        ox, oy = cnc_settings["offset_x"], cnc_settings["offset_y"]
        origin_label = "X0 Y0" if not (ox or oy) else f"job at X{ox:g} Y{oy:g}"
        canvas.create_text(zx + 6, zy + 12, text=origin_label, fill="green", anchor="w")

        overflow = any(
            item["cutout"][2] > mat_w or item["cutout"][1] < 0 for item in layout
        )

        if toolpath_var.get():
            # Simulate the real exported G-code so the preview cannot lie
            segs = simulate_gcode(
                generate_gcode_lines(layout, cnc_settings, fill_text_var.get())
            )
            job_ox, job_oy = cnc_settings["offset_x"], cnc_settings["offset_y"]
            final_z = min((s[5] for s in segs if s[4] == "cutout"), default=0.0)
            order = {"rapid": 0, "engrave": 1, "cutout": 2}

            def draw_rank(seg):
                kind, z = seg[4], seg[5]
                is_final = kind == "cutout" and abs(z - final_z) < 1e-6
                return (order[kind], 1 if is_final else 0)

            # Earlier cutout passes draw first (light blue) so tab gaps in the
            # final (dark) pass show through where the tabs are
            for x0m, y0m, x1m, y1m, kind, z in sorted(segs, key=draw_rank):
                p = (sx(x0m - job_ox), sy(mat_h - (y0m - job_oy)),
                     sx(x1m - job_ox), sy(mat_h - (y1m - job_oy)))
                if kind == "rapid":
                    canvas.create_line(*p, fill="#bbbbbb", dash=(2, 3))
                elif kind == "engrave":
                    canvas.create_line(*p, fill="red")
                elif abs(z - final_z) < 1e-6:
                    canvas.create_line(*p, fill="#0000cc", width=2)
                else:
                    canvas.create_line(*p, fill="#aac6e8")

            # Cut order badges (labels are engraved then cut out, in this order)
            for i, item in enumerate(layout, 1):
                px, py = sx(item["cutout"][0]), sy(item["cutout"][1])
                canvas.create_oval(px - 9, py - 9, px + 9, py + 9,
                                   fill="white", outline="green")
                canvas.create_text(px, py, text=str(i), fill="green")
            canvas.create_text(
                CANVAS_W / 2, CANVAS_H - 10, fill="gray",
                text=("grey dashes = rapids · red = engraving · dark blue = final cutout pass "
                      "(gaps = tabs) · light blue = earlier passes · numbers = cut order"),
            )
            design_items = []  # design drawing below is skipped in toolpath view
        else:
            design_items = layout

        for item in design_items:
            x, y_top, height = item["x"], item["y_top"], item["height"]

            # geom is Y-up with origin at the text bbox bottom-left; the canvas
            # is Y-down, so: world_y = y_top + height - geom_y
            def to_canvas(coords):
                pts = np.asarray(coords, dtype=float).copy()
                wx = pts[:, 0] + x
                wy = y_top + height - pts[:, 1]
                pts[:, 0] = (wx - mat_w / 2) * scale + CANVAS_W / 2 + pan_x
                pts[:, 1] = (wy - mat_h / 2) * scale + CANVAS_H / 2 + pan_y
                return pts

            if fill_text_var.get():
                for poly in geom_polygons(item["geom"]):
                    ext = to_canvas(poly.exterior.coords)
                    canvas.create_polygon(
                        [c for pt in ext for c in pt], fill="black", outline="black"
                    )
                    for interior in poly.interiors:
                        hole = to_canvas(interior.coords)
                        canvas.create_polygon(
                            [c for pt in hole for c in pt], fill="white", outline="white"
                        )
            else:
                for ring in geom_rings(item["geom"]):
                    pts = to_canvas(ring)
                    for i in range(len(pts) - 1):
                        canvas.create_line(*pts[i], *pts[i + 1], fill="red")

            cx0, cy0, cx1, cy1 = item["cutout"]
            canvas.create_rectangle(
                sx(cx0), sy(cy0), sx(cx1), sy(cy1),
                outline="blue" if item["fits"] else "red", dash=(2, 2),
            )

        warnings = []
        if overflow:
            warnings.append("labels exceed material size")
        if any(not item["fits"] for item in layout):
            warnings.append("text too big for label size (red)")
        if warnings:
            canvas.create_text(
                CANVAS_W / 2, 15,
                text="Warning: " + "; ".join(warnings), fill="orange",
            )

    def generate_gcode():
        if read_inputs() is None:
            messagebox.showerror("Error", "Invalid font height, spacing or label size")
            return
        layout = current_layout()
        if not layout:
            messagebox.showerror("Error", "Nothing to export — enter at least one label")
            return
        problems = []
        if any(
            item["cutout"][2] > cnc_settings["material_width"] or item["cutout"][1] < 0
            for item in layout
        ):
            problems.append("labels exceed the material size")
        if any(not item["fits"] for item in layout):
            problems.append("some labels are too small for their text")
        if problems and not messagebox.askyesno(
            "Warning", "; ".join(problems).capitalize() + ". Export anyway?"
        ):
            return

        gcode = generate_gcode_lines(layout, cnc_settings, fill_text_var.get())

        file_path = filedialog.asksaveasfilename(
            defaultextension=".gcode", filetypes=[("G-code files", "*.gcode")]
        )
        if file_path:
            with open(file_path, "w") as f:
                f.write("\n".join(gcode))
            app_log(f"Exported {len(gcode)} lines of G-code to {file_path}")
            messagebox.showinfo("Success", f"G-code saved to {file_path}")
        else:
            app_log("G-code export cancelled")

    def export_dry_run():
        if read_inputs() is None:
            messagebox.showerror("Error", "Invalid font height, spacing or label size")
            return
        layout = current_layout()
        if not layout:
            messagebox.showerror("Error", "Nothing to trace — enter at least one label")
            return
        gcode = generate_dry_run_lines(layout, cnc_settings)
        app_log(f"Dry run generated: {len(gcode)} lines (boundary trace)")
        file_path = filedialog.asksaveasfilename(
            defaultextension=".gcode", initialfile="dry_run.gcode",
            filetypes=[("G-code files", "*.gcode")],
        )
        if file_path:
            with open(file_path, "w") as f:
                f.write("\n".join(gcode))
            app_log(f"Dry run saved to {file_path}")
            messagebox.showinfo("Success", f"Dry-run G-code saved to {file_path}")
        else:
            app_log("Dry run export cancelled")

    def open_machine_dialog():
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except ImportError:
            ports = []  # pyserial missing: websocket connections still work

        win = Toplevel(root)
        win.title("Machine (GRBL)")
        Label(win, text="Connect to:").grid(row=0, column=0, sticky="e")
        conn_entry = Entry(win, width=24)
        conn_entry.insert(
            0, cnc_settings.get("machine_target")
            or (ports[0] if ports else "192.168.1.207")
        )
        conn_entry.grid(row=0, column=1, sticky="w")
        if ports:
            port_pick = StringVar(value=ports[0])

            def pick_port(p):
                conn_entry.delete(0, "end")
                conn_entry.insert(0, p)

            OptionMenu(win, port_pick, *ports, command=pick_port).grid(
                row=0, column=2, sticky="w"
            )
        Label(win, text="COM port, IP address (ESP3D wifi board), or ws:// URL").grid(
            row=1, column=1, columnspan=2, sticky="w"
        )
        Label(win, text="Baud (serial only):").grid(row=2, column=0, sticky="e")
        baud_entry = Entry(win, width=8)
        baud_entry.insert(0, str(cnc_settings.get("machine_baud", 115200)))
        baud_entry.grid(row=2, column=1, sticky="w")

        def conn():
            return conn_entry.get().strip()

        def remember_connection():
            """Persist the connection so it's prefilled next session."""
            cnc_settings["machine_target"] = conn()
            try:
                cnc_settings["machine_baud"] = int(baud_entry.get())
            except ValueError:
                pass
            save_settings()
        dry_var = tk.BooleanVar(value=True)
        Checkbutton(
            win, text="Dry run only (boundary trace, no cutting)", variable=dry_var
        ).grid(row=3, column=0, columnspan=3, sticky="w")
        home_var = tk.BooleanVar(value=True)
        Checkbutton(
            win, text="Home ($H) before send", variable=home_var
        ).grid(row=3, column=2, sticky="w")
        status = Label(win, text="Set your work zero, then Send",
                       wraplength=380, justify="left")
        status.grid(row=4, column=0, columnspan=3, pady=4)
        abort_event = threading.Event()
        busy = [False]

        def set_status(text):
            text = str(text)
            app_log(f"Machine: {text}")
            if len(text) > 300:
                text = text[:300] + "…"
            root.after(0, lambda: status.config(text=text))

        def get_baud():
            try:
                return int(baud_entry.get())
            except ValueError:
                messagebox.showerror("Error", "Baud must be a number")
                return None

        def send_worker(port, baud, lines, home):
            try:
                sent, errors = stream_gcode_serial(
                    port, baud, lines,
                    on_progress=lambda i, n: set_status(f"Sending… {i}/{n}"),
                    abort=abort_event, home=home,
                )
                if abort_event.is_set():
                    set_status(f"Aborted after {sent} lines — machine was reset")
                elif errors:
                    set_status(f"Finished with {errors} GRBL errors — check the machine")
                else:
                    set_status(f"Done — {sent} lines sent")
            except Exception as exc:
                set_status(f"Failed: {exc}")
            finally:
                busy[0] = False

        def start_send():
            if busy[0]:
                return
            if read_inputs() is None:
                messagebox.showerror("Error", "Invalid font height, spacing or label size")
                return
            layout = current_layout()
            if not layout:
                messagebox.showerror("Error", "Nothing to send — enter at least one label")
                return
            baud = get_baud()
            if baud is None:
                return
            remember_connection()
            lines = (
                generate_dry_run_lines(layout, cnc_settings) if dry_var.get()
                else generate_gcode_lines(layout, cnc_settings, fill_text_var.get())
            )
            abort_event.clear()
            busy[0] = True
            set_status("Connecting…")
            threading.Thread(
                target=send_worker,
                args=(conn(), baud, lines, home_var.get()), daemon=True,
            ).start()

        def open_grbl_settings():
            baud = get_baud()
            if baud is None:
                return
            remember_connection()
            set_status("Reading $$ settings…")

            def read_worker():
                try:
                    values = grbl_read_settings(conn(), baud)
                except Exception as exc:
                    set_status(f"Failed to read settings: {exc}")
                    return
                set_status("Settings loaded")
                root.after(0, lambda: build_editor(values))

            def build_editor(values):
                ed = Toplevel(win)
                ed.title("GRBL Settings ($$)")
                container = Canvas(ed, width=430, height=420)
                scroll = tk.Scrollbar(ed, orient="vertical", command=container.yview)
                inner = tk.Frame(container)
                inner.bind(
                    "<Configure>",
                    lambda e: container.configure(scrollregion=container.bbox("all")),
                )
                container.create_window((0, 0), window=inner, anchor="nw")
                container.configure(yscrollcommand=scroll.set)
                container.grid(row=0, column=0)
                scroll.grid(row=0, column=1, sticky="ns")
                container.bind_all(
                    "<MouseWheel>",
                    lambda e: container.yview_scroll(-1 if e.delta > 0 else 1, "units"),
                )

                entries = {}
                for row, num in enumerate(sorted(values)):
                    desc = GRBL_SETTING_DESCRIPTIONS.get(num, "")
                    Label(inner, text=f"${num}", width=6, anchor="e").grid(row=row, column=0)
                    e = Entry(inner, width=12)
                    e.insert(0, values[num])
                    e.grid(row=row, column=1, padx=4)
                    Label(inner, text=desc, anchor="w").grid(row=row, column=2, sticky="w")
                    entries[num] = e

                ed_status = Label(ed, text=f"{len(values)} settings read",
                                  wraplength=380, justify="left")
                ed_status.grid(row=1, column=0, columnspan=2)

                def write_changes():
                    changes = {
                        num: e.get().strip()
                        for num, e in entries.items()
                        if e.get().strip() != values[num]
                    }
                    if not changes:
                        ed_status.config(text="Nothing changed")
                        return
                    summary = ", ".join(f"${n}={v}" for n, v in sorted(changes.items()))
                    if not messagebox.askyesno(
                        "Write GRBL settings",
                        f"Write {len(changes)} change(s) to the controller?\n\n{summary}",
                        parent=ed,
                    ):
                        return
                    ed_status.config(text="Writing…")

                    def write_worker():
                        try:
                            problems = grbl_write_settings(conn(), baud, changes)
                        except Exception as exc:
                            root.after(0, lambda: ed_status.config(text=f"Failed: {exc}"))
                            return
                        if problems:
                            msg = "; ".join(problems)
                        else:
                            msg = f"Wrote {len(changes)} setting(s) OK"
                            for num, val in changes.items():
                                values[num] = val
                        root.after(0, lambda: ed_status.config(text=msg))

                    threading.Thread(target=write_worker, daemon=True).start()

                def save_to_file():
                    path = filedialog.asksaveasfilename(
                        parent=ed, defaultextension=".txt",
                        initialfile="grbl_settings_backup.txt",
                        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                    )
                    if not path:
                        return
                    with open(path, "w") as f:
                        f.write("\n".join(
                            f"${n}={entries[n].get().strip()}" for n in sorted(entries)
                        ) + "\n")
                    app_log(f"GRBL settings backed up to {path}")
                    ed_status.config(text=f"Saved {len(entries)} settings to file")

                def load_from_file():
                    path = filedialog.askopenfilename(
                        parent=ed,
                        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                    )
                    if not path:
                        return
                    with open(path) as f:
                        loaded = parse_grbl_settings(f.read().splitlines())
                    changed = 0
                    for num, val in loaded.items():
                        if num in entries and entries[num].get().strip() != val:
                            entries[num].delete(0, "end")
                            entries[num].insert(0, val)
                            changed += 1
                    app_log(f"Loaded {len(loaded)} settings from {path}; "
                            f"{changed} differ from the controller")
                    ed_status.config(
                        text=f"File loaded: {changed} value(s) differ — "
                             "review, then Write Changes"
                    )

                Button(ed, text="💾 Write Changes", command=write_changes).grid(
                    row=2, column=0, columnspan=2, pady=(6, 0)
                )
                Button(ed, text="📄 Save to File…", command=save_to_file).grid(
                    row=3, column=0, pady=6
                )
                Button(ed, text="📂 Load from File…", command=load_from_file).grid(
                    row=3, column=1, pady=6
                )

            threading.Thread(target=read_worker, daemon=True).start()

        Button(win, text="▶ Send", command=start_send).grid(row=5, column=0, pady=6)
        Button(win, text="⛔ Abort", command=abort_event.set).grid(row=5, column=1, pady=6)
        Button(win, text="⚙ GRBL Settings ($$)", command=open_grbl_settings).grid(
            row=6, column=0, columnspan=2, pady=(0, 6)
        )

    def show_about():
        messagebox.showinfo(
            "About CNC Label Maker",
            "CNC Label Maker\n\n"
            "Generates G-code for traffolyte-style labels: engraved text, "
            "multi-pass cutouts with holding tabs, spindle or laser, and "
            "direct GRBL machine control over USB serial or wifi.\n\n"
            "Copyright (C) 2025 Paul Wyers — GPL v3\n"
            "https://github.com/w1s3on3/CNC-LABEL",
        )

    def open_settings():
        win = Toplevel(root)
        win.title("Cutting Parameters")
        entries = {}
        for row, (key, text) in enumerate(SETTINGS_FIELDS):
            Label(win, text=text + ":").grid(row=row, column=0, sticky="e")
            e = Entry(win)
            e.insert(0, cnc_settings[key])
            e.grid(row=row, column=1)
            entries[key] = e
        Label(win, text="Tool Mode:").grid(row=len(SETTINGS_FIELDS), column=0, sticky="e")
        tool_mode = StringVar(value=cnc_settings["tool_mode"])
        OptionMenu(win, tool_mode, "Spindle", "Laser").grid(
            row=len(SETTINGS_FIELDS), column=1
        )

        def save():
            try:
                new_values = {k: float(e.get()) for k, e in entries.items()}
            except ValueError:
                messagebox.showerror("Error", "All settings must be numbers")
                return
            for key in ("pass_depth", "safe_z", "feed_rate", "plunge_rate",
                        "material_width", "material_height"):
                if new_values[key] <= 0:
                    messagebox.showerror("Error", f"{key} must be greater than zero")
                    return
            cnc_settings.update(new_values)
            cnc_settings["tool_mode"] = tool_mode.get()
            save_settings()
            win.destroy()
            update_preview()

        Button(win, text="Save", command=save).grid(
            row=len(SETTINGS_FIELDS) + 1, column=0, columnspan=2, pady=10
        )

    def zoom_canvas(delta, px, py):
        f = 1.1 if delta > 0 else 0.9
        # Keep the world point under the cursor stationary while zooming
        state["pan"][0] = (px - CANVAS_W / 2) * (1 - f) + state["pan"][0] * f
        state["pan"][1] = (py - CANVAS_H / 2) * (1 - f) + state["pan"][1] * f
        state["zoom"] *= f
        update_preview()

    def start_pan(event):
        state["drag"] = (event.x, event.y)

    def do_pan(event):
        if state["drag"] is None:
            return
        lx, ly = state["drag"]
        state["pan"][0] += event.x - lx
        state["pan"][1] += event.y - ly
        state["drag"] = (event.x, event.y)
        update_preview()

    def reset_zoom():
        state["zoom"] = 1.0
        state["pan"] = [0.0, 0.0]
        update_preview()

    def select_font(name):
        state["font_path"] = system_fonts[name]
        update_preview()

    # --- menu bar ---
    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)
    file_menu.add_command(label="Export G-code…", command=generate_gcode)
    file_menu.add_command(label="Export Dry Run…", command=export_dry_run)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=file_menu)
    settings_menu = tk.Menu(menubar, tearoff=0)
    settings_menu.add_command(label="Cutting Parameters…", command=open_settings)
    settings_menu.add_command(label="Machine (GRBL)…", command=open_machine_dialog)
    menubar.add_cascade(label="Settings", menu=settings_menu)
    menubar.add_command(label="Console", command=open_console)
    menubar.add_command(label="About", command=show_about)
    root.config(menu=menubar)

    # --- widgets ---
    Label(root, text="Labels (one per line):").grid(row=0, column=0, sticky="e")
    entry = tk.Text(root, height=4, width=50)
    entry.grid(row=0, column=1, columnspan=4, sticky="w")

    Label(root, text="Font Height (mm):").grid(row=1, column=0, sticky="e")
    font_height_entry = Entry(root, width=5)
    font_height_entry.insert(0, "10")
    font_height_entry.grid(row=1, column=1, sticky="w")

    Label(root, text="Label Spacing (mm):").grid(row=1, column=2, sticky="e")
    spacing_entry = Entry(root, width=5)
    spacing_entry.insert(0, "10")
    spacing_entry.grid(row=1, column=3, sticky="w")

    Label(root, text="Label Size:").grid(row=1, column=4, sticky="e")
    size_entry = Entry(root, width=8)
    size_entry.insert(0, "Auto")
    size_entry.grid(row=1, column=5, sticky="w")
    size_preset = StringVar(value="Auto")

    def pick_size(choice):
        size_entry.delete(0, "end")
        size_entry.insert(0, choice)
        update_preview()

    OptionMenu(
        root, size_preset, "Auto", "50x15", "60x20", "75x25", "100x30",
        command=pick_size,
    ).grid(row=1, column=6, sticky="w")

    Label(root, text="Font:").grid(row=2, column=0, sticky="e")
    font_name = StringVar()
    font_name.set(next(iter(system_fonts.keys())))
    OptionMenu(root, font_name, *system_fonts.keys(), command=select_font).grid(
        row=2, column=1, sticky="w"
    )

    Button(root, text="🔄 Reset Zoom", command=reset_zoom).grid(row=2, column=2)
    Button(root, text="💾 Export G-code", command=generate_gcode).grid(row=2, column=3)
    Button(root, text="🧭 Dry Run", command=export_dry_run).grid(row=2, column=4)

    snap_var = tk.BooleanVar(value=False)
    Checkbutton(root, text="Snap to Grid", variable=snap_var, command=update_preview).grid(
        row=2, column=5
    )
    fill_text_var = tk.BooleanVar(value=False)
    Checkbutton(root, text="Fill Text", variable=fill_text_var, command=update_preview).grid(
        row=2, column=6
    )
    toolpath_var = tk.BooleanVar(value=False)
    Checkbutton(root, text="Toolpath", variable=toolpath_var, command=update_preview).grid(
        row=2, column=7
    )

    canvas = Canvas(root, width=CANVAS_W, height=CANVAS_H, bg="white")
    canvas.grid(row=3, column=0, columnspan=8, pady=10)

    canvas.bind("<MouseWheel>", lambda e: zoom_canvas(e.delta, e.x, e.y))
    canvas.bind("<Button-4>", lambda e: zoom_canvas(120, e.x, e.y))
    canvas.bind("<Button-5>", lambda e: zoom_canvas(-120, e.x, e.y))
    for press, motion in (("<ButtonPress-1>", "<B1-Motion>"),
                          ("<ButtonPress-2>", "<B2-Motion>")):
        canvas.bind(press, start_pan)
        canvas.bind(motion, do_pan)
    entry.bind("<KeyRelease>", lambda e: update_preview())
    font_height_entry.bind("<KeyRelease>", lambda e: update_preview())
    spacing_entry.bind("<KeyRelease>", lambda e: update_preview())
    size_entry.bind("<KeyRelease>", lambda e: update_preview())

    update_preview()
    root.mainloop()


if __name__ == "__main__":
    main()
