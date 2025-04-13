
# 🪪 CNC Label Maker

The **CNC Label Maker** is a free, open-source tool that generates G-code for traffolyte-style labels using a custom stroke font. It supports both **console** and **GUI** versions, with live preview, customizable machine settings, and flexible grid layouts.

---

## 📁 Project Structure

```
CNC-Label-Maker/
├── console/                # Console-based G-code generator
│   └── create.py
├── GUI/                    # GUI version with live preview and settings
│   └── cnc_label_maker_gui.py
├── font dict/              # Stroke font file (JSON)
│   └── normalized_full_font.json
└── machine_settings.json   # Auto-generated after running GUI
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
- No dependencies required (uses only built-in modules)

---

## 🚀 How to Use

### 🔧 Console Version:
```bash
cd console
python create.py
```
Follow the prompts to enter labels and generate individual `.gcode` files.

### 🖱 GUI Version:
```bash
cd GUI
python cnc_label_maker_gui.py
```
- Type your labels (one per line)
- Click **Preview** to see layout
- Click **Settings** ⚙️ to configure machine-specific depths and speeds
- Export G-code when ready

---

## ✍️ Customization

**Font**:  
Edit or expand `font dict/normalized_full_font.json` to add new characters or styles.

**Settings**:  
The GUI saves user preferences to `machine_settings.json`. You can edit this file directly or reset by deleting it.

---

## 📦 Coming Soon

- [ ] SVG export
- [ ] Barcode & QR code support
- [ ] Font switching
- [ ] .exe release for Windows users
- [ ] Let me know what else  

---

## 🤝 Contributions

This tool was built to solve a real-world gap in free CNC label software. Contributions, forks, or suggestions welcome!
