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
        layout = app.build_layout(["AB"], FONT, 8, 10, 2, 300, 200, label_size=(60, 20))
        item = layout[0]
        x0, y0, x1, y1 = item["cutout"]
        self.assertAlmostEqual(x1 - x0, 60)
        self.assertAlmostEqual(y1 - y0, 20)
        self.assertTrue(item["fits"])
        # text centered inside the label box, both axes
        self.assertAlmostEqual(item["x"] - x0, x1 - (item["x"] + item["width"]), places=6)
        self.assertAlmostEqual(item["y_top"] - y0, y1 - (item["y_top"] + item["height"]), places=6)

    def test_too_small_label_flagged(self):
        layout = app.build_layout(["MUCH TOO LONG"], FONT, 8, 10, 2, 300, 200, label_size=(20, 10))
        self.assertFalse(layout[0]["fits"])

    def test_auto_size_still_fits_text(self):
        layout = app.build_layout(["AB"], FONT, 8, 10, 2, 300, 200)
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
            s["material_height"], label_size=(60, 20),
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
            SETTINGS["material_height"],
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
            s["material_height"], label_size=(60, 20),
        )
        g = app.generate_gcode_lines(layout, s, fill_text=False)
        x0, _, x1, _ = layout[0]["cutout"]
        xs = [x for x, _ in xy_moves(g)]
        self.assertAlmostEqual(max(xs), x1 + 0.1, places=3)
        self.assertAlmostEqual(min(xs), x0 - 0.1, places=3)


class GcodeTests(unittest.TestCase):
    def layout(self, labels=("TEST",), font_height=10, margin=0.0):
        return app.build_layout(
            list(labels), FONT, font_height, 10,
            SETTINGS["cutout_padding"], SETTINGS["material_width"],
            SETTINGS["material_height"], margin=margin,
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
        # margin = kerf radius, matching how the GUI builds its layout
        g = app.generate_gcode_lines(
            self.layout(margin=SETTINGS["tool_diameter"] / 2), SETTINGS, fill_text=True
        )
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

    def test_job_starts_at_work_origin(self):
        # Layout margin = kerf radius, so the cutout toolpath's lowest-left
        # point lands exactly on X0 Y0
        r = SETTINGS["tool_diameter"] / 2
        g = app.generate_gcode_lines(self.layout(margin=r), SETTINGS, fill_text=False)
        moves = xy_moves(g)
        self.assertAlmostEqual(min(x for x, _ in moves), 0.0, places=3)
        self.assertAlmostEqual(min(y for _, y in moves), 0.0, places=3)

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


class DryRunTests(unittest.TestCase):
    def _layout(self):
        return app.build_layout(
            ["AB", "CD"], FONT, 8, 10, SETTINGS["cutout_padding"],
            SETTINGS["material_width"], SETTINGS["material_height"],
            margin=SETTINGS["tool_diameter"] / 2,
        )

    def test_spindle_dry_run_safe_z_spindle_off(self):
        g = app.generate_dry_run_lines(self._layout(), SETTINGS)
        text = "\n".join(g)
        self.assertNotIn("M3", text)
        self.assertNotIn("M4", text)
        self.assertEqual(z_values(g), [SETTINGS["safe_z"]], "only move Z to safe height")

    def test_laser_dry_run_no_power_no_z(self):
        s = dict(SETTINGS, tool_mode="Laser")
        g = app.generate_dry_run_lines(self._layout(), s)
        text = "\n".join(g)
        self.assertNotIn("M3", text, "dry run must never power the tool")
        self.assertNotIn("M4", text, "dry run must never power the tool")
        self.assertIn("M5", text)
        self.assertEqual(z_values(g), [])

    def test_dry_run_bounds_match_job_bounds(self):
        layout = self._layout()
        job = xy_moves(app.generate_gcode_lines(layout, SETTINGS, fill_text=False))
        dry = xy_moves(app.generate_dry_run_lines(layout, SETTINGS))
        for axis in (0, 1):
            self.assertAlmostEqual(min(m[axis] for m in job), min(m[axis] for m in dry), places=3)
            self.assertAlmostEqual(max(m[axis] for m in job), max(m[axis] for m in dry), places=3)


class SimulateTests(unittest.TestCase):
    def setUp(self):
        self.layout = app.build_layout(
            ["AB"], FONT, 8, 10, SETTINGS["cutout_padding"],
            SETTINGS["material_width"], SETTINGS["material_height"],
            margin=SETTINGS["tool_diameter"] / 2,
        )
        self.gcode = app.generate_gcode_lines(self.layout, SETTINGS, fill_text=False)
        self.segs = app.simulate_gcode(self.gcode)

    def test_all_kinds_present(self):
        kinds = {s[4] for s in self.segs}
        self.assertEqual(kinds, {"rapid", "engrave", "cutout"})

    def test_final_cutout_pass_shows_tab_gaps(self):
        def length(kind_segs):
            return sum(math.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1, _, _ in
                       ((s[0], s[1], s[2], s[3], s[4], s[5]) for s in kind_segs))

        cut = [s for s in self.segs if s[4] == "cutout"]
        final_z = min(s[5] for s in cut)
        first_z = max(s[5] for s in cut)
        full = length([s for s in cut if s[5] == first_z])
        final = length([s for s in cut if s[5] == final_z])
        # final pass perimeter is shorter by one tab gap per side
        self.assertAlmostEqual(full - final, 4 * SETTINGS["tab_width"], places=2)

    def test_engrave_moves_at_text_depth(self):
        engrave_zs = {s[5] for s in self.segs if s[4] == "engrave"}
        self.assertEqual(engrave_zs, {-SETTINGS["text_cut_depth"]})


class MachineLinkTests(unittest.TestCase):
    # Excerpt of a real $$ dump + status chatter from a CNC 3018 console log
    GRBL_DUMP = """\
$0=10
$1=5
$21=1
$30=1000.000
$32=1
$100=3200.000
$110=1000.000
$120=50.000
$130=298.000
$131=170.000
$132=80.000
<Idle|WPos:2.000,168.000,0.000|FS:0,0|PS:100|PF:100>
<Idle|WPos:2.000,168.000,0.000|FS:0,0|WCO:0.000,-170.000,0.000|PS:100|PF:100>
$J=G91 G21 F1500 Y-50
ok""".splitlines()

    def test_parse_grbl_settings(self):
        settings = app.parse_grbl_settings(self.GRBL_DUMP)
        self.assertEqual(settings[130], "298.000")
        self.assertEqual(settings[0], "10")
        self.assertEqual(len(settings), 11, "status/jog/ok lines must be ignored")

    def test_sendable_lines_strips_comments(self):
        lines = [
            "G21 ; units: mm",
            "(Label: PUMP 1)",
            "",
            "G1 X5.000 Y0.000 F300",
            "M2 ; end program",
        ]
        self.assertEqual(
            app.sendable_lines(lines), ["G21", "G1 X5.000 Y0.000 F300", "M2"]
        )

    def test_await_ok_ignores_status_chatter(self):
        class FakeSerial:
            def __init__(self, responses):
                self.responses = list(responses)

            def readline(self):
                return (self.responses.pop(0) + "\n").encode() if self.responses else b""

        self.assertIsNone(app.await_ok(FakeSerial([
            "<Idle|WPos:2.000,168.000,0.000|FS:0,0|PS:100|PF:100>",
            "[MSG:...]",
            "ok",
        ])))
        self.assertEqual(app.await_ok(FakeSerial(["error:3"])), "error:3")
        with self.assertRaises(TimeoutError):
            app.await_ok(FakeSerial([]), timeout_s=0.2)
        # Quiet reads while buffered motion executes (e.g. waiting on M5's
        # planner sync) must be tolerated, not treated as a dead link
        self.assertIsNone(app.await_ok(FakeSerial(["", "", "", "ok"]), timeout_s=2))

    def test_link_kind_classification(self):
        self.assertEqual(app.link_kind("COM3"), "serial")
        self.assertEqual(app.link_kind("/dev/ttyUSB0"), "serial")
        self.assertEqual(app.link_kind("192.168.1.207"), "esp3d")
        self.assertEqual(app.link_kind("http://192.168.1.207"), "esp3d")
        self.assertEqual(app.link_kind("ws://192.168.1.207:81"), "ws")

    def test_home_machine_waits_through_slow_cycle(self):
        class FakeSerial:
            def __init__(self, responses):
                self.responses = list(responses)
                self.written = []

            def write(self, data):
                self.written.append(data)

            def readline(self):
                return (self.responses.pop(0) + "\n").encode() if self.responses else b""

        ok_ser = FakeSerial(["", "", "<Home|MPos:0,0,0>", "ok"])
        self.assertIsNone(app.home_machine(ok_ser, timeout_s=2))
        self.assertEqual(ok_ser.written, [b"$H\n"])

        alarm = FakeSerial(["ALARM:8"])
        self.assertEqual(app.home_machine(alarm, timeout_s=2), "ALARM:8")

        with self.assertRaises(TimeoutError):
            app.home_machine(FakeSerial([]), timeout_s=0.2)

    def test_normalize_target_forgives_missing_slashes(self):
        self.assertEqual(
            app.normalize_target("ws:192.168.1.207:81"), "ws://192.168.1.207:81"
        )
        self.assertEqual(
            app.normalize_target("ws:/192.168.1.207:81"), "ws://192.168.1.207:81"
        )
        self.assertEqual(
            app.normalize_target(" WS://192.168.1.207:81 "), "ws://192.168.1.207:81"
        )
        self.assertEqual(app.normalize_target("COM5"), "COM5")
        self.assertEqual(app.normalize_target("192.168.1.207"), "192.168.1.207")

    def test_esp3d_write_sends_http_commands(self):
        link = object.__new__(app.ESP3DLink)
        link.host = "192.168.1.207"
        link.timeout = 5
        urls = []

        class FakeResponse:
            def read(self):
                return b""

        original = app.urllib.request.urlopen
        app.urllib.request.urlopen = lambda url, timeout: urls.append(url) or FakeResponse()
        try:
            link.write(b"$$\n")
            link.write("G1 X5 Y0 F300\n")
            link.write(b"\r\n\r\n")  # wake noise: no commands, no requests
        finally:
            app.urllib.request.urlopen = original
        self.assertEqual(urls, [
            "http://192.168.1.207/command?plain=%24%24",
            "http://192.168.1.207/command?plain=G1%20X5%20Y0%20F300",
        ])

    def test_websocket_readline_reassembles_frames(self):
        link = object.__new__(app.WebSocketLink)
        link.buffer = b""
        link.timeout = 5

        class FakeWS:
            def __init__(self, frames):
                self.frames = list(frames)

            def recv(self):
                if not self.frames:
                    raise TimeoutError()
                return self.frames.pop(0)

        # One frame carrying many lines, then a partial line completed later
        link.ws = FakeWS(["$0=10\r\n$1=5\r\nok\r\n", "<Idle|WPos", ":0,0,0>\r\n"])
        lines = [link.readline().decode().strip() for _ in range(4)]
        self.assertEqual(lines, ["$0=10", "$1=5", "ok", "<Idle|WPos:0,0,0>"])
        self.assertEqual(link.readline(), b"", "timeout must read as empty like serial")

    def test_websocket_drops_esp3d_control_frames(self):
        # Seen on the live machine: a newline-less PING frame arriving right
        # before 'ok' must not corrupt it into 'PING:0ok'
        link = object.__new__(app.WebSocketLink)
        link.buffer = b""
        link.timeout = 5

        class FakeWS:
            def __init__(self, frames):
                self.frames = list(frames)

            def recv(self):
                if not self.frames:
                    raise TimeoutError()
                return self.frames.pop(0)

        link.ws = FakeWS(["PING:0", "ok\r\n", "CURRENT_ID:2", "ACTIVE_ID:1", "error:15\r\n"])
        self.assertEqual(link.readline().decode().strip(), "ok")
        self.assertEqual(link.readline().decode().strip(), "error:15")


if __name__ == "__main__":
    unittest.main()
