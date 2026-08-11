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

# Settings
TEXT_DEPTH = -0.2
CUT_DEPTH = -0.8
PASS_DEPTH = -0.2
SAFE_Z = 5
SPINDLE_RPM = 10000
FEED_RATE_ENGRAVE = 300
FEED_RATE_CUT = 200
PLUNGE_RATE = 100
PADDING = 10
LETTER_SPACING = 10
CHAR_SPACING = 2
LINE_HEIGHT = 10  # Each glyph is drawn in a 10mm tall cell
GRID_CELL_HEIGHT = 30  # label height including padding

# Font lives in <repo>/fonts/, independent of where the script is run from
FONT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "normalized_full_font.json"
)

with open(FONT_PATH) as f:
    FONT = json.load(f)


def text_width(text):
    return len(text) * (LETTER_SPACING + CHAR_SPACING) - CHAR_SPACING


def draw_letter(char, offset_x, offset_y):
    gcode = []
    if char == " ":
        return []  # spaces just advance the cursor
    strokes = FONT.get(char)
    if strokes is None:
        print(f"WARNING: character '{char}' not found in font. Skipping.")
        return []
    for (x1, y1), (x2, y2) in strokes:
        gcode.append(f"G0 X{offset_x + x1:.2f} Y{offset_y + y1:.2f}")
        gcode.append(f"G1 Z{TEXT_DEPTH:.2f} F{PLUNGE_RATE}")
        gcode.append(f"G1 X{offset_x + x2:.2f} Y{offset_y + y2:.2f} F{FEED_RATE_ENGRAVE}")
        gcode.append(f"G0 Z{SAFE_Z:.2f}")
    return gcode


def generate_grid_gcode(labels, filename, columns=3, spacing_x=20, spacing_y=20):
    # Size the grid cell to the longest label so text never overflows into a neighbour
    cell_width = max(text_width(t) for t in labels) + 2 * PADDING
    cell_height = GRID_CELL_HEIGHT

    gcode = [
        "G21 ; mm",
        "G90 ; absolute",
        f"G0 Z{SAFE_Z:.2f}",
        f"M3 S{SPINDLE_RPM} ; spindle on",
        "G4 P2 ; wait for spindle to reach speed",
        "( Start Grid Layout )",
    ]

    row = col = 0

    for idx, text in enumerate(labels):
        base_x = col * (cell_width + spacing_x)
        base_y = row * (cell_height + spacing_y)

        # Centered text offsets within label
        text_w = text_width(text)
        start_x = base_x + (cell_width - text_w) / 2
        start_y = base_y + (cell_height - LINE_HEIGHT) / 2

        gcode.append(f"( Label {idx+1}: '{text}' at row {row}, col {col} )")

        for i, char in enumerate(text):
            offset = start_x + i * (LETTER_SPACING + CHAR_SPACING)
            gcode += draw_letter(char, offset, start_y)

        # Rectangle cutout with multi-pass; last pass is clamped to CUT_DEPTH
        passes = max(1, math.ceil(abs(CUT_DEPTH) / abs(PASS_DEPTH)))
        for p in range(1, passes + 1):
            z = max(CUT_DEPTH, p * PASS_DEPTH)
            gcode += [
                f"( Cut Label {idx+1} Pass {p} )",
                f"G0 X{base_x:.2f} Y{base_y:.2f}",
                f"G1 Z{z:.2f} F{PLUNGE_RATE}",
                f"G1 X{base_x + cell_width:.2f} Y{base_y:.2f} F{FEED_RATE_CUT}",
                f"G1 X{base_x + cell_width:.2f} Y{base_y + cell_height:.2f}",
                f"G1 X{base_x:.2f} Y{base_y + cell_height:.2f}",
                f"G1 X{base_x:.2f} Y{base_y:.2f}",
                f"G0 Z{SAFE_Z:.2f}",
            ]

        col += 1
        if col >= columns:
            col = 0
            row += 1

    gcode.append("M5 ; spindle off")
    gcode.append("M30 ; End of job")

    with open(filename, "w") as f:
        f.write("\n".join(gcode))

    print(f"\nGrid layout written to {filename}")


def main():
    print("=== CNC G-code Label Grid Generator ===")
    while True:
        raw = input("Enter number of labels [default 1]: ").strip() or "1"
        try:
            count = int(raw)
            if count > 0:
                break
        except ValueError:
            pass
        print("Please enter a positive whole number.")

    labels = []
    for i in range(count):
        label = ""
        while not label:
            label = input(f"Label {i+1}: ").strip()
        labels.append(label)

    os.makedirs("output", exist_ok=True)

    filename = "output/grid_labels.gcode"
    generate_grid_gcode(labels, filename, columns=3)

    print("\nAll labels done and exported as a grid.")


if __name__ == "__main__":
    main()
