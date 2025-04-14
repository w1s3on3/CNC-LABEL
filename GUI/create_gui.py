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

import tkinter as tk
from tkinter import messagebox, filedialog, Toplevel
import json
import os

SETTINGS_FILE = "machine_settings.json"

DEFAULTS = {
    "TEXT_DEPTH": -0.2,
    "CUT_DEPTH": -0.8,
    "PASS_DEPTH": -0.2,
    "SAFE_Z": 5,
    "FEED_RATE_ENGRAVE": 300,
    "FEED_RATE_CUT": 200,
    "PADDING": 10,
    "GRID_CELL_HEIGHT": 40,
    "CHAR_SPACING": 2,
    "LETTER_SPACING": 10,
    "LINE_SPACING": 12
}

settings = DEFAULTS.copy()

if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE) as f:
        settings.update(json.load(f))

with open("normalized_full_font.json") as f:
    FONT = json.load(f)

def draw_letter(char, offset_x, offset_y, gcode_mode=True):
    gcode = []
    strokes = FONT.get(char)
    if not strokes:
        return []
    for (x1, y1), (x2, y2) in strokes:
        if gcode_mode:
            gcode.append(f"G0 X{offset_x + x1:.2f} Y{offset_y + y1:.2f}")
            gcode.append(f"G1 Z{settings['TEXT_DEPTH']:.2f} F{settings['FEED_RATE_ENGRAVE']}")
            gcode.append(f"G1 X{offset_x + x2:.2f} Y{offset_y + y2:.2f}")
            gcode.append(f"G1 Z{settings['SAFE_Z']:.2f}")
        else:
            gcode.append(((offset_x + x1, offset_y + y1), (offset_x + x2, offset_y + y2)))
    return gcode

def generate_grid_gcode(labels, filename, columns=3, spacing_x=20, spacing_y=20):
    gcode = [
        "G21 ; mm",
        "G90 ; absolute",
        f"G1 Z{settings['SAFE_Z']:.2f} F{settings['FEED_RATE_ENGRAVE']}",
        "( Start Grid Layout )",
        "M3 S1000 ; Start spindle"
    ]
    row = col = 0

    for idx, label in enumerate(labels):
        text_width = len(label) * (settings['LETTER_SPACING'] + settings['CHAR_SPACING']) - settings['CHAR_SPACING']
        cell_width = text_width + 2 * settings['PADDING']
        row = idx // columns
        col = idx % columns
        base_x = col * (cell_width + spacing_x)
        base_y = row * (settings['GRID_CELL_HEIGHT'] + spacing_y)
        start_y = base_y + (settings['GRID_CELL_HEIGHT'] - settings['LINE_SPACING']) / 2
        start_x = base_x + (cell_width - text_width) / 2

        gcode.append(f"( Label {idx+1}: '{label}' at row {row}, col {col} )")
        for i, char in enumerate(label):
            offset = start_x + i * (settings['LETTER_SPACING'] + settings['CHAR_SPACING'])
            gcode += draw_letter(char, offset, start_y)

        passes = int(abs(settings['CUT_DEPTH']) / abs(settings['PASS_DEPTH']))
        for p in range(1, passes + 1):
            z = p * settings['PASS_DEPTH']
            gcode += [
                f"( Cut Label {idx+1} Pass {p} )",
                f"G0 X{base_x:.2f} Y{base_y:.2f}",
                f"G1 Z{z:.2f} F{settings['FEED_RATE_CUT']}",
                f"G1 X{base_x + cell_width:.2f} Y{base_y:.2f}",
                f"G1 X{base_x + cell_width:.2f} Y{base_y + settings['GRID_CELL_HEIGHT']:.2f}",
                f"G1 X{base_x:.2f} Y{base_y + settings['GRID_CELL_HEIGHT']:.2f}",
                f"G1 X{base_x:.2f} Y{base_y:.2f}",
                f"G1 Z{settings['SAFE_Z']:.2f}"
            ]

    gcode.append("M5 ; Stop spindle")
    gcode.append("M30 ; End of job")
    os.makedirs("output", exist_ok=True)
    with open(filename, "w") as f:
        f.write("\n".join(gcode))

def draw_preview(canvas, labels, columns=3, show_cuts=True):
    canvas.delete("all")
    spacing_x = 20
    spacing_y = 20
    for idx, label in enumerate(labels):
        text_width = len(label) * (settings['LETTER_SPACING'] + settings['CHAR_SPACING']) - settings['CHAR_SPACING']
        cell_width = text_width + 2 * settings['PADDING']
        row = idx // columns
        col = idx % columns
        base_x = col * (cell_width + spacing_x)
        base_y = row * (settings['GRID_CELL_HEIGHT'] + spacing_y)
        start_y = base_y + (settings['GRID_CELL_HEIGHT'] - settings['LINE_SPACING']) / 2
        start_x = base_x + (cell_width - text_width) / 2

        for i, char in enumerate(label):
            strokes = draw_letter(char, start_x + i * (settings['LETTER_SPACING'] + settings['CHAR_SPACING']), start_y, gcode_mode=False)
            for (x1, y1), (x2, y2) in strokes:
                canvas.create_line(x1, 400 - y1, x2, 400 - y2, fill="red")

        if show_cuts:
            canvas.create_rectangle(
                base_x, 400 - base_y,
                base_x + cell_width, 400 - (base_y + settings['GRID_CELL_HEIGHT']),
                outline="black"
            )

def update_preview():
    labels = label_input.get("1.0", tk.END).strip().splitlines()
    draw_preview(preview_canvas, labels, show_cuts=show_cut.get())

def generate_gcode():
    labels = label_input.get("1.0", tk.END).strip().splitlines()
    if not labels:
        messagebox.showerror("Error", "Enter at least one label.")
        return
    filename = filedialog.asksaveasfilename(defaultextension=".gcode", filetypes=[("G-code files", "*.gcode")])
    if not filename:
        return
    generate_grid_gcode(labels, filename)
    messagebox.showinfo("Done", f"G-code saved to:\n{filename}")

def open_settings():
    win = Toplevel(root)
    win.title("Machine Settings")
    entries = {}
    for i, (key, val) in enumerate(settings.items()):
        tk.Label(win, text=key).grid(row=i, column=0, sticky="w")
        e = tk.Entry(win)
        e.insert(0, str(val))
        e.grid(row=i, column=1)
        entries[key] = e

    def save():
        for k in entries:
            try:
                settings[k] = float(entries[k].get())
            except ValueError:
                pass
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        win.destroy()
        update_preview()

    tk.Button(win, text="Save", command=save).grid(row=len(settings), columnspan=2)

root = tk.Tk()
root.title("CNC Label Maker")

tk.Label(root, text="Enter labels (one per line):").pack()
label_input = tk.Text(root, height=6, width=50)
label_input.pack()

button_frame = tk.Frame(root)
button_frame.pack(pady=5)
tk.Button(button_frame, text="Settings ⚙️", command=open_settings).pack(side=tk.LEFT, padx=5)
tk.Button(button_frame, text="Preview", command=update_preview).pack(side=tk.LEFT, padx=5)
tk.Button(button_frame, text="Export G-code", command=generate_gcode).pack(side=tk.LEFT, padx=5)

show_cut = tk.BooleanVar(value=True)
tk.Checkbutton(root, text="Show Cut Paths in Preview", variable=show_cut, command=update_preview).pack()

preview_canvas = tk.Canvas(root, width=700, height=400, bg="white")
preview_canvas.pack()

root.mainloop()
