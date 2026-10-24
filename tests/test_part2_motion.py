"""Part 2: frozen flash echoes, real art bounds and inert ornament animation."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea
from pet_window import PetWindow

APP = QApplication.instance() or QApplication(["part2-motion"])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part2-motion-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def advance(engine, duration):
    for _ in range(round(duration * 240)):
        engine.advance(1 / 240)


def gif_bytes():
    data = b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    data += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for value in (b"\x44\x01\x00", b"\x4c\x01\x00"):
        data += b"\x21\xf9\x04\x00\x08\x00\x00\x00"
        data += b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02" + value
    return data + b"\x3b"


def paint(renderer, engine, foot=QPointF(420, 450)):
    image = QImage(1000, 700, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.paint(painter, engine, foot)
    painter.end()
    return image


class ReverseFlashTests(unittest.TestCase):
    def setUp(self):
        self.e = PetEngine(WorkArea(0, 0, 1800, 1100))

    def test_free_flash_runs_reverse_then_returns_without_physical_movement(self):
        events = []; self.e.presentation.changed.connect(events.append)
        original = (self.e.x, self.e.y, self.e.landing_count)
        self.assertTrue(self.e.perform_trick("reverse_flash", flash_distance=48))
        self.assertEqual(self.e.visual_offset, QPointF())
        advance(self.e, .4); self.assertAlmostEqual(self.e.visual_offset.x(), 0, places=6)
        advance(self.e, .25); self.assertAlmostEqual(self.e.visual_offset.x(), -48, places=6)
        self.assertEqual(self.e.visual_offset.y(), 0)
        advance(self.e, .75); self.assertAlmostEqual(self.e.visual_offset.x(), -48, places=6)
        advance(self.e, .6); self.assertAlmostEqual(self.e.visual_offset.x(), -24, places=6)
        advance(self.e, .61)
        self.assertEqual(self.e.active_trick, "")
        self.assertEqual(self.e.visual_offset, QPointF())
        self.assertEqual(self.e._flash_distance, 0)
        self.assertEqual((self.e.x, self.e.y, self.e.landing_count), original)
        self.assertEqual([row["phase"] for row in events], ["accepted", "finished"])

    def test_pinned_body_is_fixed_but_a_room_can_request_its_own_displacement(self):
        self.e.set_pinned(True); original = self.e.x, self.e.y
        self.assertTrue(self.e.perform_trick("reverse_flash", flash_distance=60))
        advance(self.e, .9)
        self.assertEqual(self.e.visual_offset, QPointF())
        self.assertEqual(self.e.reverse_flash_offset(25, pinned=False), QPointF(-25, 0))
        self.assertEqual((self.e.x, self.e.y), original)
        self.e.cancel_trick("hidden")
        self.assertEqual(self.e.reverse_flash_offset(25, pinned=False), QPointF())

    def test_invalid_distance_and_held_request_leave_existing_performance(self):
        self.assertTrue(self.e.perform_trick("clone")); active = dict(self.e.presentation.active)
        for distance in (-1, 61, float("nan"), float("inf"), True, "20"):
            self.assertFalse(self.e.can_start_trick("reverse_flash", replacing=True, flash_distance=distance))
        self.e.held = True
        self.assertFalse(self.e.can_start_trick("reverse_flash", replacing=True))
        self.assertEqual(self.e.presentation.active, active)
        self.assertEqual(self.e.active_trick, "clone")

    def test_drag_and_reset_clear_flash_and_do_not_restore_an_old_position(self):
        self.e.perform_trick("reverse_flash"); advance(self.e, .8)
        self.e.begin_drag(); self.assertEqual(self.e.active_trick, "")
        self.assertEqual(self.e._flash_distance, 0)
        self.e.drag_to(500, 460, 1000); self.e.release_drag(0, 0)
        self.e.set_pinned(True); self.e.place(500, 460)
        advance(self.e, 4)
        self.assertEqual((self.e.x, self.e.y), (500, 460))
        self.e.perform_trick("reverse_flash"); self.e.reset()
        self.assertEqual(self.e.active_trick, ""); self.assertEqual(self.e._flash_distance, 0)


class FlashRenderingTests(unittest.TestCase):
    def setUp(self):
        self.e = PetEngine(WorkArea(0, 0, 1800, 1100))
        self.renderers = []; self.windows = []

    def renderer(self, path=None):
        item = SkinRenderer(path or ROOT / "assets/skins/default")
        self.renderers.append(item); return item

    def tearDown(self):
        for window in self.windows:
            window.stop(); window.deleteLater()
        for renderer in self.renderers:
            renderer.stop(); renderer.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_max_skin_buff_and_wings_shortens_dash_at_left_edge(self):
        renderer = self.renderer(); self.e.skin_scale = 1.5
        self.e.set_buff({"scale": 1.2, "remaining_seconds": 60})
        renderer.set_accessories({"head": "crown", "face": "seven_goggles", "back": "phoenix_wings", "offset_y": -30})
        extent = renderer._flash_neutral_bounds(self.e)
        self.e.x = -extent.left() + 17
        distance = renderer.desktop_flash_distance(self.e)
        self.assertAlmostEqual(distance, 12)
        anchor = self.e.x, self.e.y
        self.assertTrue(self.e.perform_trick("reverse_flash", flash_distance=distance))
        bounds = renderer.scene_bounds(self.e, QPointF(self.e.x, self.e.y))
        self.assertGreaterEqual(bounds.left(), self.e.area.left)
        for age in (.1, .5, 1., 1.7, 2.5):
            self.e.elapsed = self.e._trick_started + age
            self.assertEqual(renderer.scene_bounds(self.e, QPointF(self.e.x, self.e.y)), bounds)
            painted = renderer.body_transform(self.e, QPointF(self.e.x, self.e.y)).mapRect(
                renderer.visible_rect(self.e.state).united(renderer.accessory_bounds(self.e.state)))
            self.assertTrue(bounds.contains(painted), str(painted))
            self.assertGreaterEqual(painted.left(), self.e.area.left)
            self.assertEqual((self.e.x, self.e.y), anchor)

    def test_pinned_native_window_geometry_and_foot_are_stable_during_dash(self):
        window = PetWindow(ROOT / "assets/skins/default"); self.windows.append(window)
        window.timer.stop(); window.engine.set_pinned(True); window.engine.place(600, 570)
        window.set_accessories({"face": "seven_goggles", "back": "kiting_scarf"})
        self.assertTrue(window.perform_trick("reverse_flash"))
        window._sync_window(); geometry = window.geometry(); anchor = window.capture_position()
        for age in (.1, .45, .8, 1.5, 2.4):
            window.engine.elapsed = window.engine._trick_started + age; window._sync_window()
            self.assertEqual(window.geometry(), geometry)
            self.assertEqual(window.capture_position(), anchor)
            self.assertEqual(window.engine.visual_offset, QPointF())
        window.cancel_presentation("hidden"); self.assertEqual(window.capture_position(), anchor)

    def test_png_and_gif_share_transform_and_echo_capture_is_frozen(self):
        work = ART / self._testMethodName; work.mkdir()
        (work / "idle.gif").write_bytes(gif_bytes())
        (work / "manifest.json").write_text(json.dumps({"name": "local test", "states": {"idle": "idle.gif"}}), encoding="utf-8")
        renderer = self.renderer(work); renderer.set_accessories({"face": "seven_goggles", "back": "kiting_scarf"})
        self.e.set_pinned(True); self.e.set_buff({"scale": 1.2, "color": "#efb3ca", "remaining_seconds": 60})
        self.assertTrue(self.e.perform_trick("reverse_flash")); advance(self.e, .5)
        first = paint(renderer, self.e); entry = renderer._flash_snapshots["PetEngine"]
        key = entry[1].cacheKey(); frozen = hashlib.sha256(bytes(entry[1].toImage().bits())).hexdigest()
        movie = next(iter(renderer.movies.values())); movie.jumpToFrame(1)
        renderer._movie_frame(movie); advance(self.e, .4); second = paint(renderer, self.e)
        self.assertEqual(renderer._flash_snapshots["PetEngine"][1].cacheKey(), key)
        self.assertEqual(hashlib.sha256(bytes(renderer._flash_snapshots["PetEngine"][1].toImage().bits())).hexdigest(), frozen)
        self.assertNotEqual(bytes(first.bits()), bytes(second.bits()))
        self.e.cancel_trick("skin_changed"); paint(renderer, self.e)
        self.assertEqual(renderer._flash_snapshots, {})
        self.assertEqual(renderer.accessories["face"], "seven_goggles")
        self.assertEqual(renderer.accessories["back"], "kiting_scarf")
        self.assertTrue(first.save(str(work / "gif-flash.png")))

    def test_new_ornaments_change_pixels_without_moving_the_body(self):
        renderer = self.renderer(); self.e.set_pinned(True); self.e.place(900, 700)
        anchor = self.e.x, self.e.y
        plain = paint(renderer, self.e)
        renderer.set_accessories({"face": "seven_goggles", "back": "kiting_scarf"})
        wearing = paint(renderer, self.e)
        self.assertNotEqual(bytes(plain.bits()), bytes(wearing.bits()))
        body = renderer.body_transform(self.e, QPointF(420, 450)).map(QPointF())
        self.e.begin_drag(); self.e.drag_to(self.e.x, self.e.y, 1500); advance(self.e, .15)
        self.assertLess(self.e.scarf_lag, -1)
        lagged = self.e.scarf_lag; self.e.release_drag(0, 0); advance(self.e, 1)
        self.assertLess(abs(self.e.scarf_lag), abs(lagged) * .02)
        self.assertEqual((self.e.x, self.e.y), anchor)
        self.e.angle = 0; self.e.spring = 0
        self.assertEqual(renderer.body_transform(self.e, QPointF(420, 450)).map(QPointF()), body)

    def test_goggle_pokes_merge_a_single_deadline_and_cleanup_after_fade(self):
        self.e.set_pinned(True)
        for _ in range(20):
            self.e.click(); advance(self.e, .01)
        self.assertGreater(self.e.goggles_flash_until, self.e.elapsed)
        self.assertLessEqual(self.e.goggles_flash_until - self.e.elapsed, .55)
        advance(self.e, 1)
        self.assertLess(self.e.goggles_flash_until, self.e.elapsed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
