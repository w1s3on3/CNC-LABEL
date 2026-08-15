# 🪪 CNC Label Maker

The **CNC Label Maker** is a free, open-source tool that generates G-code for traffolyte-style labels using a custom stroke font. It supports both **console** and **GUI** versions, with live preview, customisable machine settings, and flexible grid layouts.

---

## 📁 Project Structure

```
CNC-Label-Maker/
├── Console/                # Console-based G-code generator (stroke font)
│   └── create.py
├── GUI/                    # GUI version with live preview and settings
│   ├── create_gui.py
│   └── machine_settings.json   # Auto-generated after running GUI
├── fonts/                  # Stroke font files (JSON) (CONSOLE VERSION)
│   └── normalized_full_font.json
├── tests/                  # G-code generation tests
│   └── test_gcode.py
└── requirements.txt
```

---

## ✅ Features

- ✔ Console & GUI support
- ✔ Case-sensitive stroke font (uppercase, lowercase, numbers, symbols)
- ✔ Live preview canvas in GUI
- ✔ Cut path visualization toggle
- ✔ Grid layout generation for batching labels
- ✔ Machine config popup with persistent settings
- ✔ G-code output ready for Candle, UGS, etc.

---

## 🖥️ Requirements

- Python 3.8+

```bash
pip install -r requirements.txt
```

---

## 🚀 How to Use

### 🔧 Console Version:
```bash
cd Console
python create.py
```
Follow the prompts to enter labels and generate individual `.gcode` files.

### 🖱 GUI Version:
```bash
cd GUI
python create_gui.py
```
- Type your labels (one per line)
- Click **Preview** to see layout
- Click **Settings** ⚙️ to configure machine-specific depths and speeds
- Export G-code when ready

---

## ✍️ Customization

**Font**:  
Edit or expand `font/normalized_full_font.json` to add new characters or styles.

**Settings**:  
The GUI saves user preferences to `GUI/machine_settings.json`. You can edit this file directly or reset by deleting it.

**Tests**:  
```bash
python -m unittest discover tests
```

---

## 🆕 GUI Version

### ✅ Usage Notes
- Use one label per line (no commas needed)
- Multi-word labels supported
- Text is centered in each label cutout
- **Label Size**: pick a preset (or type e.g. `60x20`) for fixed-size labels; labels whose text doesn't fit are shown in red. `Auto` sizes each label from its text
- Toggle Grid Snap for precision
- Mouse scroll to zoom, Reset button to restore

A modernized version using **TrueType fonts** for accurate rendering, cutouts, and export.

### ✨ Features
- 🅰️ Uses system-installed TTF fonts (e.g., Arial, DIN)
- ✂️ G-code generation for text + label cutouts (multi-pass, with holding tabs)
- 📏 Font height calibrated in real millimetres (capital letter height)
- 🏷️ Fixed label sizes (50x15, 60x20, 75x25, 100x30 or custom WxH) or auto-size from text
- 🔧 Kerf compensation — toolpath offset by tool radius (spindle) or half kerf (laser), so finished labels match the drawn size
- 🔍 Zoom with mouse scroll
- 🔲 Grid snapping (toggle on/off)
- ⚙️ Settings panel for depths, feeds, tool mode (Spindle or Laser)

### ▶️ Run It
```bash
python create_gui.py
```

No font conversion required — just pick any installed font and go.

---

## ⚙️ Settings Explained

When you click the **Settings** button in the GUI, you can configure and save your preferred cutting parameters:

| Setting                | Description                                                                 |
|------------------------|-----------------------------------------------------------------------------|
| **Text Cut Depth**     | How deep the engraving for the text should go (e.g., 0.2mm)                 |
| **Label Cutout Depth** | How deep to cut the full label shape around the text (e.g., 1.6mm)         |
| **Depth per Pass**     | Maximum depth removed per pass; deeper cuts are split into multiple passes  |
| **Tool Diameter**      | Diameter of your engraving tool (sets hatch-fill line spacing)              |
| **Safe Z Height**      | The safe height (Z-axis) to lift to before rapid movement (e.g., 5.0mm)     |
| **Feed Rate**          | Speed of cutting movement in mm/min (e.g., 300)                             |
| **Plunge Rate**        | Speed of Z plunges in mm/min (e.g., 100)                                    |
| **Spindle RPM**        | S value sent with M3 in Spindle mode                                        |
| **Laser Power**        | S value sent with M4 in Laser mode (GRBL dynamic power)                     |
| **Tool Mode**          | **Spindle** (M3, Z plunges) or **Laser** (M4 dynamic power, no Z motion)    |
| **Cutout Padding**     | Distance from text to label border in mm (min clearance for fixed sizes)    |
| **Laser Kerf**         | Beam kerf width in mm; cutout path is offset outward by half of it          |
| **Tab Width/Height**   | Holding tabs left on the cutout so labels don't come loose (0 = no tabs)    |
| **Material Width/Height** | Material size in mm (used for centering, preview and overflow warning)  |

These settings are automatically saved to `machine_settings.json` for your next session.

---

## 📦 Coming Soon

- [ ] Multiline Support
- [ ] Style Support (Fix infil)
- [ ] SVG export
- [ ] Barcode & QR code support
- [ ] Font switching
- [ ] .exe release for Windows users
- [ ] Let me know what else  

---

## 🤝 Contributions

This tool was built to solve a real-world gap in free CNC label software. Contributions, forks, or suggestions welcome!
