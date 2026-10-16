"""Phase 4 unified PNG/GIF transforms, layers and programmatic tricks."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from uuid import uuid4

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMovie, QPainter, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea
from pet_window import PetWindow

APP = QApplication.instance() or QApplication(["phase4-render-tests"])
ARTIFACTS = ROOT / "tests/artifacts" / datetime.now().strftime("phase4-rendering-%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)


def gif_bytes():
    header = b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    result = header + b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for index in range(2):
        result += b"\x21\xf9\x04\x00\x08\x00\x00\x00"
        result += b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
        result += b"\x44\x01\x00" if index == 0 else b"\x4c\x01\x00"
    return result + b"\x3b"


def padded_gif_bytes(boxes, width=64, height=64):
    """Opaque cream bodies in a transparent logical canvas; stdlib encoder."""
    result = (b"GIF89a" + struct.pack("<HH", width, height)
              + b"\x80\x00\x00\x00\x00\x00\xff\xf8\xe7"
              + b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
    for box in boxes:
        codes = []
        for y in range(height):
            for x in range(width):
                visible = box is not None and box[0] <= x < box[2] and box[1] <= y < box[3]
                codes.extend((4, int(visible)))  # clear before every pixel: fixed 3-bit codes
        codes.append(5)
        payload, bits, value = bytearray(), 0, 0
        for code in codes:
            value |= code << bits
            bits += 3
            while bits >= 8:
                payload.append(value & 255)
                value >>= 8
                bits -= 8
        if bits:
            payload.append(value & 255)
        result += b"\x21\xf9\x04\x09\x08\x00\x00\x00"
        result += b"\x2c\x00\x00\x00\x00" + struct.pack("<HH", width, height) + b"\x00\x02"
        for position in range(0, len(payload), 255):
            block = payload[position:position + 255]
            result += bytes([len(block)]) + block
        result += b"\x00"
    return result + b"\x3b"


def advance(engine, duration):
    for _ in range(round(duration * 240)):
        engine.advance(1 / 240)


class TrickEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))

    def test_flip_has_high_jump_and_half_turn_without_moving_pinned_anchor(self):
        self.engine.set_pinned(True)
        foot = self.engine.x, self.engine.y
        self.assertTrue(self.engine.perform_trick("flip"))
        advance(self.engine, 0.55)
        self.assertAlmostEqual(self.engine.visual_angle, 180, places=5)
        self.assertLess(self.engine.visual_offset.y(), -160)
        self.assertEqual((self.engine.x, self.engine.y), foot)
        self.assertEqual(self.engine.active_trick, "flip")

    def test_free_flip_also_keeps_physics_anchor_and_does_not_fake_drop(self):
        foot = self.engine.x, self.engine.y
        lands = self.engine.landing_count
        self.assertTrue(self.engine.perform_trick("flip"))
        advance(self.engine, 1.11)
        self.assertEqual((self.engine.x, self.engine.y), foot)
        self.assertEqual(self.engine.landing_count, lands)
        self.assertEqual(self.engine.active_trick, "")
        self.assertEqual(self.engine.visual_angle, 0)
        self.assertLess(self.engine.spring, 0)
        self.assertEqual(self.engine.state, PetState.HAPPY)

    def test_clone_and_ball_have_requested_durations(self):
        self.assertTrue(self.engine.perform_trick("clone"))
        advance(self.engine, 2.49)
        self.assertEqual(self.engine.active_trick, "clone")
        advance(self.engine, 0.02)
        self.assertEqual(self.engine.active_trick, "")
        self.assertTrue(self.engine.perform_trick("ball"))
        advance(self.engine, 4.99)
        self.assertEqual(self.engine.active_trick, "ball")
        advance(self.engine, 0.02)
        self.assertEqual(self.engine.active_trick, "")

    def test_ball_obeys_gravity_and_elastic_side_collision(self):
        self.engine.perform_trick("ball")
        initial = self.engine.ball_vy
        advance(self.engine, 0.03)
        self.assertGreater(self.engine.ball_vy, initial)
        self.engine.ball_x, self.engine.ball_vx = 144.9, 150
        advance(self.engine, 0.03)
        self.assertLess(self.engine.ball_vx, 0)
        self.assertLessEqual(self.engine.ball_x, 145)

    def test_ball_bounces_off_body_and_keeps_pinned_anchor(self):
        self.engine.set_pinned(True)
        foot = self.engine.x, self.engine.y
        self.engine.perform_trick("ball")
        self.engine.ball_x, self.engine.ball_y = 0, -110
        self.engine.ball_vy = 220
        self.engine.advance(1 / 240)
        self.assertLess(self.engine.ball_vy, 0)
        advance(self.engine, 3)
        self.assertEqual((self.engine.x, self.engine.y), foot)

    def test_tricks_are_mutually_exclusive_and_unknown_rejected(self):
        self.assertFalse(self.engine.perform_trick("unsafe"))
        self.assertTrue(self.engine.perform_trick("clone"))
        self.assertFalse(self.engine.perform_trick("flip"))

    def test_flat_held_and_airborne_reject_start(self):
        self.engine.set_flat(True)
        self.assertFalse(self.engine.perform_trick("flip"))
        self.engine.set_flat(False)
        self.engine.hold()
        self.assertFalse(self.engine.perform_trick("flip"))
        self.engine.held = False
        self.engine.grounded = False
        self.assertFalse(self.engine.perform_trick("flip"))

    def test_drag_reset_and_starvation_cancel_active_trick(self):
        self.engine.perform_trick("clone")
        self.engine.begin_drag()
        self.assertEqual(self.engine.active_trick, "")
        self.engine.reset()
        self.engine.perform_trick("flip")
        self.engine.reset()
        self.assertEqual(self.engine.active_trick, "")
        self.engine.perform_trick("ball")
        self.engine.set_starving(True)
        self.assertEqual(self.engine.active_trick, "")

    def test_chili_does_not_displace_performing_pet(self):
        self.engine.set_buff({"scale": 1.2, "remaining_seconds": 60, "behavior_remaining": 12})
        foot = self.engine.x, self.engine.y
        self.engine.perform_trick("clone")
        advance(self.engine, 1)
        self.assertEqual((self.engine.x, self.engine.y), foot)


class LayerAndSkinTests(unittest.TestCase):
    def setUp(self):
        self.work = ARTIFACTS / (self._testMethodName + "-" + uuid4().hex)
        self.work.mkdir()
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        self.renderers = []
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.stop()
            window.hide()
        for renderer in self.renderers:
            renderer.stop()

    def make_skin(self, animated=False, white=False, size=(80, 100), **manifest):
        folder = self.work / uuid4().hex
        folder.mkdir()
        if animated:
            (folder / "idle.gif").write_bytes(gif_bytes())
            states = {"idle": "idle.gif"}
        else:
            image = QImage(*size, QImage.Format.Format_RGBA8888)
            image.fill(QColor("white") if white else Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setPen(QPen(QColor("#735e64"), 3))
            painter.setBrush(QColor("#fff8e7"))
            painter.drawEllipse(5, 5, size[0] - 10, size[1] - 10)
            painter.end()
            image.save(str(folder / "idle.png"), "PNG")
            states = {"idle": "idle.png"}
        (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "states": states, **manifest}), encoding="utf-8")
        return folder

    def renderer(self, folder):
        renderer = SkinRenderer(folder)
        self.renderers.append(renderer)
        return renderer

    def render(self, renderer):
        image = QImage(PetWindow.CANVAS_WIDTH, PetWindow.CANVAS_HEIGHT, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.paint(painter, self.engine, QPointF(PetWindow.ANCHOR_X, PetWindow.ANCHOR_Y))
        painter.end()
        return image

    def pixels(self, renderer):
        image = self.render(renderer)
        return bytes(image.constBits())

    def test_single_png_preserves_aspect_and_all_missing_states_fall_back(self):
        renderer = self.renderer(self.make_skin(size=(90, 140)))
        rect = renderer.draw_rects[PetState.IDLE]
        self.assertLess(rect.width(), rect.height())
        self.assertEqual(rect.bottom(), 0)
        self.assertTrue(all(renderer.source_state(state) == PetState.IDLE for state in PetState))

    def test_white_removal_applies_even_when_png_already_has_alpha_channel(self):
        renderer = self.renderer(self.make_skin(white=True, remove_white_background=True))
        image = renderer.images[PetState.IDLE]
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 250)

    def test_custom_large_png_texture_never_exceeds_512(self):
        renderer = self.renderer(self.make_skin(size=(1600, 1200)))
        self.assertLessEqual(max(renderer.images[PetState.IDLE].size().toTuple()), 512)

    def test_head_face_effect_settings_clamp_offset_and_unknown_ids(self):
        renderer = self.renderer(self.make_skin())
        renderer.set_accessories({"head": "crown", "face": "sunglasses", "effect": "steam", "offset_y": -80})
        self.assertEqual(renderer.accessories["offset_y"], -30)
        renderer.set_accessories({"head": "not-an-accessory", "offset_y": float("nan")})
        self.assertEqual(renderer.accessories, {"head": "", "face": "", "effect": "", "offset_y": 0})

    def test_each_head_accessory_draws_above_actual_png_body(self):
        renderer = self.renderer(self.make_skin())
        plain = self.pixels(renderer)
        for head in ("sprout", "crown", "bow"):
            with self.subTest(head=head):
                renderer.set_accessories({"head": head, "offset_y": -10})
                image = self.render(renderer)
                self.assertNotEqual(bytes(image.constBits()), plain)
                self.assertTrue(image.save(str(self.work / (head + ".png"))))
                self.assertLess(renderer.accessory_bounds(PetState.IDLE).top(), renderer.anchor_rect(PetState.IDLE).top())

    def test_sunglasses_and_steam_draw_independent_layers(self):
        renderer = self.renderer(self.make_skin())
        self.engine.elapsed = 0.3
        plain = self.pixels(renderer)
        for fields in ({"face": "sunglasses"}, {"effect": "steam"}):
            renderer.set_accessories(fields)
            self.assertNotEqual(self.pixels(renderer), plain)

    def test_offset_is_local_and_follows_scaled_rotated_anchor(self):
        renderer = self.renderer(self.make_skin())
        self.engine.angle = 18
        self.engine.spring = -0.3
        self.engine.set_buff({"scale": 1.2, "remaining_seconds": 60})
        transform = renderer.body_transform(self.engine, QPointF(400, 544))
        rect = renderer.anchor_rect(PetState.IDLE)
        original = transform.map(QPointF(rect.center().x(), rect.top()))
        adjusted = transform.map(QPointF(rect.center().x(), rect.top() - 30))
        self.assertAlmostEqual(math.hypot(adjusted.x() - original.x(), adjusted.y() - original.y()), 30 * self.engine.pose.scale_y)

    def test_flip_clones_accessories_and_size_buff_fit_entire_expanded_canvas(self):
        renderer = self.renderer(ROOT / "assets/skins/default")
        renderer.set_accessories({"head": "crown", "face": "sunglasses", "effect": "steam", "offset_y": -30})
        canvas = QRectF(0, 0, PetWindow.CANVAS_WIDTH, PetWindow.CANVAS_HEIGHT)
        foot = QPointF(PetWindow.ANCHOR_X, PetWindow.ANCHOR_Y)
        for trick in ("flip", "clone", "ball"):
            self.engine.reset()
            self.engine.set_buff({"scale": 1.2, "remaining_seconds": 60})
            self.engine.perform_trick(trick)
            for index in range(60):
                self.engine.spring = -0.45 if index % 2 else 0.38
                self.engine.angle = -18 if index % 2 else 18
                bounds = renderer.scene_bounds(self.engine, foot)
                with self.subTest(trick=trick, frame=index):
                    self.assertTrue(canvas.contains(bounds), str(bounds))
                self.engine.advance(self.engine._trick_duration / 61)

    def test_clone_has_two_equal_scale_transparent_instances_that_merge(self):
        renderer = self.renderer(self.make_skin())
        self.engine.perform_trick("clone")
        advance(self.engine, 1)
        clones = renderer._clone_offsets(self.engine)
        self.assertEqual(len(clones), 2)
        self.assertLess(clones[0][0], 0)
        self.assertGreater(clones[1][0], 0)
        self.assertTrue(all(0 < opacity < 0.5 for _x, _y, opacity in clones))
        self.render(renderer).save(str(self.work / "clone.png"))
        advance(self.engine, 1.51)
        self.assertEqual(renderer._clone_offsets(self.engine), [])

    def test_qmovie_frames_change_without_growing_tint_cache(self):
        renderer = self.renderer(self.make_skin(animated=True))
        self.assertIn(PetState.IDLE, renderer.movies)
        movie = renderer.movies[PetState.IDLE]
        self.assertEqual(movie.cacheMode(), QMovie.CacheMode.CacheNone)
        observed = set()
        for _ in range(8):
            QTest.qWait(45)
            image = renderer.images[PetState.IDLE]
            observed.add(hashlib.sha256(bytes(image.constBits())).hexdigest())
            renderer.tinted_pixmap(PetState.IDLE, "#e48da5")
            self.assertLessEqual(len(renderer.tint_cache), 1)
            self.assertLessEqual(max(image.size().toTuple()), 512)
        self.assertEqual(len(observed), 2)

    def test_gif_tint_keeps_alpha_and_crown_flip_uses_same_transform(self):
        renderer = self.renderer(self.make_skin(animated=True))
        renderer.set_accessories({"head": "crown", "offset_y": -15})
        self.engine.set_buff({"scale": 1.2, "color": "#f58fb1", "remaining_seconds": 60})
        self.engine.perform_trick("flip")
        advance(self.engine, 0.3)
        plain = renderer.pixmaps[PetState.IDLE].toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        tinted = renderer.tinted_pixmap(PetState.IDLE, "#f58fb1").toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        self.assertEqual(bytes(plain.constBits())[3::4], bytes(tinted.constBits())[3::4])
        image = self.render(renderer)
        self.assertTrue(image.save(str(self.work / "gif-crown-flip.png")))
        self.assertNotEqual(renderer.body_transform(self.engine, QPointF(400, 544)).map(QPointF(0, -116)), QPointF(400, 428))

    def test_gif_shared_state_file_uses_one_movie_and_stop_stops_it(self):
        folder = self.make_skin(animated=True, states={state.value: "idle.gif" for state in PetState})
        renderer = self.renderer(folder)
        self.assertEqual(len(set(renderer.movies.values())), 1)
        renderer.stop()
        self.assertTrue(all(movie.state() == QMovie.MovieState.NotRunning for movie in renderer.movies.values()))

    def test_manual_manifest_path_escape_and_oversized_gif_canvas_rejected(self):
        folder = self.make_skin()
        (folder / "manifest.json").write_text(json.dumps({"states": {"idle": "../outside.png"}}), encoding="utf-8")
        self.assertFalse(self.renderer(folder).pixmaps)
        gif_folder = self.make_skin(animated=True)
        payload = bytearray((gif_folder / "idle.gif").read_bytes())
        payload[6:10] = struct.pack("<HH", 65535, 65535)
        (gif_folder / "idle.gif").write_bytes(payload)
        self.assertFalse(self.renderer(gif_folder).pixmaps)

    def test_set_skin_keeps_accessories_and_pinned_position_stops_old_movie(self):
        window = PetWindow(self.make_skin(animated=True))
        self.windows.append(window)
        window.timer.stop()
        window.set_pinned(True)
        window.set_accessories({"head": "crown", "offset_y": 17})
        foot = window.engine.x, window.engine.y
        old = window.renderer
        self.assertTrue(window.set_skin(self.make_skin()))
        self.assertTrue(all(movie.state() == QMovie.MovieState.NotRunning for movie in old.movies.values()))
        self.assertEqual(window.renderer.accessories["head"], "crown")
        self.assertEqual(window.renderer.accessories["offset_y"], 17)
        self.assertEqual((window.engine.x, window.engine.y), foot)
        self.assertFalse(window.set_skin(self.work / "missing-skin"))
        self.assertEqual(window.renderer.accessories["head"], "crown")

    def test_gif_logical_canvas_is_stable_when_frame_block_is_tiny(self):
        folder = self.make_skin(animated=True)
        payload = bytearray((folder / "idle.gif").read_bytes())
        payload[6:10] = struct.pack("<HH", 16, 12)
        (folder / "idle.gif").write_bytes(payload)
        renderer = self.renderer(folder)
        self.assertEqual(renderer.movies[PetState.IDLE].scaledSize().toTuple(), (16, 12))
        first = QRectF(renderer.draw_rects[PetState.IDLE])
        QTest.qWait(180)
        self.assertEqual(renderer.draw_rects[PetState.IDLE], first)
        self.assertLessEqual(max(renderer.images[PetState.IDLE].size().toTuple()), 512)

    def test_svg_disguised_as_png_is_rejected_during_hot_reload(self):
        folder = self.make_skin()
        (folder / "idle.png").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="red"/></svg>', encoding="utf-8")
        self.assertFalse(self.renderer(folder).pixmaps)

    @unittest.skipUnless(sys.platform == "win32", "Windows junction guard")
    def test_runtime_rejects_skin_root_replaced_by_actual_junction(self):
        source = self.make_skin()
        link = self.work / "junction-skin"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(source)],
                                cwd=ROOT, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, repr(result.stderr))
        self.assertFalse(self.renderer(link).pixmaps)
        self.assertTrue(source.is_dir())

    def test_arbitrary_tint_colors_cannot_grow_cache_unbounded(self):
        renderer = self.renderer(self.make_skin())
        for index in range(100):
            renderer.tinted_pixmap(PetState.IDLE, f"#{index:06x}")
            self.assertLessEqual(len(renderer.tint_cache), 32)

    def test_gif_padding_feet_and_crown_use_stable_visible_body_union(self):
        folder = self.make_skin(animated=True)
        (folder / "idle.gif").write_bytes(padded_gif_bytes([(20, 12, 40, 50), (23, 12, 43, 50)]))
        renderer = self.renderer(folder)
        source = PetState.IDLE
        rect = QRectF(renderer.draw_rects[source])
        anchor = QRectF(renderer.anchor_rect(source))
        self.assertEqual(anchor.bottom(), 0)
        self.assertAlmostEqual(anchor.top(), -116)
        scale = rect.width() / 64
        self.assertAlmostEqual(rect.top() + 50 * scale, 0)
        self.assertAlmostEqual(rect.left() + (20 + 43) / 2 * scale, 0)
        self.assertAlmostEqual(anchor.top(), rect.top() + 12 * scale)
        renderer.set_accessories({"head": "crown"})
        self.assertLess(renderer.accessory_bounds(source).top(), anchor.top())
        QTest.qWait(190)
        self.assertEqual(renderer.draw_rects[source], rect)
        self.assertEqual(renderer.anchor_rect(source), anchor)
        self.render(renderer).save(str(self.work / "padded-gif-crown.png"))

    def test_gif_first_transparent_frame_can_find_later_visible_reference(self):
        folder = self.make_skin(animated=True)
        (folder / "idle.gif").write_bytes(padded_gif_bytes([None, (20, 12, 40, 50)]))
        renderer = self.renderer(folder)
        self.assertIn(PetState.IDLE, renderer.pixmaps)
        self.assertAlmostEqual(renderer.anchor_rect(PetState.IDLE).top(), -116)
        self.assertEqual(renderer.anchor_rect(PetState.IDLE).bottom(), 0)
        QTest.qWait(100)
        self.assertIsNotNone(renderer._visible_alpha_box(renderer.images[PetState.IDLE]))

    def test_tiny_gif_body_cannot_magnify_transparent_canvas_without_bound(self):
        folder = self.make_skin(animated=True)
        (folder / "idle.gif").write_bytes(padded_gif_bytes([(1, 1, 2, 2), (1, 1, 2, 2)]))
        renderer = self.renderer(folder)
        rect = renderer.draw_rects[PetState.IDLE]
        self.assertLessEqual(max(rect.width(), rect.height()), 256)
        visible = renderer.visible_rect(PetState.IDLE)
        self.assertEqual(visible.bottom(), 0)
        self.assertLessEqual(visible.width(), 4)
        canvas = QRectF(0, 0, PetWindow.CANVAS_WIDTH, PetWindow.CANVAS_HEIGHT)
        self.assertTrue(canvas.contains(renderer.scene_bounds(self.engine, QPointF(PetWindow.ANCHOR_X, PetWindow.ANCHOR_Y))))

    def test_extremely_thin_transparent_png_stays_valid_at_source_dimension_limit(self):
        for width, height in ((8192, 1), (1, 8192)):
            with self.subTest(size=(width, height)):
                folder = self.make_skin()
                image = QImage(width, height, QImage.Format.Format_RGBA8888)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.fillRect(width // 4 if width > 1 else 0,
                                 height // 4 if height > 1 else 0,
                                 width // 2 if width > 1 else 1,
                                 height // 2 if height > 1 else 1, QColor("#f9d8e8"))
                painter.end()
                self.assertTrue(image.save(str(folder / "idle.png"), "PNG"))
                renderer = self.renderer(folder)
                self.assertIn(PetState.IDLE, renderer.images)
                texture = renderer.images[PetState.IDLE]
                self.assertGreater(min(texture.width(), texture.height()), 0)
                self.assertLessEqual(max(texture.width(), texture.height()), 512)
                anchor = renderer.anchor_rect(PetState.IDLE)
                self.assertGreater(anchor.width(), 0)
                self.assertGreater(anchor.height(), 0)
                self.assertEqual(anchor.bottom(), 0)
                self.assertTrue(renderer.hit_test(self.engine, QPointF(400, 544),
                    renderer.body_transform(self.engine, QPointF(400, 544)).map(anchor.center())))
                self.render(renderer)

    def test_extremely_thin_transparent_gif_keeps_valid_texture_every_frame(self):
        for width, height in ((8192, 1), (1, 8192)):
            with self.subTest(size=(width, height)):
                folder = self.make_skin(animated=True)
                box = (width // 4 if width > 1 else 0,
                       height // 4 if height > 1 else 0,
                       width * 3 // 4 if width > 1 else 1,
                       height * 3 // 4 if height > 1 else 1)
                (folder / "idle.gif").write_bytes(padded_gif_bytes([box, box], width, height))
                renderer = self.renderer(folder)
                self.assertIn(PetState.IDLE, renderer.movies)
                movie = renderer.movies[PetState.IDLE]
                self.assertGreater(min(movie.scaledSize().toTuple()), 0)
                self.assertLessEqual(max(movie.scaledSize().toTuple()), 512)
                for _ in range(3):
                    QTest.qWait(60)
                    image = renderer.images[PetState.IDLE]
                    self.assertGreater(min(image.width(), image.height()), 0)
                    self.assertLessEqual(max(image.width(), image.height()), 512)
                    self.assertGreater(renderer.anchor_rect(PetState.IDLE).width(), 0)
                    self.assertGreater(renderer.anchor_rect(PetState.IDLE).height(), 0)
                    self.render(renderer)

    def test_window_trick_finishes_signal_without_drag_drop(self):
        window = PetWindow(self.make_skin())
        self.windows.append(window)
        window.timer.stop()
        window.set_pinned(True)
        events, drops = [], []
        window.trick_finished.connect(events.append)
        window.drag_landed.connect(lambda: drops.append(True))
        self.assertTrue(window.perform_trick("flip"))
        window.engine._trick_started -= 1.2
        window._on_frame()
        window.timer.stop()
        self.assertEqual(events, ["flip"])
        self.assertEqual(drops, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
