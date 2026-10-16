"""Behavioral regression tests. No recursive temporary-directory cleanup."""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea
from pet_window import PetWindow

APP = QApplication.instance() or QApplication(["phase1-tests"])
APP.setQuitOnLastWindowClosed(False)
ARTIFACTS = ROOT / "tests" / "artifacts" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)


def advance_for(engine: PetEngine, duration: float, fps: int = 60) -> None:
    for _ in range(round(duration * fps)):
        engine.advance(1.0 / fps)


class PhysicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))

    def test_breathing_preserves_area_and_ground_contact(self) -> None:
        heights = []
        for _ in range(360):
            self.engine.advance(1 / 60)
            pose = self.engine.pose
            heights.append(pose.scale_y)
            self.assertAlmostEqual(pose.scale_x * pose.scale_y, 1.0)
            self.assertAlmostEqual(self.engine.y + self.engine.bounds_offsets()[3], 1000)
        self.assertGreater(max(heights), 1.03)
        self.assertLess(min(heights), 0.97)

    def test_click_squashes_jumps_and_lands_exactly_once(self) -> None:
        self.engine.click()
        self.assertEqual(self.engine.state, PetState.HAPPY)
        self.assertLess(self.engine.pose.scale_y, 0.8)
        self.assertGreater(self.engine.pose.scale_x, 1.2)
        self.engine.advance(1 / 60)
        self.assertLess(self.engine.y, 1000)
        advance_for(self.engine, 2.0)
        self.assertTrue(self.engine.grounded)
        self.assertEqual(self.engine.landing_count, 1)
        self.assertEqual(self.engine.state, PetState.IDLE)
        self.assertAlmostEqual(self.engine.y, 1000)

    def test_happy_expression_expires_after_point_eight_seconds(self) -> None:
        self.engine.click()
        advance_for(self.engine, 0.75, 120)
        self.assertEqual(self.engine.state, PetState.HAPPY)
        advance_for(self.engine, 0.10, 120)
        self.assertEqual(self.engine.state, PetState.IDLE)

    def test_flat_is_a_separate_forty_percent_transform(self) -> None:
        ordinary_height = self.engine.pose.scale_y
        self.engine.set_flat(True)
        self.assertEqual(self.engine.state, PetState.FLAT)
        self.assertAlmostEqual(self.engine.pose.scale_y / ordinary_height, 0.4)
        advance_for(self.engine, 1.0)
        self.assertAlmostEqual(self.engine.y, 1000)
        self.engine.set_flat(False)
        self.assertEqual(self.engine.state, PetState.IDLE)

    def test_drag_expression_and_tilt_then_inherited_throw(self) -> None:
        self.engine.set_flat(True)
        self.engine.begin_drag()
        self.engine.drag_to(800, 450, 9000)
        advance_for(self.engine, 0.1)
        self.assertEqual(self.engine.state, PetState.DIZZY)
        self.assertGreater(self.engine.angle, 0)
        self.assertLessEqual(self.engine.angle, 18)
        self.engine.release_drag(1000, -500)
        self.assertAlmostEqual(self.engine.vx, 580)
        self.assertAlmostEqual(self.engine.vy, -290)
        advance_for(self.engine, 1.0)
        self.assertLess(abs(self.engine.angle), 0.02)
        self.assertEqual(self.engine.state, PetState.FLAT)

    def test_left_tilt_is_bounded(self) -> None:
        self.engine.begin_drag()
        self.engine.drag_to(700, 400, -100000)
        advance_for(self.engine, 0.1)
        self.assertGreaterEqual(self.engine.angle, -18)
        self.assertLess(self.engine.angle, 0)

    def test_larger_fall_causes_stronger_landing_compression(self) -> None:
        def first_impact(drop_height: float) -> tuple[float, float]:
            pet = PetEngine(self.engine.area)
            pet.y -= drop_height
            pet.grounded = False
            for _ in range(600):
                impact = pet.advance(1 / 120)
                if impact is not None:
                    return impact, abs(pet.spring)
            self.fail("No landing occurred")
        low_speed, low_compression = first_impact(40)
        high_speed, high_compression = first_impact(500)
        self.assertGreater(high_speed, low_speed * 2)
        self.assertGreater(high_compression, low_compression)

    def test_negative_origin_screen_and_horizontal_bounce(self) -> None:
        area = WorkArea(-1920, -200, 1920, 1080)
        self.engine.reset(area)
        self.engine.x = area.left + 70
        self.engine.y = 400
        self.engine.grounded = False
        self.engine.vx = -1100
        self.engine.advance(1 / 60)
        self.assertGreater(self.engine.vx, 0)
        advance_for(self.engine, 2)
        left, _, right, bottom = self.engine.bounds_offsets()
        self.assertGreaterEqual(self.engine.x + left, area.left - 0.001)
        self.assertLessEqual(self.engine.x + right, area.right + 0.001)
        self.assertAlmostEqual(self.engine.y + bottom, area.bottom)

    def test_right_edge_bounces(self) -> None:
        self.engine.x = 1530
        self.engine.y = 500
        self.engine.grounded = False
        self.engine.vx = 1100
        self.engine.advance(1 / 60)
        self.assertLess(self.engine.vx, 0)

    def test_motion_is_consistent_at_30_60_120_and_144_hz(self) -> None:
        positions = []
        for fps in (30, 60, 120, 144):
            pet = PetEngine(self.engine.area)
            pet.x, pet.y, pet.vx, pet.vy = 700, 250, 500, -120
            pet.grounded = False
            advance_for(pet, 1.5, fps)
            positions.append(pet.x)
            self.assertTrue(pet.grounded)
            self.assertEqual(pet.landing_count, 1)
            self.assertAlmostEqual(pet.y, 1000)
        self.assertLess(max(positions) - min(positions), 2.0)

    def test_long_suspend_does_not_teleport_physics(self) -> None:
        self.engine.y = 250
        self.engine.grounded = False
        self.engine.click()
        self.engine.advance(3600)
        self.assertLess(abs(self.engine.y - 250), 50)
        self.assertEqual(self.engine.state, PetState.IDLE)
        self.assertTrue(math.isfinite(self.engine.pose.scale_x))

    def test_work_area_change_releases_then_settles_at_new_floor(self) -> None:
        self.engine.set_work_area(WorkArea(0, 0, 1600, 1100))
        self.assertFalse(self.engine.grounded)
        advance_for(self.engine, 2)
        self.assertAlmostEqual(self.engine.y, 1100)
        self.engine.set_work_area(WorkArea(0, 0, 1600, 900))
        self.assertAlmostEqual(self.engine.y, 900)

    def test_spring_is_damped_and_reset_clears_transient_motion(self) -> None:
        self.engine.click()
        advance_for(self.engine, 3)
        self.assertLess(abs(self.engine.spring), 0.0001)
        self.engine.begin_drag()
        self.engine.drag_to(900, 400, 500)
        self.engine.reset()
        self.assertEqual(self.engine.state, PetState.IDLE)
        self.assertFalse(self.engine.held)
        self.assertEqual((self.engine.vx, self.engine.vy, self.engine.angle), (0, 0, 0))

    def test_hold_freezes_position_until_release(self) -> None:
        self.engine.y = 400
        self.engine.grounded = False
        self.engine.vy = 500
        self.engine.hold()
        advance_for(self.engine, 1)
        self.assertEqual(self.engine.y, 400)
        self.engine.click()
        self.engine.advance(1 / 60)
        self.assertLess(self.engine.y, 400)

    def test_bad_delta_is_ignored(self) -> None:
        for dt in (0, -1, float("nan"), float("inf")):
            self.assertIsNone(self.engine.advance(dt))
        self.assertEqual(self.engine.elapsed, 0)

    def test_drag_tilt_and_breath_stay_inside_work_area_at_edges(self) -> None:
        self.engine.begin_drag()
        self.engine.drag_to(1600, 1000, 2400)
        for _ in range(20):
            self.engine.advance(1 / 60)
            left, top, right, bottom = self.engine.bounds_offsets()
            self.assertGreaterEqual(self.engine.x + left, -0.001)
            self.assertLessEqual(self.engine.x + right, 1600.001)
            self.assertGreaterEqual(self.engine.y + top, -0.001)
            self.assertLessEqual(self.engine.y + bottom, 1000.001)


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skin_dir = ARTIFACTS / "fixture-skins"
        cls.skin_dir.mkdir()
        cls.colors = {
            PetState.IDLE: "#83aecc", PetState.HAPPY: "#e4afbd",
            PetState.DIZZY: "#baafd9", PetState.FLAT: "#e7bd77",
        }
        for state, color in cls.colors.items():
            image = QImage(100, 100, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.fillRect(18, 24, 64, 52, QColor(color))
            painter.end()
            destination = cls.skin_dir / f"{state.value}.png"
            if destination.exists():
                raise FileExistsError(destination)
            if not image.save(str(destination)):
                raise RuntimeError("Fixture PNG save failed")
        cls.renderer = SkinRenderer(cls.skin_dir)

    def setUp(self) -> None:
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))

    def render(self, renderer: SkinRenderer) -> QImage:
        image = QImage(384, 288, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.paint(painter, self.engine, QPointF(192, 244))
        painter.end()
        return image

    def test_all_png_states_are_loaded_and_alpha_padding_is_removed(self) -> None:
        self.assertEqual(len(self.renderer.pixmaps), 4)
        for image in self.renderer.images.values():
            self.assertEqual((image.width(), image.height()), (64, 52))

    def test_real_png_pixels_switch_for_all_four_states(self) -> None:
        for state in PetState:
            self.engine.reset()
            self.engine.set_flat(state == PetState.FLAT)
            if state == PetState.HAPPY:
                self.engine.click()
            elif state == PetState.DIZZY:
                self.engine.begin_drag()
            image = self.render(self.renderer)
            height = self.engine.BODY_HEIGHT * self.engine.pose.scale_y
            color = image.pixelColor(192, round(244 - height / 2))
            self.assertEqual(color.name(), self.colors[state])

    def test_missing_directory_uses_visible_fallback(self) -> None:
        renderer = SkinRenderer(ARTIFACTS / "does-not-exist")
        self.assertIsNone(renderer.source_state(PetState.IDLE))
        image = self.render(renderer)
        self.assertGreater(image.pixelColor(192, 200).alpha(), 0)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertTrue(image.save(str(ARTIFACTS / "fallback-idle.png")))

    def test_partial_skin_falls_back_to_idle(self) -> None:
        directory = ARTIFACTS / "partial"
        directory.mkdir()
        image = self.renderer.images[PetState.IDLE]
        self.assertTrue(image.save(str(directory / "idle.png")))
        renderer = SkinRenderer(directory)
        self.assertEqual(renderer.source_state(PetState.HAPPY), PetState.IDLE)

    def test_broken_and_transparent_pngs_do_not_crash(self) -> None:
        directory = ARTIFACTS / "bad-png"
        directory.mkdir()
        (directory / "idle.png").write_bytes(b"not a png")
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        self.assertTrue(image.save(str(directory / "happy.png")))
        with self.assertLogs("pet_engine", level="WARNING") as messages:
            renderer = SkinRenderer(directory)
        self.assertEqual(len(renderer.pixmaps), 0)
        self.assertEqual(len(messages.output), 2)

    def test_transform_keeps_bottom_center_fixed_for_every_state(self) -> None:
        for flat in (False, True):
            self.engine.set_flat(flat)
            self.engine.click()
            for _ in range(120):
                self.engine.advance(1 / 60)
                foot = QPointF(192.3, 244.7)
                anchor = self.renderer.body_transform(self.engine, foot).map(QPointF(0, 0))
                self.assertAlmostEqual(anchor.x(), foot.x())
                self.assertAlmostEqual(anchor.y(), foot.y())

    def test_fallback_hit_test_follows_deformation(self) -> None:
        renderer = SkinRenderer(ARTIFACTS / "absent")
        foot = QPointF(192, 244)
        self.assertTrue(renderer.hit_test(self.engine, foot, QPointF(192, 200)))
        self.assertFalse(renderer.hit_test(self.engine, foot, QPointF(130, 130)))
        self.engine.set_flat(True)
        self.assertFalse(renderer.hit_test(self.engine, foot, QPointF(192, 170)))
        self.assertTrue(renderer.hit_test(self.engine, foot, QPointF(192, 230)))

    def test_png_alpha_hole_is_not_clickable(self) -> None:
        directory = ARTIFACTS / "hole"
        directory.mkdir()
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(QColor("#aabbcc"))
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(30, 30, 40, 40, Qt.GlobalColor.transparent)
        painter.end()
        self.assertTrue(image.save(str(directory / "idle.png")))
        renderer = SkinRenderer(directory)
        self.assertFalse(renderer.hit_test(self.engine, QPointF(192, 244), QPointF(192, 186)))


class InputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = PetWindow(ARTIFACTS / "no-default-skin")
        self.window.timer.stop()
        self.clicks = []
        self.drags = []
        self.window.clicked.connect(lambda: self.clicks.append(True))
        self.window.drag_started.connect(lambda: self.drags.append(True))
        self.start = QPointF(self.window.engine.x, self.window.engine.y - 50)

    def tearDown(self) -> None:
        self.window.stop()
        self.window.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def send(self, kind: QEvent.Type, point: QPointF, at: float) -> None:
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        local = point - QPointF(self.window.pos())
        event = QMouseEvent(kind, local, point, button, buttons, Qt.KeyboardModifier.NoModifier)
        with patch("pet_window.time.perf_counter", return_value=at):
            APP.sendEvent(self.window, event)

    def test_small_pointer_jitter_is_one_click(self) -> None:
        self.send(QEvent.Type.MouseButtonPress, self.start, 100)
        self.send(QEvent.Type.MouseMove, self.start + QPointF(2, -1), 100.03)
        self.send(QEvent.Type.MouseButtonRelease, self.start + QPointF(2, -1), 100.06)
        self.assertEqual(len(self.clicks), 1)
        self.assertEqual(len(self.drags), 0)
        self.assertEqual(self.window.engine.state, PetState.HAPPY)

    def test_drag_uses_dizzy_then_throw_without_click(self) -> None:
        self.send(QEvent.Type.MouseButtonPress, self.start, 100)
        moved = self.start + QPointF(-60, -180)
        self.send(QEvent.Type.MouseMove, moved, 100.05)
        self.assertEqual(self.window.engine.state, PetState.DIZZY)
        self.send(QEvent.Type.MouseButtonRelease, moved + QPointF(-10, 0), 100.07)
        self.assertEqual(len(self.drags), 1)
        self.assertEqual(len(self.clicks), 0)
        self.assertFalse(self.window.engine.held)
        self.assertLess(self.window.engine.vx, 0)

    def test_pause_before_release_does_not_reuse_old_throw_velocity(self) -> None:
        self.send(QEvent.Type.MouseButtonPress, self.start, 100)
        moved = self.start + QPointF(-100, -200)
        self.send(QEvent.Type.MouseMove, moved, 100.05)
        self.send(QEvent.Type.MouseButtonRelease, moved, 100.6)
        self.assertEqual((self.window.engine.vx, self.window.engine.vy), (0, 0))

    def test_transparent_corner_does_not_start_click(self) -> None:
        outside = QPointF(self.window.pos()) + QPointF(5, 5)
        self.send(QEvent.Type.MouseButtonPress, outside, 100)
        self.send(QEvent.Type.MouseButtonRelease, outside, 100.03)
        self.assertFalse(self.window._pressed)
        self.assertEqual(len(self.clicks), 0)

    def test_flat_toggle_and_reset_preserve_test_state(self) -> None:
        self.window.set_test_flat(True)
        self.window.engine.begin_drag()
        self.window.reset_to_primary()
        self.window.timer.stop()
        self.assertTrue(self.window.engine.flat)
        self.assertFalse(self.window.engine.dragging)
        self.assertAlmostEqual(self.window.engine.y, self.window.engine.area.bottom)

    def test_lost_mouse_grab_releases_a_held_pet(self) -> None:
        self.send(QEvent.Type.MouseButtonPress, self.start, 100)
        self.send(QEvent.Type.MouseMove, self.start + QPointF(-50, -100), 100.03)
        APP.sendEvent(self.window, QEvent(QEvent.Type.UngrabMouse))
        self.assertFalse(self.window._pressed)
        self.assertFalse(self.window.engine.held)
        self.assertFalse(self.window.engine.dragging)


if __name__ == "__main__":
    print(f"Retained test artifacts: {ARTIFACTS}", flush=True)
    unittest.main(verbosity=2)
