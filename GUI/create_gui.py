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
from tkinter import messagebox, filedialog
import json
import os

# Settings
TEXT_DEPTH = -0.2
CUT_DEPTH = -0.8
PASS_DEPTH = -0.2
SAFE_Z = 5
FEED_RATE_ENGRAVE = 300
FEED_RATE_CUT = 200
PADDING = 10
LETTER_SPACING = 10
CHAR_SPACING = 2
LINE_HEIGHT = 10
GRID_CELL_WIDTH = 80
GRID_CELL_HEIGHT = 30

# Load font
with open("normalized_full_font.json") as f:
    FONT = json.load(f)

def estimate_label_size(text):
    text_width = len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING
    return text_width + 2 * PADDING, LINE_HEIGHT + 2 * PADDING

def draw_letter(char, offset_x, offset_y):
    gcode = []
    strokes = FONT.get(char)
    if not strokes:
        return []
    for (x1, y1), (x2, y2) in strokes:
        gcode.append(f"G0 X{offset_x + x1:.2f} Y{offset_y + y1:.2f}")
        gcode.append(f"G1 Z{TEXT_DEPTH:.2f} F{FEED_RATE_ENGRAVE}")
        gcode.append(f"G1 X{offset_x + x2:.2f} Y{offset_y + y2:.2f}")
        gcode.append(f"G1 Z{SAFE_Z:.2f}")
    return gcode

def generate_grid_gcode(labels, filename, columns=3, spacing_x=20, spacing_y=20):
    gcode = [
        "G21 ; mm",
        "G90 ; absolute",
        f"G1 Z{SAFE_Z:.2f} F{FEED_RATE_ENGRAVE}",
        "( Start Grid Layout )"
    ]

    row = col = 0

    for idx, text in enumerate(labels):
        base_x = col * (GRID_CELL_WIDTH + spacing_x)
        base_y = row * (GRID_CELL_HEIGHT + spacing_y)

        text_width = len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING
        start_x = base_x + (GRID_CELL_WIDTH - text_width) / 2
        start_y = base_y + (GRID_CELL_HEIGHT - LINE_HEIGHT) / 2

        gcode.append(f"( Label {idx+1}: '{text}' at row {row}, col {col} )")

        for i, char in enumerate(text):
            offset = start_x + i * (LETTER_SPACING + CHAR_SPACING)
            gcode += draw_letter(char, offset, start_y)

        passes = int(abs(CUT_DEPTH) / abs(PASS_DEPTH))
        for p in range(1, passes + 1):
            z = p * PASS_DEPTH
            gcode += [
                f"( Cut Label {idx+1} Pass {p} )",
                f"G0 X{base_x:.2f} Y{base_y:.2f}",
                f"G1 Z{z:.2f} F{FEED_RATE_CUT}",
                f"G1 X{base_x + GRID_CELL_WIDTH:.2f} Y{base_y:.2f}",
                f"G1 X{base_x + GRID_CELL_WIDTH:.2f} Y{base_y + GRID_CELL_HEIGHT:.2f}",
                f"G1 X{base_x:.2f} Y{base_y + GRID_CELL_HEIGHT:.2f}",
                f"G1 X{base_x:.2f} Y{base_y:.2f}",
                f"G1 Z{SAFE_Z:.2f}"
            ]

        col += 1
        if col >= columns:
            col = 0
            row += 1

    gcode.append("M30 ; End of job")

    os.makedirs("output", exist_ok=True)
    with open(filename, "w") as f:
        f.write("\n".join(gcode))

def draw_preview(canvas, labels, columns=3):
    canvas.delete("all")
    spacing_x = 20
    spacing_y = 20

    for idx, text in enumerate(labels):
        row = idx // columns
        col = idx % columns
        base_x = col * (GRID_CELL_WIDTH + spacing_x)
        base_y = row * (GRID_CELL_HEIGHT + spacing_y)

        text_width = len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING
        start_x = base_x + (GRID_CELL_WIDTH - text_width) / 2
        start_y = base_y + (GRID_CELL_HEIGHT - LINE_HEIGHT) / 2

        for i, char in enumerate(text):
            strokes = FONT.get(char)
            if not strokes:
                continue
            offset = start_x + i * (LETTER_SPACING + CHAR_SPACING)
            for (x1, y1), (x2, y2) in strokes:
                canvas.create_line(
                    offset + x1, 400 - (start_y + y1),
                    offset + x2, 400 - (start_y + y2),
                    fill="red", width=1
                )

        canvas.create_rectangle(
            base_x, 400 - base_y,
            base_x + GRID_CELL_WIDTH, 400 - (base_y + GRID_CELL_HEIGHT),
            outline="black"
        )

def update_preview():
    labels = label_input.get("1.0", tk.END).strip().splitlines()
    draw_preview(preview_canvas, labels)

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

# GUI Setup
root = tk.Tk()
root.title("CNC Label Generator")

tk.Label(root, text="Enter labels (one per line):").pack()
label_input = tk.Text(root, height=6, width=50)
label_input.pack()

button_frame = tk.Frame(root)
button_frame.pack(pady=5)
tk.Button(button_frame, text="Preview", command=update_preview).pack(side=tk.LEFT, padx=5)
tk.Button(button_frame, text="Export G-code", command=generate_gcode).pack(side=tk.LEFT, padx=5)

preview_canvas = tk.Canvas(root, width=500, height=400, bg="white")
preview_canvas.pack()

root.mainloop()
