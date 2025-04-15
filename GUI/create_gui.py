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

import os
import json
import tkinter as tk
from tkinter import StringVar, OptionMenu, Label, Canvas, Entry, Toplevel, Button, Checkbutton, filedialog, messagebox
from matplotlib.font_manager import FontProperties, findSystemFonts
from matplotlib.textpath import TextPath
from matplotlib.path import Path
import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union, polygonize
import shapely.affinity  


SETTINGS_FILE = "machine_settings.json"

cnc_settings = {
    "text_cut_depth": 0.2,
    "label_cutout_depth": 0.8,
    "tool_diameter": 0.3,
    "safe_z": 5.0,
    "feed_rate": 300,
    "tool_mode": "Spindle",
    "cutout_padding": 2.0,
    "material_width": 1000,
    "material_height": 600
}

def load_settings():
    defaults = cnc_settings.copy()
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            loaded = json.load(f)
            defaults.update(loaded)
    cnc_settings.update(defaults)

def save_settings():
    with open(SETTINGS_FILE, "w") as f:
        json.dump(cnc_settings, f, indent=2)

load_settings()

zoom_scale = [1.0]
grid_snapping = [False]

def get_system_fonts():
    fonts = findSystemFonts(fontpaths=None, fontext='ttf')
    font_dict = {}
    for path in fonts:
        try:
            name = FontProperties(fname=path).get_name()
            if name not in font_dict:
                font_dict[name] = path
        except:
            pass
    return dict(sorted(font_dict.items()))

system_fonts = get_system_fonts()
selected_font_path = [list(system_fonts.values())[0]]

def snap(val, grid=5):
    return round(val / grid) * grid if grid_snapping[0] else val

def hatch_fill(poly, spacing=0.3):
    from shapely.geometry import LineString
    bounds = poly.bounds
    ymin, ymax = bounds[1], bounds[3]
    hatch_lines = []
    y = ymin - spacing
    while y < ymax + spacing:
        line = LineString([(bounds[0]-1, y), (bounds[2]+1, y)])
        intersection = poly.intersection(line)
        if intersection.is_empty:
            y += spacing
            continue
        if intersection.geom_type == 'MultiLineString':
            for geom in intersection.geoms:
                x0, y0, x1, y1 = geom.bounds
                hatch_lines.append(((x0, y0), (x1, y1)))
        elif intersection.geom_type == 'LineString':
            x0, y0, x1, y1 = intersection.bounds
            hatch_lines.append(((x0, y0), (x1, y1)))
        y += spacing
    return hatch_lines

def update_preview():
    canvas.delete("all")
    CANVAS_WIDTH = cnc_settings["material_width"]
    CANVAS_HEIGHT = cnc_settings["material_height"]
    canvas.config(width=CANVAS_WIDTH, height=CANVAS_HEIGHT)

    font_path = selected_font_path[0]
    text = entry.get("1.0", "end").strip()
    try:
        font_height = float(font_height_entry.get())
        spacing = float(spacing_entry.get())
    except ValueError:
        canvas.create_text(CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2, text="Invalid font height or spacing", fill="red")
        return

    padding = cnc_settings["cutout_padding"]
    labels = [lbl.strip().rstrip(",") for lbl in text.splitlines() if lbl.strip()]
    y_start = 40
    zoom = zoom_scale[0]

    for label in labels:
        tp = TextPath((0, 0), label, prop=FontProperties(fname=font_path, size=font_height * zoom))
        bbox = tp.get_extents()
        width, height = bbox.width, bbox.height
        x = snap((CANVAS_WIDTH - width) / 2)
        y = snap(y_start)

        # Convert TextPath to shapely polygons directly
        polys = [Polygon(poly) for poly in tp.to_polygons()]
        merged_poly = unary_union(polys).buffer(0)  # Correct geometry

        def draw_shapely_polygon(poly):
            if poly.geom_type == 'Polygon':
                exterior = np.array(poly.exterior.coords)
                exterior[:, 1] *= -1
                exterior[:, 0] += x
                exterior[:, 1] += y
                flat_exterior = [c for point in exterior for c in point]
                canvas.create_polygon(flat_exterior, fill="black", outline="black")

                for interior in poly.interiors:
                    hole = np.array(interior.coords)
                    hole[:, 1] *= -1
                    hole[:, 0] += x
                    hole[:, 1] += y
                    flat_hole = [c for point in hole for c in point]
                    canvas.create_polygon(flat_hole, fill="white", outline="white")

            elif poly.geom_type == 'MultiPolygon':
                for sub_poly in poly.geoms:
                    draw_shapely_polygon(sub_poly)

        if fill_text_var.get():
            draw_shapely_polygon(merged_poly)
        else:
            for poly in polys:
                poly_np = np.array(poly.exterior.coords)
                poly_np[:, 1] *= -1
                poly_np[:, 0] += x
                poly_np[:, 1] += y
                for i in range(len(poly_np) - 1):
                    x1, y1 = poly_np[i]
                    x2, y2 = poly_np[i + 1]
                    canvas.create_line(x1, y1, x2, y2, fill="red")

        canvas.create_rectangle(
            x - padding, y - height - padding,
            x + width + padding, y + padding,
            outline="blue", dash=(2, 2)
        )

        y_start += height + spacing + padding * 2
        if y_start > CANVAS_HEIGHT - 100:
            canvas.create_text(CANVAS_WIDTH / 2, y_start, text="Warning: Labels exceed material height", fill="orange")
            break


def open_settings():
    win = Toplevel(root)
    win.title("Settings")
    def save():
        try:
            cnc_settings["text_cut_depth"] = float(text_cut_depth.get())
            cnc_settings["label_cutout_depth"] = float(label_cutout_depth.get())
            cnc_settings["tool_diameter"] = float(tool_diameter.get())
            cnc_settings["safe_z"] = float(safe_z.get())
            cnc_settings["feed_rate"] = float(feed_rate.get())
            cnc_settings["tool_mode"] = tool_mode.get()
            cnc_settings["cutout_padding"] = float(cutout_padding.get())
            cnc_settings["material_width"] = float(material_width.get())
            cnc_settings["material_height"] = float(material_height.get())
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return
        save_settings()
        win.destroy()
        update_preview()

    Label(win, text="Text Cut Depth:").grid(row=0, column=0)
    text_cut_depth = Entry(win); text_cut_depth.insert(0, cnc_settings["text_cut_depth"]); text_cut_depth.grid(row=0, column=1)
    Label(win, text="Label Cutout Depth:").grid(row=1, column=0)
    label_cutout_depth = Entry(win); label_cutout_depth.insert(0, cnc_settings["label_cutout_depth"]); label_cutout_depth.grid(row=1, column=1)
    Label(win, text="Tool Diameter:").grid(row=2, column=0)
    tool_diameter = Entry(win); tool_diameter.insert(0, cnc_settings["tool_diameter"]); tool_diameter.grid(row=2, column=1)
    Label(win, text="Safe Z Height:").grid(row=3, column=0)
    safe_z = Entry(win); safe_z.insert(0, cnc_settings["safe_z"]); safe_z.grid(row=3, column=1)
    Label(win, text="Feed Rate:").grid(row=4, column=0)
    feed_rate = Entry(win); feed_rate.insert(0, cnc_settings["feed_rate"]); feed_rate.grid(row=4, column=1)
    Label(win, text="Cutout Padding:").grid(row=5, column=0)
    cutout_padding = Entry(win); cutout_padding.insert(0, cnc_settings["cutout_padding"]); cutout_padding.grid(row=5, column=1)
    Label(win, text="Material Width:").grid(row=6, column=0)
    material_width = Entry(win); material_width.insert(0, cnc_settings["material_width"]); material_width.grid(row=6, column=1)
    Label(win, text="Material Height:").grid(row=7, column=0)
    material_height = Entry(win); material_height.insert(0, cnc_settings["material_height"]); material_height.grid(row=7, column=1)
    Label(win, text="Tool Mode:").grid(row=8, column=0)
    tool_mode = StringVar(value=cnc_settings["tool_mode"])
    OptionMenu(win, tool_mode, "Spindle", "Laser").grid(row=8, column=1)
    Button(win, text="Save", command=save).grid(row=9, column=0, columnspan=2, pady=10)

def generate_gcode():
    CANVAS_WIDTH = cnc_settings["material_width"]
    CANVAS_HEIGHT = cnc_settings["material_height"]
    font_path = selected_font_path[0]
    text = entry.get("1.0", "end").strip()
    try:
        font_height = float(font_height_entry.get())
        spacing = float(spacing_entry.get())
    except ValueError:
        messagebox.showerror("Error", "Invalid font height or spacing")
        return
    padding = cnc_settings["cutout_padding"]
    labels = [lbl.strip().rstrip(",") for lbl in text.splitlines() if lbl.strip()]
    gcode = []
    y_start = 40  # Start 40mm from the top, consistent with preview

    gcode.append("G21 ; mm mode")
    gcode.append("G90 ; absolute positioning")
    gcode.append(f"G0 Z{cnc_settings['safe_z']}")

    if cnc_settings["tool_mode"] == "Spindle":
        gcode.append("M3 S10000 ; spindle on")
    else:
        gcode.append("M3 S100 ; laser on")

    for label in labels:
        tp = TextPath((0, 0), label, prop=FontProperties(fname=font_path, size=font_height))
        bbox = tp.get_extents()
        width = bbox.width
        height = bbox.height
        # Center the text horizontally, consistent with preview
        x = snap((CANVAS_WIDTH - width) / 2)
        # Position y to match the preview's y_start progression
        y = snap(y_start)

        gcode.append(f"(Label: {label})")

        for poly in tp.to_polygons():
            poly = Polygon(poly)
            # Flip Y-axis to match G-code (Y increases upward, origin at bottom-left)
            poly = shapely.affinity.scale(poly, xfact=-1, yfact=-1, origin=(0, 0))
            # Translate to the centered position
            poly = shapely.affinity.translate(poly, xoff=x + width, yoff=y)

            if fill_text_var.get():
                hatch_lines = hatch_fill(poly, spacing=cnc_settings["tool_diameter"] * 0.8)
                for (sx, sy), (ex, ey) in hatch_lines:
                    gcode.append(f"G0 X{sx:.3f} Y{sy:.3f}")
                    gcode.append(f"G1 Z{-cnc_settings['text_cut_depth']:.3f} F{cnc_settings['feed_rate']}")
                    gcode.append(f"G1 X{ex:.3f} Y{ey:.3f}")
                    gcode.append(f"G0 Z{cnc_settings['safe_z']}")
            else:
                exterior_coords = np.array(poly.exterior.coords)
                sx, sy = exterior_coords[0]
                gcode.append(f"G0 X{sx:.3f} Y{sy:.3f}")
                gcode.append(f"G1 Z{-cnc_settings['text_cut_depth']:.3f} F{cnc_settings['feed_rate']}")
                for px, py in exterior_coords[1:]:
                    gcode.append(f"G1 X{px:.3f} Y{py:.3f}")
                gcode.append(f"G0 Z{cnc_settings['safe_z']}")

        # Cutout rectangle around the label
        cutout_x_min = x - padding
        cutout_y_min = y - height - padding
        cutout_x_max = x + width + padding
        cutout_y_max = y + padding

        gcode.append(f"(Cutout for label: {label})")
        gcode.append(f"G0 Z{cnc_settings['safe_z']}")

        gcode.append(f"G0 X{cutout_x_min:.3f} Y{cutout_y_min:.3f}")
        gcode.append(f"G1 Z{-cnc_settings['label_cutout_depth']:.3f} F{cnc_settings['feed_rate']}")
        gcode.append(f"G1 X{cutout_x_max:.3f} Y{cutout_y_min:.3f}")
        gcode.append(f"G1 X{cutout_x_max:.3f} Y{cutout_y_max:.3f}")
        gcode.append(f"G1 X{cutout_x_min:.3f} Y{cutout_y_max:.3f}")
        gcode.append(f"G1 X{cutout_x_min:.3f} Y{cutout_y_min:.3f}")
        gcode.append(f"G0 Z{cnc_settings['safe_z']}")

        # Increment y_start for the next label, consistent with preview
        y_start += height + spacing + padding * 2

    gcode.append("M5 ; stop spindle/laser")
    gcode.append("M2 ; end program")

    file_path = filedialog.asksaveasfilename(defaultextension=".gcode", filetypes=[("G-code files", "*.gcode")])
    if file_path:
        with open(file_path, "w") as f:
            f.write("\n".join(gcode))
        messagebox.showinfo("Success", f"G-code saved to {file_path}")

def zoom_canvas(event):
    delta = event["delta"] if isinstance(event, dict) else event.delta
    zoom_scale[0] *= 1.1 if delta > 0 else 0.9
    update_preview()

def reset_zoom():
    zoom_scale[0] = 1.0
    update_preview()

def toggle_snap():
    grid_snapping[0] = snap_var.get()
    update_preview()

root = tk.Tk()
root.title("CNC Label Maker")

fill_text_var = tk.BooleanVar(value=False)

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

Label(root, text="Font:").grid(row=2, column=0, sticky="e")
font_name = StringVar()
font_name.set(list(system_fonts.keys())[0])
font_dropdown = OptionMenu(root, font_name, *system_fonts.keys(),
                          command=lambda name: selected_font_path.__setitem__(0, system_fonts[name]) or update_preview())
font_dropdown.grid(row=2, column=1, sticky="w")

Button(root, text="⚙ Settings", command=open_settings).grid(row=2, column=2)
Button(root, text="🔄 Reset Zoom", command=reset_zoom).grid(row=2, column=3)
Button(root, text="💾 Export G-code", command=generate_gcode).grid(row=2, column=4)

snap_var = tk.BooleanVar(value=False)
Checkbutton(root, text="Snap to Grid", variable=snap_var, command=toggle_snap).grid(row=2, column=5)
fill_text_var = tk.BooleanVar(value=False)
Checkbutton(root, text="Fill Text", variable=fill_text_var, command=update_preview).grid(row=2, column=6)

canvas = Canvas(root, width=cnc_settings["material_width"], height=cnc_settings["material_height"], bg="white")
canvas.grid(row=3, column=0, columnspan=6, pady=10)

canvas.bind("<MouseWheel>", zoom_canvas)
canvas.bind("<Button-4>", lambda e: zoom_canvas({"delta": 120}))
canvas.bind("<Button-5>", lambda e: zoom_canvas({"delta": -120}))
entry.bind("<KeyRelease>", lambda e: update_preview())
font_height_entry.bind("<KeyRelease>", lambda e: update_preview())
spacing_entry.bind("<KeyRelease>", lambda e: update_preview())

update_preview()
root.mainloop()
