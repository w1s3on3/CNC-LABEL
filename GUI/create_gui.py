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
import tkinter as tk
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
    "feed_rate": 300,
    "plunge_rate": 100,
    "spindle_rpm": 10000,
    "laser_power": 1000,
    "tool_mode": "Spindle",
    "cutout_padding": 2.0,
    "laser_kerf": 0.15,
    "tab_width": 3.0,
    "tab_height": 0.4,
    "material_width": 1000,
    "material_height": 600,
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


def text_geometry(label, font_path, font_height_mm):
    """Shapely geometry for a label with letter counters (the hole in O, A, e…)
    as real holes, scaled so capitals are font_height_mm tall.

    Origin is the bottom-left of the text bounding box, Y up (machine-style).
    Returns None for labels with no printable outline.
    """
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
    return shapely.affinity.translate(geom, xoff=-minx, yoff=-miny)


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
                 material_width, snap_grid=None, label_size=None):
    """Place labels top-down on the material, centered horizontally.

    Coordinates are "canvas" mm: origin top-left, Y increases downward (what
    the preview shows). Each item's geom keeps its own origin (text bbox
    bottom-left, Y up); x/y_top place that box on the material.

    label_size: (width, height) in mm for fixed-size labels, or None to size
    each label from its text (bbox + padding). A fixed-size label whose text
    (plus padding clearance) doesn't fit is flagged fits=False — the caller
    decides whether to warn or refuse.
    """
    def snap(v):
        return round(v / snap_grid) * snap_grid if snap_grid else v

    items = []
    cursor = 40.0  # canvas y of the top edge of the next label
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
        bx0 = snap((material_width - label_w) / 2)
        by0 = snap(cursor)
        items.append({
            "label": label, "geom": geom,
            "x": bx0 + (label_w - width) / 2,
            "y_top": by0 + (label_h - height) / 2,
            "width": width, "height": height,
            "cutout": (bx0, by0, bx0 + label_w, by0 + label_h),
            "fits": fits,
        })
        cursor = by0 + label_h + spacing
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

    def polyline(points, depth):
        sx, sy = points[0]
        g.append(f"G0 X{sx:.3f} Y{sy:.3f}")
        if not laser:
            g.append(f"G1 Z{-depth:.3f} F{plunge:.0f}")
        first = True
        for px, py in points[1:]:
            f_part = f" F{feed:.0f}" if first else ""
            g.append(f"G1 X{px:.3f} Y{py:.3f}{f_part}")
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
    ("feed_rate", "Feed Rate (mm/min)"),
    ("plunge_rate", "Plunge Rate (mm/min)"),
    ("spindle_rpm", "Spindle RPM"),
    ("laser_power", "Laser Power (S value)"),
    ("cutout_padding", "Cutout Padding (mm)"),
    ("laser_kerf", "Laser Kerf (mm)"),
    ("tab_width", "Tab Width (mm, 0 = no tabs)"),
    ("tab_height", "Tab Height (mm, 0 = no tabs)"),
    ("material_width", "Material Width (mm)"),
    ("material_height", "Material Height (mm)"),
]

SNAP_GRID_MM = 5
MAX_CANVAS_W, MAX_CANVAS_H = 1200, 700


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
        "font_path": next(iter(system_fonts.values())),
    }

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
        return build_layout(
            labels, state["font_path"], font_height, spacing,
            cnc_settings["cutout_padding"], cnc_settings["material_width"],
            snap_grid=SNAP_GRID_MM if snap_var.get() else None,
            label_size=label_size,
        )

    def update_preview():
        canvas.delete("all")
        zoom = state["zoom"]
        mat_w, mat_h = cnc_settings["material_width"], cnc_settings["material_height"]
        canvas.config(width=min(mat_w, MAX_CANVAS_W), height=min(mat_h, MAX_CANVAS_H))

        if read_inputs() is None:
            canvas.create_text(
                200, 40, text="Invalid font height, spacing or label size", fill="red"
            )
            return
        layout = current_layout()

        # Material boundary
        canvas.create_rectangle(0, 0, mat_w * zoom, mat_h * zoom, outline="gray")

        overflow = False
        for item in layout:
            x, y_top, height = item["x"], item["y_top"], item["height"]

            # geom is Y-up with origin at the text bbox bottom-left; the canvas
            # is Y-down, so: canvas_y = y_top + height - geom_y
            def to_canvas(coords):
                pts = np.asarray(coords, dtype=float).copy()
                pts[:, 0] = (pts[:, 0] + x) * zoom
                pts[:, 1] = (y_top + height - pts[:, 1]) * zoom
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
                cx0 * zoom, cy0 * zoom, cx1 * zoom, cy1 * zoom,
                outline="blue" if item["fits"] else "red", dash=(2, 2),
            )
            if cy1 > mat_h or cx0 < 0:
                overflow = True

        warnings = []
        if overflow:
            warnings.append("labels exceed material size")
        if any(not item["fits"] for item in layout):
            warnings.append("text too big for label size (red)")
        if warnings:
            canvas.create_text(
                min(mat_w, MAX_CANVAS_W) / 2, 20,
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
            item["cutout"][3] > cnc_settings["material_height"] or item["cutout"][0] < 0
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
            messagebox.showinfo("Success", f"G-code saved to {file_path}")

    def open_settings():
        win = Toplevel(root)
        win.title("Settings")
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
            for key in ("pass_depth", "safe_z", "feed_rate", "plunge_rate"):
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

    def zoom_canvas(delta):
        state["zoom"] *= 1.1 if delta > 0 else 0.9
        update_preview()

    def reset_zoom():
        state["zoom"] = 1.0
        update_preview()

    def select_font(name):
        state["font_path"] = system_fonts[name]
        update_preview()

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

    Button(root, text="⚙ Settings", command=open_settings).grid(row=2, column=2)
    Button(root, text="🔄 Reset Zoom", command=reset_zoom).grid(row=2, column=3)
    Button(root, text="💾 Export G-code", command=generate_gcode).grid(row=2, column=4)

    snap_var = tk.BooleanVar(value=False)
    Checkbutton(root, text="Snap to Grid", variable=snap_var, command=update_preview).grid(
        row=2, column=5
    )
    fill_text_var = tk.BooleanVar(value=False)
    Checkbutton(root, text="Fill Text", variable=fill_text_var, command=update_preview).grid(
        row=2, column=6
    )

    canvas = Canvas(
        root,
        width=min(cnc_settings["material_width"], MAX_CANVAS_W),
        height=min(cnc_settings["material_height"], MAX_CANVAS_H),
        bg="white",
    )
    canvas.grid(row=3, column=0, columnspan=7, pady=10)

    canvas.bind("<MouseWheel>", lambda e: zoom_canvas(e.delta))
    canvas.bind("<Button-4>", lambda e: zoom_canvas(120))
    canvas.bind("<Button-5>", lambda e: zoom_canvas(-120))
    entry.bind("<KeyRelease>", lambda e: update_preview())
    font_height_entry.bind("<KeyRelease>", lambda e: update_preview())
    spacing_entry.bind("<KeyRelease>", lambda e: update_preview())
    size_entry.bind("<KeyRelease>", lambda e: update_preview())

    update_preview()
    root.mainloop()


if __name__ == "__main__":
    main()
