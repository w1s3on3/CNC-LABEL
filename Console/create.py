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

# Needs alot of fixes. working on the gui first!

import os
import json

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
LINE_HEIGHT = 10  # Each glyph is drawn in a 10mm tall cell
GRID_CELL_WIDTH = 80   # set based on your longest expected label
GRID_CELL_HEIGHT = 30  # set for height including padding

# Load stroke font
with open("normalized_full_font.json") as f:
    FONT = json.load(f)

def estimate_label_size(text):
    return len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING + 2 * PADDING, LINE_HEIGHT + 2 * PADDING

def draw_letter(char, offset_x, offset_y):
    gcode = []
    strokes = FONT.get(char)
    if strokes is None:
        print(f"⚠️  Character '{char}' not found in font. Skipping.")
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
        label_w, label_h = estimate_label_size(text)

        # Calculate base X,Y for label position in grid
        base_x = col * (GRID_CELL_WIDTH + spacing_x)
        base_y = row * (GRID_CELL_HEIGHT + spacing_y)


        # Centered text offsets within label
        text_w = len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING
        start_x = base_x + (GRID_CELL_WIDTH - text_w) / 2
        start_y = base_y + (GRID_CELL_HEIGHT - LINE_HEIGHT) / 2


        gcode.append(f"( Label {idx+1}: '{text}' at row {row}, col {col} )")

        for i, char in enumerate(text):
            offset = start_x + i * (LETTER_SPACING + CHAR_SPACING)
            gcode += draw_letter(char, offset, start_y)

        # Rectangle cutout with multi-pass
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

    with open(filename, "w") as f:
        f.write("\n".join(gcode))

    print(f"\n🧱 Grid layout written to {filename}")

def main():
    print("=== CNC G-code Label Grid Generator ===")
    count = int(input("Enter number of labels [default 1]: ") or "1")

    labels = []
    for i in range(count):
        label = ""
        while not label:
            label = input(f"Label {i+1}: ").strip()
        labels.append(label)

    os.makedirs("output", exist_ok=True)

    filename = "output/grid_labels.gcode"
    generate_grid_gcode(labels, filename, columns=3)

    print("\n✅ All labels done and exported as a grid.")

if __name__ == "__main__":
    main()
