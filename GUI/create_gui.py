
import os
import json
import tkinter as tk
from tkinter import StringVar, OptionMenu, Label, Canvas, Entry, Toplevel, Button, filedialog

FONT_DIR = "fonts"
CANVAS_WIDTH = 1000
CANVAS_HEIGHT = 600

cnc_settings = {
    "text_cut_depth": 0.2,
    "label_cutout_depth": 1.6,
    "tool_diameter": 0.3,
    "safe_z": 5.0,
    "feed_rate": 300,
    "tool_mode": "Spindle"
}

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
    base_height = 10
    scale = height_mm / base_height
    return scale_strokes([char_strokes], scale)[0]

def draw_label(canvas, text, font_dict, font_height, start_x, start_y, padding=2):
    x_offset = start_x
    label_start_x = x_offset
    for char in text:
        strokes = get_scaled_char(char, font_dict, font_height)
        for segment in strokes:
            for i in range(len(segment) - 1):
                x1, y1 = segment[i]
                x2, y2 = segment[i + 1]
                canvas.create_line(x1 + x_offset, start_y - y1, x2 + x_offset, start_y - y2)
        x_offset += font_height * 0.75
    label_width = x_offset - label_start_x
    box_x1 = label_start_x - padding
    box_y1 = start_y - font_height - padding
    box_x2 = x_offset + padding
    box_y2 = start_y + padding
    canvas.create_rectangle(box_x1, box_y1, box_x2, box_y2, outline="gray", dash=(2, 2))

def draw_all_labels(canvas, labels, font_dict, font_height, spacing):
    canvas.delete("all")
    x_start = 10
    y_start = 30
    x = x_start
    y = y_start
    for label in labels:
        draw_label(canvas, label, font_dict, font_height, x, y)
        y += font_height + spacing + 4
        if y > CANVAS_HEIGHT - font_height:
            y = y_start
            x += 250

def update_preview(*args):
    try:
        raw_text = entry.get()
        labels = [label.strip() for label in raw_text.split(",") if label.strip()]
        font_dict = load_selected_font(selected_font.get())
        font_height = float(font_height_entry.get())
        spacing = float(spacing_entry.get())
        draw_all_labels(canvas, labels, font_dict, font_height, spacing)
    except Exception as e:
        print("Preview error:", e)

def open_settings_window():
    settings_win = Toplevel(root)
    settings_win.title("CNC Settings")

    def save_settings():
        try:
            cnc_settings["text_cut_depth"] = float(text_cut_depth.get())
            cnc_settings["label_cutout_depth"] = float(label_cutout_depth.get())
            cnc_settings["tool_diameter"] = float(tool_diameter.get())
            cnc_settings["safe_z"] = float(safe_z.get())
            cnc_settings["feed_rate"] = float(feed_rate.get())
            cnc_settings["tool_mode"] = tool_mode.get()
            settings_win.destroy()
        except ValueError:
            print("Invalid entry in settings.")

    Label(settings_win, text="Text Cut Depth (mm):").grid(row=0, column=0, sticky="e")
    text_cut_depth = Entry(settings_win)
    text_cut_depth.insert(0, str(cnc_settings["text_cut_depth"]))
    text_cut_depth.grid(row=0, column=1)

    Label(settings_win, text="Label Cutout Depth (mm):").grid(row=1, column=0, sticky="e")
    label_cutout_depth = Entry(settings_win)
    label_cutout_depth.insert(0, str(cnc_settings["label_cutout_depth"]))
    label_cutout_depth.grid(row=1, column=1)

    Label(settings_win, text="Tool Diameter (mm):").grid(row=2, column=0, sticky="e")
    tool_diameter = Entry(settings_win)
    tool_diameter.insert(0, str(cnc_settings["tool_diameter"]))
    tool_diameter.grid(row=2, column=1)

    Label(settings_win, text="Safe Z Height (mm):").grid(row=3, column=0, sticky="e")
    safe_z = Entry(settings_win)
    safe_z.insert(0, str(cnc_settings["safe_z"]))
    safe_z.grid(row=3, column=1)

    Label(settings_win, text="Feed Rate (mm/min):").grid(row=4, column=0, sticky="e")
    feed_rate = Entry(settings_win)
    feed_rate.insert(0, str(cnc_settings["feed_rate"]))
    feed_rate.grid(row=4, column=1)

    Label(settings_win, text="Tool Type:").grid(row=5, column=0, sticky="e")
    tool_mode = StringVar(value=cnc_settings["tool_mode"])
    OptionMenu(settings_win, tool_mode, "Spindle", "Laser").grid(row=5, column=1)

    Button(settings_win, text="Save", command=save_settings).grid(row=6, column=0, columnspan=2, pady=10)

def generate_gcode():
    try:
        raw_text = entry.get()
        labels = [label.strip() for label in raw_text.split(",") if label.strip()]
        font_dict = load_selected_font(selected_font.get())
        font_height = float(font_height_entry.get())
        spacing = float(spacing_entry.get())
        safe_z = cnc_settings["safe_z"]
        depth = cnc_settings["text_cut_depth"]
        feed = cnc_settings["feed_rate"]
        mode = cnc_settings["tool_mode"]

        gcode = []
        if mode == "Spindle":
            gcode.append("G21 ; mm mode")
            gcode.append("G90 ; absolute positioning")
            gcode.append(f"G0 Z{safe_z}")
            gcode.append("M3 S1000")
        elif mode == "Laser":
            gcode.append("G21")
            gcode.append("G90")
            gcode.append("M3")

        x = 0
        y = 0
        for label in labels:
            for char in label:
                strokes = get_scaled_char(char, font_dict, font_height)
                for segment in strokes:
                    if not segment: continue
                    x1, y1 = segment[0]
                    gcode.append(f"G0 X{round(x + x1,3)} Y{round(y + y1,3)} Z{safe_z}")
                    if mode == "Spindle":
                        gcode.append(f"G1 Z{-depth} F{feed}")
                    for x2, y2 in segment[1:]:
                        gcode.append(f"G1 X{round(x + x2,3)} Y{round(y + y2,3)} F{feed}")
                    gcode.append(f"G0 Z{safe_z}")
                x += font_height * 0.75
            x = 0
            y += font_height + spacing + 4

        gcode.append("M5")
        gcode.append("G0 Z{}".format(safe_z))
        gcode.append("G0 X0 Y0")
        gcode.append("M2")

        file_path = filedialog.asksaveasfilename(defaultextension=".gcode", filetypes=[("G-code files", "*.gcode")])
        if file_path:
            with open(file_path, "w") as f:
                f.write("\n".join(gcode))
            print("G-code saved.")
    except Exception as e:
        print("Error generating G-code:", e)

root = tk.Tk()
root.title("CNC Label Maker - Full Tool")

Label(root, text="Enter Labels (comma-separated):").grid(row=0, column=0, sticky="e")
entry = Entry(root, width=60)
entry.grid(row=0, column=1, columnspan=3, sticky="w")

Label(root, text="Select Font:").grid(row=1, column=0, sticky="e")
selected_font = StringVar()
fonts = list_available_fonts()
selected_font.set(fonts[0])
font_dropdown = OptionMenu(root, selected_font, *fonts)
font_dropdown.grid(row=1, column=1, sticky="w")

Button(root, text="Settings ⚙️", command=open_settings_window).grid(row=1, column=2)

Label(root, text="Font Height (mm):").grid(row=2, column=0, sticky="e")
font_height_entry = Entry(root, width=5)
font_height_entry.insert(0, "10")
font_height_entry.grid(row=2, column=1, sticky="w")

Label(root, text="Label Spacing (mm):").grid(row=2, column=2, sticky="e")
spacing_entry = Entry(root, width=5)
spacing_entry.insert(0, "10")
spacing_entry.grid(row=2, column=3, sticky="w")

canvas = Canvas(root, width=CANVAS_WIDTH, height=CANVAS_HEIGHT, bg="white")
canvas.grid(row=3, column=0, columnspan=4, pady=10)

Button(root, text="Generate G-code", command=generate_gcode).grid(row=4, column=0, columnspan=4, pady=10)

entry.bind("<KeyRelease>", update_preview)
font_height_entry.bind("<KeyRelease>", update_preview)
spacing_entry.bind("<KeyRelease>", update_preview)
selected_font.trace("w", update_preview)

update_preview()
root.mainloop()
