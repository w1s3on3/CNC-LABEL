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
- Type your labels (one per line) — the preview updates live
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
- Labels stack upward from the work origin (bottom-left of the material); the first label's cutout toolpath starts exactly at X0 Y0
- Text is centered in each label cutout
- **Label Size**: pick a preset (or type e.g. `60x20`) for fixed-size labels; labels whose text doesn't fit are shown in red. `Auto` sizes each label from its text
- Toggle Grid Snap for precision
- Mouse scroll to zoom at the cursor, drag (left or middle button) to pan — both display-only, the exported job never changes
- The preview fits the whole material sheet at Reset Zoom; the green cross marks work zero (X0 Y0)

A modernized version using **TrueType fonts** for accurate rendering, cutouts, and export.

### ✨ Features
- 🅰️ Uses system-installed TTF fonts (e.g., Arial, DIN)
- ✂️ G-code generation for text + label cutouts (multi-pass, with holding tabs)
- 📏 Font height calibrated in real millimetres (capital letter height)
- 🏷️ Fixed label sizes (50x15, 60x20, 75x25, 100x30 or custom WxH) or auto-size from text
- 🔧 Kerf compensation — toolpath offset by tool radius (spindle) or half kerf (laser), so finished labels match the drawn size
- 🔍 Zoom with mouse scroll
- 🔲 Grid snapping (toggle on/off)
- 🛰️ Toolpath view — simulates the actual exported G-code: rapids (grey dashes), engraving (red), cutout passes (blue, tab gaps visible) and cut order badges
- 🧭 Dry Run export — trace the job boundary at Safe Z with the spindle off, or at low Frame Power on a laser, to verify placement before cutting
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
| **X/Y Offset from Home** | Work-origin offset added to every exported coordinate, to shift the job away from machine home |
| **Feed Rate**          | Speed of cutting movement in mm/min (e.g., 300)                             |
| **Plunge Rate**        | Speed of Z plunges in mm/min (e.g., 100)                                    |
| **Spindle RPM**        | S value sent with M3 in Spindle mode                                        |
| **Laser Power**        | S value sent with M4 in Laser mode (GRBL dynamic power)                     |
| **Tool Mode**          | **Spindle** (M3, Z plunges) or **Laser** (M4 dynamic power, no Z motion)    |
| **Cutout Padding**     | Distance from text to label border in mm (min clearance for fixed sizes)    |
| **Laser Kerf**         | Beam kerf width in mm; cutout path is offset outward by half of it          |
| **Tab Width/Height**   | Holding tabs left on the cutout so labels don't come loose (0 = no tabs)    |
| **Material Width/Height** | Material size in mm (sets the preview sheet and overflow warnings)      |

These settings are automatically saved to `machine_settings.json` for your next session.

---

## 🔦 Spindle vs Laser Mode

**Spindle** (default) generates conventional milling G-code:

- `M3 S{Spindle RPM}` at the start, with a `G4` dwell so the spindle reaches speed before cutting
- Z plunges to the configured depths at the Plunge Rate, retracts to Safe Z between strokes
- Deep cuts are split into multiple passes (Depth per Pass), and the final cutout passes leave holding tabs so labels don't come loose
- The cutout toolpath is offset outward by half the Tool Diameter so the finished label matches the drawn size

**Laser** generates GRBL dynamic-power laser G-code — and **never moves Z**:

- No Z commands at all: focus the laser manually before starting the job, and it stays at that height
- `M4 S{Laser Power}` (dynamic mode): the beam only fires during `G1` cutting moves, so rapids between letters/labels don't leave burn marks
- The depth settings become pass counts: `Label Cutout Depth ÷ Depth per Pass` = number of times the cutout is traced (e.g. 1.6 / 0.4 = 4 passes); same for text
- The cutout is offset by half the Laser Kerf instead of the tool radius; holding tabs are skipped (they only make sense as uncut material thickness on a spindle)

---

## 📡 Send to Machine (GRBL over USB)

A stock CNC 3018 runs **GRBL 1.1 over USB serial** — the **📡 Machine** button talks to it directly (needs `pyserial`, included in requirements):

- Pick the COM port and baud (115200 is the GRBL default), then **Send**
- **Dry run only** is ticked by default — the first send traces the job boundary at Safe Z / Frame Power so you can check placement before cutting anything
- Streaming is call-and-response (each line waits for GRBL's `ok`), with live progress and an **Abort** button that feed-holds (`!`) and soft-resets (`Ctrl-X`) the controller
- **Home/zero the machine first** — the app sends the job as-is against your current work zero

### ⚙ GRBL Settings ($$)

The Machine dialog can also read and edit the controller's `$$` parameters (steps/mm, max rates, accelerations, travel limits, homing, laser mode, …):

- Reads the full `$$` dump and shows each `$n` with a description and editable value
- Only changed values are written (as `$n=value`), after a confirmation listing exactly what will be sent
- Status reports (`<Idle|WPos:...>`) and other chatter on the line are handled/ignored automatically

---

## 📦 Coming Soon

- [ ] Multiline text within one label
- [x] Dry run / frame mode (trace the job boundary at Safe Z or low power)
- [x] Toolpath preview (rapids, cut order, tabs)
- [ ] Grid/sheet nesting in the GUI (rows × columns across the stock)
- [ ] Rounded corners & mounting holes
- [ ] SVG export
- [ ] Barcode & QR code support
- [ ] .exe release for Windows users
- [ ] Let me know what else  

---

## 🤝 Contributions

This tool was built to solve a real-world gap in free CNC label software. Contributions, forks, or suggestions welcome!
