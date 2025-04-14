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
from tkinter import StringVar, OptionMenu, Label, Canvas

FONT_DIR = "fonts"
FONT_HEIGHT_MM = 10

def list_available_fonts():
    return [f for f in os.listdir(FONT_DIR) if f.endswith(".json")]

def load_selected_font(name):
    path = os.path.join(FONT_DIR, name)
    with open(path, "r") as f:
        return json.load(f)

def scale_strokes(strokes, scale):
    return [
        [[(x * scale, y * scale) for x, y in segment] for segment in char_strokes]
        for char_strokes in strokes
    ]

def get_scaled_char(char, font_dict, height_mm):
    char_strokes = font_dict.get(char.upper())
    if not char_strokes:
        return []
    base_height = 15
    scale = height_mm / base_height
    return scale_strokes([char_strokes], scale)[0]

def draw_text(canvas, text, font_dict, font_height):
    canvas.delete("all")
    x_offset = 10
    for char in text:
        strokes = get_scaled_char(char, font_dict, font_height)
        for segment in strokes:
            for i in range(len(segment) - 1):
                x1, y1 = segment[i]
                x2, y2 = segment[i+1]
                canvas.create_line(x1 + x_offset, 150 - y1, x2 + x_offset, 150 - y2)
        x_offset += font_height

def update_preview(*args):
    text = entry.get()
    font_dict = load_selected_font(selected_font.get())
    draw_text(canvas, text, font_dict, FONT_HEIGHT_MM)

root = tk.Tk()
root.title("CNC Label Maker")

Label(root, text="Enter Text:").grid(row=0, column=0)
entry = tk.Entry(root)
entry.grid(row=0, column=1)

Label(root, text="Select Font:").grid(row=1, column=0)
selected_font = StringVar()
fonts = list_available_fonts()
selected_font.set(fonts[0])
font_dropdown = OptionMenu(root, selected_font, *fonts)
font_dropdown.grid(row=1, column=1)

canvas = Canvas(root, width=800, height=200, bg="white")
canvas.grid(row=2, column=0, columnspan=2, pady=10)

entry.bind("<KeyRelease>", update_preview)
selected_font.trace("w", update_preview)

root.mainloop()
