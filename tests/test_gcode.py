# Golden/behaviour tests for the G-code generation core.
# Run with:  python -m unittest discover tests   (from the repo root)

import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "GUI"))

from matplotlib.font_manager import findSystemFonts
import create_gui as app

FONT = sorted(findSystemFonts(fontext="ttf"))[0]

SETTINGS = dict(app.DEFAULT_SETTINGS)
SETTINGS.update({"material_width": 300, "material_height": 200})


def xy_moves(lines):
    moves = []
    for line in lines:
        m = re.match(r"G[01] X(-?\d+\.?\d*) Y(-?\d+\.?\d*)", line)
        if m:
            moves.append((float(m.group(1)), float(m.group(2))))
    return moves


def z_values(lines):
    vals = []
    for line in lines:
        m = re.search(r"Z(-?\d+\.?\d*)", line)
        if m:
            vals.append(float(m.group(1)))
    return vals


class TextGeometryTests(unittest.TestCase):
    def test_counters_become_holes(self):
        geom = app.text_geometry("O", FONT, 10)
        holes = sum(len(p.interiors) for p in app.geom_polygons(geom))
        self.assertGreaterEqual(holes, 1, "the counter of 'O' must be a hole")

    def test_cap_height_scaling(self):
        geom = app.text_geometry("X", FONT, 10)
        _, _, _, maxy = geom.bounds
        self.assertAlmostEqual(maxy, 10.0, delta=0.1)

    def test_hatch_skips_holes(self):
        geom = app.text_geometry("O", FONT, 10)
        _, miny, _, maxy = geom.bounds
        mid = (miny + maxy) / 2
        lines = app.hatch_fill(geom, 0.24)
        near_mid = [l for l in lines if abs(l[0][1] - mid) < 0.5]
        # At mid-height an 'O' is two strokes: left wall and right wall
        rows = {}
        for (x0, y0), (x1, y1) in near_mid:
            rows.setdefault(round(y0, 3), []).append((x0, x1))
        self.assertTrue(
            any(len(segs) >= 2 for segs in rows.values()),
            "hatch at the middle of 'O' should split around the counter",
        )


class LabelSizeTests(unittest.TestCase):
    def test_fixed_size_cutout_and_centering(self):
        layout = app.build_layout(["AB"], FONT, 8, 10, 2, 300, label_size=(60, 20))
        item = layout[0]
        x0, y0, x1, y1 = item["cutout"]
        self.assertAlmostEqual(x1 - x0, 60)
        self.assertAlmostEqual(y1 - y0, 20)
        self.assertTrue(item["fits"])
        # text centered inside the label box, both axes
        self.assertAlmostEqual(item["x"] - x0, x1 - (item["x"] + item["width"]), places=6)
        self.assertAlmostEqual(item["y_top"] - y0, y1 - (item["y_top"] + item["height"]), places=6)

    def test_too_small_label_flagged(self):
        layout = app.build_layout(["MUCH TOO LONG"], FONT, 8, 10, 2, 300, label_size=(20, 10))
        self.assertFalse(layout[0]["fits"])

    def test_auto_size_still_fits_text(self):
        layout = app.build_layout(["AB"], FONT, 8, 10, 2, 300)
        item = layout[0]
        x0, y0, x1, y1 = item["cutout"]
        self.assertAlmostEqual(x1 - x0, item["width"] + 4)
        self.assertAlmostEqual(y1 - y0, item["height"] + 4)
        self.assertTrue(item["fits"])


class KerfTests(unittest.TestCase):
    def test_spindle_toolpath_offset_by_tool_radius(self):
        s = dict(SETTINGS, tab_width=0.0, tab_height=0.0)
        layout = app.build_layout(
            ["AB"], FONT, 8, 10, s["cutout_padding"], s["material_width"],
            label_size=(60, 20),
        )
        g = app.generate_gcode_lines(layout, s, fill_text=False)
        x0, _, x1, _ = layout[0]["cutout"]
        r = s["tool_diameter"] / 2
        xs = [x for x, _ in xy_moves(g)]
        self.assertAlmostEqual(max(xs), x1 + r, places=3)
        self.assertAlmostEqual(min(xs), x0 - r, places=3)

    def test_work_origin_offset_shifts_all_moves(self):
        layout = app.build_layout(
            ["AB"], FONT, 8, 10, SETTINGS["cutout_padding"], SETTINGS["material_width"],
        )
        base = xy_moves(app.generate_gcode_lines(layout, SETTINGS, fill_text=False))
        s = dict(SETTINGS, offset_x=25.0, offset_y=-10.0)
        shifted = xy_moves(app.generate_gcode_lines(layout, s, fill_text=False))
        self.assertEqual(len(base), len(shifted))
        for (bx, by), (sx_, sy_) in zip(base, shifted):
            self.assertAlmostEqual(sx_ - bx, 25.0, places=3)
            self.assertAlmostEqual(sy_ - by, -10.0, places=3)

    def test_laser_toolpath_offset_by_half_kerf(self):
        s = dict(SETTINGS, tool_mode="Laser", laser_kerf=0.2)
        layout = app.build_layout(
            ["AB"], FONT, 8, 10, s["cutout_padding"], s["material_width"],
            label_size=(60, 20),
        )
        g = app.generate_gcode_lines(layout, s, fill_text=False)
        x0, _, x1, _ = layout[0]["cutout"]
        xs = [x for x, _ in xy_moves(g)]
        self.assertAlmostEqual(max(xs), x1 + 0.1, places=3)
        self.assertAlmostEqual(min(xs), x0 - 0.1, places=3)


class GcodeTests(unittest.TestCase):
    def layout(self, labels=("TEST",), font_height=10):
        return app.build_layout(
            list(labels), FONT, font_height, 10,
            SETTINGS["cutout_padding"], SETTINGS["material_width"],
        )

    def test_spindle_on_and_off(self):
        g = app.generate_gcode_lines(self.layout(), SETTINGS, fill_text=True)
        text = "\n".join(g)
        self.assertIn("M3", text)
        self.assertIn("M5", text)
        self.assertLess(text.index("M3"), text.index("G1"), "spindle must start before cutting")

    def test_cutout_is_multipass_and_lands_on_depth(self):
        g = app.generate_gcode_lines(self.layout(), SETTINGS, fill_text=False)
        depths = sorted({z for z in z_values(g) if z < 0})
        self.assertEqual(min(depths), -SETTINGS["label_cutout_depth"])
        n_expected = math.ceil(SETTINGS["label_cutout_depth"] / SETTINGS["pass_depth"])
        cutout_depths = [z for z in depths if z < -SETTINGS["text_cut_depth"]]
        self.assertEqual(len(cutout_depths), n_expected)

    def test_uneven_pass_depth_clamps_final(self):
        s = dict(SETTINGS, label_cutout_depth=0.9, pass_depth=0.2)
        g = app.generate_gcode_lines(self.layout(), s, fill_text=False)
        self.assertEqual(min(z_values(g)), -0.9)

    def test_moves_inside_material(self):
        g = app.generate_gcode_lines(self.layout(), SETTINGS, fill_text=True)
        for x, y in xy_moves(g):
            self.assertGreaterEqual(x, -0.01)
            self.assertLessEqual(x, SETTINGS["material_width"] + 0.01)
            self.assertGreaterEqual(y, -0.01)
            self.assertLessEqual(y, SETTINGS["material_height"] + 0.01)

    def test_not_mirrored(self):
        # In "L" the vertical stem is on the left: engraving X for the glyph
        # body must start left of the label centre, and the bottom bar extends
        # right. A mirrored/rotated output puts the stem on the right.
        layout = self.layout(labels=("L",))
        item = layout[0]
        geom = item["geom"]
        _, miny, maxx, maxy = geom.bounds
        top = geom.intersection(app.LineString([(-1, maxy - 0.2), (maxx + 1, maxy - 0.2)]))
        bottom = geom.intersection(app.LineString([(-1, miny + 0.2), (maxx + 1, miny + 0.2)]))
        self.assertLess(top.length, bottom.length, "L: top row must be narrower than bottom bar")

    def test_machine_y_flip_consistent(self):
        # First label sits near the top of the material -> high machine Y
        g = app.generate_gcode_lines(self.layout(), SETTINGS, fill_text=False)
        ys = [y for _, y in xy_moves(g)]
        self.assertGreater(
            min(ys), SETTINGS["material_height"] / 4,
            "a single top-placed label must map to the upper part of machine Y space",
        )

    def test_laser_mode_has_no_z_moves(self):
        s = dict(SETTINGS, tool_mode="Laser")
        g = app.generate_gcode_lines(self.layout(), s, fill_text=True)
        text = "\n".join(g)
        self.assertIn("M4", text)
        self.assertNotIn("M3 ", text)
        self.assertEqual([z for z in z_values(g)], [], "laser mode must not move Z")

    def test_tabs_leave_gaps_on_final_pass(self):
        g = app.generate_gcode_lines(self.layout(), SETTINGS, fill_text=False)
        # Final cutout pass with tabs: perimeter is 8 segments -> 8 plunges to
        # full depth instead of 1
        full_depth_plunges = [
            l for l in g if l.startswith("G1 Z-") and f"Z-{SETTINGS['label_cutout_depth']:.3f}" in l
        ]
        self.assertEqual(len(full_depth_plunges), 8)

    def test_no_tabs_when_disabled(self):
        s = dict(SETTINGS, tab_width=0.0, tab_height=0.0)
        g = app.generate_gcode_lines(self.layout(), s, fill_text=False)
        full_depth_plunges = [
            l for l in g if l.startswith("G1 Z-") and f"Z-{s['label_cutout_depth']:.3f}" in l
        ]
        self.assertEqual(len(full_depth_plunges), 1)


if __name__ == "__main__":
    unittest.main()
