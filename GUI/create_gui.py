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
from tkinter import StringVar, OptionMenu, Label, Canvas, Entry, Toplevel, Button, Checkbutton, filedialog
from matplotlib.font_manager import FontProperties, findSystemFonts
from matplotlib.textpath import TextPath
import matplotlib.path as mpath
import numpy as np
import svgwrite

CANVAS_WIDTH = 1000
CANVAS_HEIGHT = 600

cnc_settings = {
    "text_cut_depth": 0.2,
    "label_cutout_depth": 1.6,
    "tool_diameter": 0.3,
    "safe_z": 5.0,
    "feed_rate": 300,
    "tool_mode": "Spindle",
    "cutout_padding": 2.0
}

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
    return font_dict

system_fonts = get_system_fonts()
selected_font_path = [list(system_fonts.values())[0]]

def snap(val, grid=5):
    return round(val / grid) * grid if grid_snapping[0] else val

def render_char_path(char, font_path, font_height):
    fp = FontProperties(fname=font_path, size=font_height)
    return TextPath((0, 0), char, prop=fp)

def update_preview():
    canvas.delete("all")
    font_path = selected_font_path[0]
    text = entry.get("1.0", "end").strip()
    font_height = float(font_height_entry.get())
    spacing = float(spacing_entry.get())
    padding = cnc_settings["cutout_padding"]
    labels = [lbl.strip().rstrip(",") for lbl in text.splitlines() if lbl.strip()]
    x_start = 10
    y_start = 40
    zoom = zoom_scale[0]

    for label in labels:
        tp = TextPath((0, 0), label, prop=FontProperties(fname=font_path, size=font_height))
        bbox = tp.get_extents()
        width = bbox.width
        height = bbox.height
        x = snap((CANVAS_WIDTH - width) / 2)
        y = snap(y_start)

        for poly in tp.to_polygons():
            for i in range(len(poly) - 1):
                x1, y1 = poly[i]
                x2, y2 = poly[i + 1]
                canvas.create_line((x + x1) * zoom, (y - y1) * zoom, (x + x2) * zoom, (y - y2) * zoom)

        canvas.create_rectangle(
            (x - padding) * zoom,
            (y - height - padding) * zoom,
            (x + width + padding) * zoom,
            (y + padding) * zoom,
            outline="gray", dash=(3, 2)
        )

        y_start += height + spacing + padding * 2
        if y_start > CANVAS_HEIGHT - 100:
            y_start = 40

def open_settings():
    win = Toplevel(root)
    win.title("Settings")
    def save():
        cnc_settings["text_cut_depth"] = float(text_cut_depth.get())
        cnc_settings["label_cutout_depth"] = float(label_cutout_depth.get())
        cnc_settings["tool_diameter"] = float(tool_diameter.get())
        cnc_settings["safe_z"] = float(safe_z.get())
        cnc_settings["feed_rate"] = float(feed_rate.get())
        cnc_settings["tool_mode"] = tool_mode.get()
        cnc_settings["cutout_padding"] = float(cutout_padding.get())
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
    Label(win, text="Tool Mode:").grid(row=6, column=0)
    tool_mode = StringVar(value=cnc_settings["tool_mode"])
    OptionMenu(win, tool_mode, "Spindle", "Laser").grid(row=6, column=1)
    Button(win, text="Save", command=save).grid(row=7, column=0, columnspan=2, pady=10)

def zoom_canvas(event):
    if event.delta > 0:
        zoom_scale[0] *= 1.1
    else:
        zoom_scale[0] /= 1.1
    update_preview()

def reset_zoom():
    zoom_scale[0] = 1.0
    update_preview()

def toggle_snap():
    grid_snapping[0] = snap_var.get()
    update_preview()

# --- GUI Setup ---
root = tk.Tk()
root.title("CNC Label Maker - TTF Full Version")

Label(root, text="Labels (one per line):").grid(row=0, column=0, sticky="e")
entry = tk.Text(root, height=4, width=50)
entry.grid(row=0, column=1, columnspan=3, sticky="w")

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

snap_var = tk.BooleanVar(value=False)
Checkbutton(root, text="Snap to Grid", variable=snap_var, command=toggle_snap).grid(row=2, column=4)

canvas = Canvas(root, width=CANVAS_WIDTH, height=CANVAS_HEIGHT, bg="white")
canvas.grid(row=3, column=0, columnspan=5, pady=10)

canvas.bind("<MouseWheel>", zoom_canvas)
entry.bind("<KeyRelease>", lambda e: update_preview())
font_height_entry.bind("<KeyRelease>", lambda e: update_preview())
spacing_entry.bind("<KeyRelease>", lambda e: update_preview())

update_preview()
root.mainloop()
