"""Reverse flash preserves the real painted origin at camera-fitting edges."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from home_scene import IllustratedRoomCanvas
from main import PetApplication
from models import PetData
from pet_engine import PetEngine, SkinRenderer, WorkArea

APP = QApplication.instance() or QApplication(["part2-flash-origin"])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part2-flash-edges-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def foot(room):
    return room._pet_transform().map(room._render_foot() + room._view().visual_offset)


def advance(engine, room, seconds):
    for _ in range(round(seconds * 60)):
        engine.advance(1 / 60)
        room.advance_scene(1 / 60)


class ControllerFlashEdgeTests(unittest.TestCase):
    def setUp(self):
        work = ART / self._testMethodName; work.mkdir()
        self.c = PetApplication(APP, save_path=work / "save_data.json", skins_root=work / "skins", dev_mode=True)
        self.c.dashboard.resize(1240, 800)
        APP.processEvents()
        for owner in (self.c.window, self.c.dashboard):
            for timer in owner.findChildren(QTimer):
                timer.stop()
        self.m, self.e, self.r = self.c.model, self.c.window.engine, self.c.dashboard.room
        self.m.replace_data(PetData(coins=0, hunger=80, affection_level=30, muted=True))
        self.e.set_work_area(WorkArea(0, 0, 2000, 1300))
        self.c.window.set_pinned(True); self.e.place(800, 900)
        self.assertTrue(self.m.buy_trick("reverse_flash"))

    def tearDown(self):
        self.c.stop()
        self.c.dashboard.deleteLater(); self.c.window.deleteLater(); self.c.tray.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def configure(self, width, height, x, *, large=False):
        if large:
            self.assertTrue(self.m.set_skin_scale(1.5))
            self.e.set_buff({"item_id": "sesame", "scale": 1.2, "remaining_seconds": 60})
            self.assertTrue(self.m.equip_accessory("head", "crown"))
            self.assertTrue(self.m.equip_accessory("back", "phoenix_wings"))
            self.assertTrue(self.m.set_accessory_offset(-30))
        # Deliberately exercise the canvas viewport dimensions, independent of
        # the top-level window's minimum size and its drawer allocation.
        self.r.resize(width, height)
        self.r.life.x = x
        self.r.life.interact(); self.r.life.wait = 1000
        self.r._settle_offset = QPointF(); self.r._settle_age = 1

    def same_point(self, first, second, note=""):
        self.assertAlmostEqual(first.x(), second.x(), delta=.03, msg=note + " x")
        self.assertAlmostEqual(first.y(), second.y(), delta=.03, msg=note + " y")

    def assert_origin_and_completion(self):
        origin = foot(self.r); desktop = self.c.window.capture_position()
        self.assertTrue(self.c._perform_trick("reverse_flash"))
        self.same_point(foot(self.r), origin, "accepted first frame")
        advance(self.e, self.r, .8)
        middle = foot(self.r)
        # Camera-mapped coordinates are still scene units; the outer room
        # painter applies this scale before they become QWidget pixels.
        travelled_pixels = (origin.x() - middle.x()) * self.r._geometry()[0]
        self.assertGreaterEqual(travelled_pixels, -.03)
        self.assertLessEqual(travelled_pixels, 60.03)
        self.assertAlmostEqual(middle.y(), origin.y(), delta=.03)
        # Consume just beyond the natural end, while the independent idle
        # return delay has not elapsed. The endpoint belongs to this origin.
        advance(self.e, self.r, 1.85)
        self.assertEqual(self.e.active_trick, "")
        self.same_point(foot(self.r), origin, "natural endpoint")
        self.assertEqual(self.c.window.capture_position(), desktop)
        advance(self.e, self.r, 8)
        self.assertAlmostEqual(self.r.life.x, self.r.life.HOME_X, places=6)
        self.same_point(foot(self.r), self.r._base_foot(), "eventual HOME")
        self.assertEqual(self.c.window.capture_position(), desktop)

    def test_narrow_left_keeps_first_frame_and_natural_origin(self):
        self.configure(500, 760, .28)
        self.assert_origin_and_completion()

    def test_narrow_right_keeps_first_frame_and_natural_origin(self):
        self.configure(500, 760, .70)
        self.assert_origin_and_completion()

    def test_large_skin_buff_and_wings_at_left_preserve_the_painted_origin(self):
        self.configure(1240, 800, .28, large=True)
        self.assert_origin_and_completion()

    def test_large_skin_buff_and_wings_at_right_preserve_the_painted_origin(self):
        self.configure(1240, 800, .70, large=True)
        self.assert_origin_and_completion()

    def test_input_mid_dash_is_continuous_and_returns_home_without_desktop_drift(self):
        self.configure(500, 760, .28, large=True)
        desktop = self.c.window.capture_position()
        self.assertTrue(self.c._perform_trick("reverse_flash"))
        advance(self.e, self.r, .8)
        before = foot(self.r)
        self.c._room_poke()
        self.assertEqual(self.e.active_trick, "")
        self.same_point(foot(self.r), before, "input interruption")
        advance(self.e, self.r, 8)
        self.assertAlmostEqual(self.r.life.x, self.r.life.HOME_X, places=6)
        self.same_point(foot(self.r), self.r._base_foot(), "HOME after interruption")
        self.assertEqual(self.c.window.capture_position(), desktop)
        self.assertIsNone(self.r.performance)
        self.assertFalse(self.r._gift_queue or self.r._food_queue)

    def test_real_pointer_signal_chain_does_not_recapture_an_uncancelled_engine_offset(self):
        self.configure(1240, 800, .70, large=True)
        desktop = self.c.window.capture_position()
        self.assertTrue(self.c._perform_trick("reverse_flash"))
        advance(self.e, self.r, .85)
        before = foot(self.r)
        clicks = self.m.data.stats["total_clicks"]
        QTest.mouseClick(self.r, Qt.MouseButton.LeftButton, pos=self.r.pet_center().toPoint())
        self.assertEqual(self.m.data.stats["total_clicks"], clicks + 1)
        self.assertEqual(self.e.active_trick, "")
        self.same_point(foot(self.r), before, "real pointer interruption")
        advance(self.e, self.r, 8)
        self.same_point(foot(self.r), self.r._base_foot(), "real pointer HOME")
        self.assertEqual(self.c.window.capture_position(), desktop)


class StandaloneFlashOriginTests(unittest.TestCase):
    def test_prepared_standalone_view_uses_the_same_real_painted_origin(self):
        e = PetEngine(WorkArea(0, 0, 1600, 1100)); e.set_pinned(True)
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(e, lambda: renderer)
        room.resize(500, 760); room._animation_timer.stop()
        room.life.x = .28; room.life.interact(); room.life.wait = 1000
        desktop = e.x, e.y
        try:
            origin = foot(room)
            room.prepare_trick()
            self.assertTrue(e.perform_trick("reverse_flash", flash_distance=35))
            room.begin_trick("reverse_flash")
            first = foot(room)
            self.assertAlmostEqual(first.x(), origin.x(), delta=.03)
            self.assertAlmostEqual(first.y(), origin.y(), delta=.03)
            advance(e, room, .9)
            current = foot(room)
            room.cancel_presentation("input", cancel_engine=True)
            self.assertAlmostEqual(foot(room).x(), current.x(), delta=.03)
            self.assertAlmostEqual(foot(room).y(), current.y(), delta=.03)
            advance(e, room, 8)
            self.assertAlmostEqual(foot(room).x(), room._base_foot().x(), delta=.03)
            self.assertAlmostEqual(foot(room).y(), room._base_foot().y(), delta=.03)
            self.assertEqual((e.x, e.y), desktop)
        finally:
            room.stop(); room.deleteLater(); renderer.stop(); renderer.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main(verbosity=2)
