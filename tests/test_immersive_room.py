"""Edge-to-edge storybook room: layout, art replacement and shared interactions.

Fixtures and captures stay beneath tests/artifacts; player data is never opened.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import struct
import sys
import unittest
import zlib

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from home_scene import GiftPerformance, IllustratedRoomCanvas
from models import Catalog, PetData, PetModel
from pet_engine import PetEngine, RoomCanvas, SkinRenderer, WorkArea
from room_art import LAYER_ORDER, RoomLayerAtlas, StorybookRoomArt

APP = QApplication.instance() or QApplication(["immersive-room-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("immersive-room-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def advance(room, seconds):
    for _ in range(round(seconds * 60)):
        room.advance_scene(1 / 60)


def mapped_rect(widget, parent):
    return QRectF(widget.mapTo(parent, QPoint()), widget.size())


class ImmersiveDashboardTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel(PetData(coins=10000, affection_level=30))
        self.panel = DashboardWindow(self.model)
        self.panel.resize(1240, 800)
        self.panel.show()
        APP.processEvents()
        self.panel.preview_timer.stop()
        self.panel.room._animation_timer.stop()
        self.panel.room.life.wait = 1000
        self.panel.accessory_requested.connect(self.model.equip_accessory)
        self.panel.furniture_requested.connect(self.model.equip_furniture)
        self.panel.offset_requested.connect(self.model.set_accessory_offset)

    def tearDown(self):
        self.panel.stop()
        self.panel.close()
        self.panel.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_home_room_reaches_every_viewport_edge_at_multiple_sizes(self):
        for size in ((820, 650), (1240, 800), (1600, 900)):
            with self.subTest(size=size):
                self.panel.resize(*size)
                self.panel.show_section("home", animate=False)
                APP.processEvents()
                viewport = self.panel.home_scroll.viewport()
                self.assertEqual(mapped_rect(self.panel.room, viewport), QRectF(viewport.rect()))
                self.assertTrue(self.panel.drawer.isHidden())
                self.assertEqual(self.panel.home_scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(self.panel.home_scroll.verticalScrollBar().maximum(), 0)

    def test_room_corners_are_painted_instead_of_cut_to_an_outer_frame(self):
        image = self.panel.room.grab().toImage()
        for point in (QPoint(0, 0), QPoint(image.width() - 1, 0),
                      QPoint(0, image.height() - 1), image.rect().bottomRight()):
            self.assertEqual(image.pixelColor(point).alpha(), 255, point)

    def test_feeding_controls_are_transparent_children_over_the_foreground(self):
        shelf = self.panel.feeding_shelf
        self.assertIs(shelf.parentWidget(), self.panel.room)
        self.assertEqual(shelf.frameShape(), QFrame.Shape.NoFrame)
        self.assertFalse(shelf.autoFillBackground())
        self.assertTrue(self.panel.room.rect().contains(shelf.geometry()))
        self.assertIs(self.panel.dock.parentWidget(), self.panel.room)
        self.assertFalse(self.panel.dock.autoFillBackground())
        self.assertFalse(shelf.geometry().intersects(self.panel.dock.geometry()))

    def test_five_badges_stay_compact_and_do_not_stretch_across_the_window(self):
        self.assertEqual(set(self.panel.nav_buttons), {"home", "bag", "shop", "achievements", "settings"})
        total_width = sum(button.width() for button in self.panel.nav_buttons.values())
        self.assertLess(total_width, self.panel.room.width() * .5)
        for button in self.panel.nav_buttons.values():
            self.assertLessEqual(button.width(), 80)
            self.assertLessEqual(button.height(), 90)
            self.assertGreaterEqual(button.iconSize().width(), 32)
            self.assertFalse(button.icon().isNull())
            self.assertTrue(self.panel.room.rect().contains(mapped_rect(button, self.panel.room).toRect()))

    def test_badge_hover_rises_then_returns_without_moving_the_click_target(self):
        button = self.panel.nav_buttons["shop"]
        before = button.geometry()
        APP.sendEvent(button, QEnterEvent(QPointF(8, 8), QPointF(8, 8),
                                          QPointF(button.mapToGlobal(QPoint(8, 8)))))
        button.hover_animation.setCurrentTime(button.hover_animation.duration())
        self.assertGreater(button.property("hover_lift"), 0)
        self.assertLessEqual(button.property("hover_lift"), 6)
        self.assertEqual(button.geometry(), before)
        APP.sendEvent(button, QEvent(QEvent.Type.Leave))
        button.hover_animation.setCurrentTime(button.hover_animation.duration())
        self.assertAlmostEqual(button.property("hover_lift"), 0)
        self.assertEqual(button.geometry(), before)

    def test_every_drawer_keeps_the_pet_and_foreground_controls_inside_the_room(self):
        for size in ((820, 650), (1240, 800), (1600, 900)):
            self.panel.resize(*size)
            for section in ("bag", "shop", "dress", "furniture", "achievements", "settings"):
                with self.subTest(size=size, section=section):
                    self.panel.show_section(section, animate=False)
                    APP.processEvents()
                    room = self.panel.room
                    self.assertTrue(room.isVisible())
                    self.assertTrue(self.panel.drawer.isVisible())
                    self.assertFalse(self.panel.drawer.isWindow())
                    self.assertTrue(QRectF(room.rect()).contains(room.pet_bounds()))
                    self.assertTrue(room.rect().contains(room.pet_center().toPoint()))
                    self.assertFalse(room.geometry().intersects(self.panel.drawer.geometry()))
                    for widget in (self.panel.feeding_shelf, self.panel.dock):
                        self.assertTrue(room.rect().contains(widget.geometry()), widget.objectName())

    def test_foreground_food_click_consumes_once_and_keeps_food_zero_exp(self):
        self.model.set_hunger(20)
        self.assertTrue(self.model.buy_item("sesame"))
        self.panel.refresh()
        previous = self.model.snapshot()
        presentations = []
        self.model.presentation_requested.connect(presentations.append)
        self.panel.feeding_buttons["sesame"].click()
        self.assertEqual(self.model.data.hunger, 55)
        self.assertEqual(self.model.data.inventory["sesame"], 0)
        self.assertEqual(self.model.data.affection_exp, previous["affection_exp"])
        self.assertEqual(self.model.data.coins, previous["coins"])
        self.assertEqual(len(presentations), 1)
        settled = self.model.snapshot()
        advance(self.panel.room, 3)
        self.assertEqual(self.model.snapshot(), settled)

    def test_equipping_and_decorating_from_drawers_updates_the_visible_pet(self):
        self.panel.show_section("dress", animate=False)
        self.panel.dress_tabs.setCurrentIndex(1)
        self.panel.head_combo.buttons[self.panel.head_combo.findData("crown")].click()
        self.panel.offset_slider.setValue(17)
        self.assertEqual(self.model.data.accessories["head"], "crown")
        self.assertEqual(self.panel._home_renderer.accessories["offset_y"], 17)
        self.assertTrue(self.model.buy_furniture("sakura_room"))
        self.panel.show_section("furniture", animate=False)
        self.panel.furniture_buttons["sakura_room"].click()
        self.assertEqual(self.panel.room._slot("theme"), "sakura_room")
        self.assertTrue(self.panel.room.isVisible())
        self.assertTrue(self.panel.drawer.isVisible())


class ImmersiveSceneTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        self.engine.set_pinned(True)
        self.renderer = SkinRenderer(ROOT / "assets/skins/default")
        self.room = IllustratedRoomCanvas(self.engine, lambda: self.renderer)
        self.room.resize(1200, 800)
        self.room.show()
        self.room._animation_timer.stop()
        self.room.life.wait = 1000
        self.desktop = self.engine.x, self.engine.y
        APP.processEvents()

    def tearDown(self):
        self.room.stop()
        self.room.close()
        self.room.deleteLater()
        self.renderer.stop()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def assert_resting_anchor(self):
        actual = self.room._pet_transform().map(self.room._render_foot() + self.room._view().visual_offset)
        expected = self.room._base_foot()
        self.assertAlmostEqual(actual.x(), expected.x(), places=4)
        self.assertAlmostEqual(actual.y(), expected.y(), places=4)
        self.assertEqual((self.engine.x, self.engine.y), self.desktop)

    def test_viewport_resize_and_scene_zoom_preserve_actual_resting_foot(self):
        for width, height in ((760, 420), (1200, 800), (1600, 900)):
            self.room.resize(width, height)
            for scale in (.6, 1, 1.5):
                self.engine.skin_scale = scale
                self.engine.set_buff({"scale": 1.2, "remaining_seconds": 60})
                self.renderer.set_accessories({"head": "crown", "offset_y": -30})
                self.room.grab()
                self.assert_resting_anchor()

    def test_gift_finish_and_interrupt_settle_on_the_visible_rug(self):
        for gift in ("spinning_top", "flower_bouquet", "summit_pickaxe", "drama_clapper"):
            with self.subTest(gift=gift):
                self.room.life.x = .66
                self.room.performance = GiftPerformance(gift, start_x=.66)
                advance(self.room, 2)
                self.room.record_interaction("poke")
                advance(self.room, 6)
                self.assertIsNone(self.room.performance)
                self.assertEqual(self.room._gift_queue, [])
                self.assert_resting_anchor()

    def test_screen_roll_and_flip_return_to_rug_in_the_new_projection(self):
        for trick in ("screen_roll", "flip"):
            self.room.life.x = .60
            self.engine.perform_trick(trick)
            self.room.begin_trick(trick)
            self.engine.advance(13)
            self.room.advance_scene(.02)
            advance(self.room, 6)
            self.assert_resting_anchor()

    def test_lamp_click_uses_its_drawn_placement_and_never_pokes_the_pet(self):
        self.room.set_home_state({"equipped_furniture": {"corner": "warm_lamp", "wall": "sunflower_painting"}})
        toggles, pokes = [], []
        self.room.lamp_toggle_requested.connect(lambda: toggles.append(True))
        self.room.poke_requested.connect(lambda: pokes.append(True))
        area = self.room.lamp_rect()
        self.assertFalse(area.isEmpty())
        self.assertTrue(QRectF(self.room.rect()).contains(area))
        self.assertFalse(area.contains(self.room.pet_center()))
        QTest.mouseClick(self.room, Qt.MouseButton.LeftButton, pos=area.center().toPoint())
        self.assertEqual(toggles, [True])
        self.assertEqual(pokes, [])

    def test_corner_lamp_and_wall_picture_have_separate_rendered_areas(self):
        self.room.set_home_state({"equipped_furniture": {"corner": "warm_lamp", "wall": "sunflower_painting"}})
        for size in ((760, 420), (1200, 800), (1600, 900)):
            self.room.resize(*size)
            scale, width, height = self.room._geometry()
            picture = self.room._wall_art_rect(width, height)
            actual_picture = QRectF(picture.x() * scale, picture.y() * scale,
                                    picture.width() * scale, picture.height() * scale)
            self.assertFalse(self.room.lamp_rect().intersects(actual_picture), size)

    def test_day_night_and_lamp_light_are_visibly_distinct_without_mutating_state(self):
        self.room.set_home_state({"equipped_furniture": {"corner": "warm_lamp"}, "lamp_on": False})
        original = dict(self.room._home)
        self.room.daytime_override = True
        day = self.room.grab().toImage()
        self.room.daytime_override = False
        night = self.room.grab().toImage()
        self.assertNotEqual(bytes(day.constBits()), bytes(night.constBits()))
        self.assertEqual(self.room._home, original)
        self.room.set_home_state({**original, "lamp_on": True})
        lamp = self.room.grab().toImage()
        self.assertNotEqual(bytes(night.constBits()), bytes(lamp.constBits()))
        self.assertTrue(day.save(str(ART / "room-day.png")))
        self.assertTrue(night.save(str(ART / "room-night.png")))
        self.assertTrue(lamp.save(str(ART / "room-lamp.png")))
        self.assertEqual((self.engine.x, self.engine.y), self.desktop)


class ArtistLayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = ART / self._testMethodName
        self.directory.mkdir(exist_ok=False)
        self.atlas = RoomLayerAtlas(self.directory)

    def make_png(self, key, size=(80, 40), color=QColor(205, 84, 119, 123)):
        image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(color)
        path = self.directory / (key + ".png")
        self.assertTrue(image.save(str(path)))
        return path

    def test_floor_planks_converge_in_depth_and_leave_a_real_left_wall(self):
        for width, height in ((760, 420), (1240, 800), (1600, 900)):
            geometry = StorybookRoomArt.floor_geometry(width, height)
            self.assertGreaterEqual(geometry["corner"] / width, .20)
            self.assertLessEqual(geometry["corner"] / width, .24)
            vanishing = geometry["vanishing"]
            self.assertLess(vanishing.y(), geometry["floor"])
            edges = geometry["edges"]
            self.assertGreater(len(edges), 8)
            top_gap = edges[1][0].x() - edges[0][0].x()
            front_gap = edges[1][1].x() - edges[0][1].x()
            self.assertGreater(front_gap, top_gap * 1.5)
            for rear, front in edges:
                self.assertAlmostEqual(rear.y(), geometry["floor"])
                self.assertAlmostEqual(front.y(), height)
                to_front, to_rear = front - vanishing, rear - vanishing
                cross = to_front.x() * to_rear.y() - to_front.y() * to_rear.x()
                self.assertAlmostEqual(cross / (width * height), 0, places=10)

    def test_window_reveals_and_projecting_sill_have_depth_around_clear_glass(self):
        art = StorybookRoomArt(self.directory)
        image = QImage(400, 320, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            art.window_frame(painter, QRectF(100, 80, 150, 160), "#bf9872")
        finally:
            painter.end()
        self.assertGreater(image.pixelColor(90, 150).alpha(), 150)
        self.assertGreater(image.pixelColor(150, 70).alpha(), 150)
        self.assertGreater(image.pixelColor(140, 260).alpha(), 150)
        # The frame's soft contact shadow may feather into the glass opening;
        # it must remain clear enough to reveal the separately painted outdoors.
        self.assertLess(image.pixelColor(125, 120).alpha(), 20)
        self.assertNotEqual(image.pixelColor(90, 150), image.pixelColor(257, 150))

    def test_artist_png_is_used_with_its_alpha_and_never_rewritten(self):
        source = self.make_png("cloud_cushion")
        original = source.read_bytes()
        image = self.atlas.pixmap("cloud_cushion")
        self.assertIsNotNone(image)
        self.assertEqual(image.size().width(), 80)
        self.assertEqual(image.toImage().pixelColor(30, 20).alpha(), 123)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(set(self.directory.iterdir()), {source})

    def test_fitting_keeps_aspect_ratio_and_transparent_padding(self):
        self.make_png("wood_bowl", size=(80, 40), color=QColor(28, 153, 98, 140))
        image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            self.assertTrue(self.atlas.paint(painter, "wood_bowl", QRectF(0, 0, 100, 100)))
        finally:
            painter.end()
        self.assertEqual(image.pixelColor(50, 10).alpha(), 0)
        self.assertAlmostEqual(image.pixelColor(50, 50).alpha(), 140, delta=1)
        self.assertEqual(image.pixelColor(50, 90).alpha(), 0)

    def test_large_artist_texture_is_scaled_before_use_and_keeps_source_bytes(self):
        source = self.make_png("sakura_room", size=(6000, 80))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        image = self.atlas.pixmap("sakura_room")
        self.assertIsNotNone(image)
        self.assertLessEqual(max(image.width(), image.height()), 4096)
        self.assertAlmostEqual(image.width() / image.height(), 75, delta=2)
        self.assertEqual(image.toImage().pixelColor(image.width() // 2, image.height() // 2).alpha(), 123)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_corrupt_and_missing_layers_decline_without_writing_replacements(self):
        source = self.directory / "warm_lamp.png"
        source.write_bytes(b"This is an artist file that is not a PNG.")
        original = source.read_bytes()
        self.assertIsNone(self.atlas.pixmap("warm_lamp"))
        self.assertIsNone(self.atlas.pixmap("missing"))
        image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            self.assertFalse(self.atlas.paint(painter, "warm_lamp", QRectF(0, 0, 100, 100)))
        finally:
            painter.end()
        self.assertFalse(any(bytes(image.constBits())))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(set(self.directory.iterdir()), {source})

    def test_path_traversal_and_absolute_or_non_png_keys_are_rejected(self):
        self.make_png("allowed")
        for key in ("../allowed", "..\\allowed", "allowed.png", "C:\\allowed", "/allowed", "a/b", "", None):
            with self.subTest(key=key):
                self.assertIsNone(self.atlas.pixmap(key))
        self.assertIsNotNone(self.atlas.pixmap("allowed"))

    def test_file_and_pixel_budgets_are_checked_before_decode(self):
        oversized = self.directory / "oversized.png"
        with oversized.open("xb") as output:
            output.write(b"too-large-png")
            output.seek(RoomLayerAtlas.MAX_FILE)
            output.write(b"x")
        self.assertIsNone(self.atlas.pixmap("oversized"))
        # A valid PNG header advertises an unsafe texture. It must never be
        # allocated merely because the compressed payload is small.
        source = self.make_png("pixel_bomb", size=(1, 1))
        raw = bytearray(source.read_bytes())
        raw[16:24] = struct.pack(">II", 10000, 10000)
        raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]) & 0xffffffff)
        source.write_bytes(raw)
        self.assertIsNone(self.atlas.pixmap("pixel_bomb"))

    def test_cache_detects_an_artist_edit_in_the_same_running_process(self):
        self.make_png("rice_clock", color=QColor("#c63d48"))
        first = self.atlas.pixmap("rice_clock").toImage()
        self.make_png("rice_clock", size=(64, 32), color=QColor("#3b925e"))
        second = self.atlas.pixmap("rice_clock").toImage()
        self.assertNotEqual(first.pixelColor(20, 20), second.pixelColor(20, 20))
        self.assertEqual(second.width(), 64)

    def test_theme_layer_prefers_the_named_local_png_over_vector_fallback(self):
        self.make_png("cheese_room__walls_floor", size=(40, 40), color=QColor("#993f7c"))
        art = StorybookRoomArt(self.directory)
        image = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            used = art.layer(painter, "cheese_room", "walls_floor", QRectF(0, 0, 200, 100))
        finally:
            painter.end()
        self.assertTrue(used)
        self.assertEqual(image.pixelColor(100, 50).name(), "#993f7c")
        self.assertEqual(image.pixelColor(0, 0).alpha(), 255)

    def test_missing_artist_layers_still_produce_a_complete_vector_room(self):
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(engine, lambda: renderer)
        room._art = StorybookRoomArt(self.directory)
        room.resize(1000, 700)
        room._animation_timer.stop()
        try:
            image = room.grab().toImage()
            self.assertFalse(image.isNull())
            self.assertEqual(image.pixelColor(2, 350).alpha(), 255)
            self.assertNotEqual(image.pixelColor(500, 160), image.pixelColor(500, 630))
            self.assertEqual(list(self.directory.iterdir()), [])
        finally:
            room.stop()
            room.deleteLater()
            renderer.stop()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_scene_consumes_theme_and_furniture_png_without_replacing_pet_state(self):
        theme = self.make_png("cheese_room", color=QColor("#7455ca"))
        lamp = self.make_png("warm_lamp", color=QColor("#32d05f"))
        original = {p: p.read_bytes() for p in (theme, lamp)}
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        engine.set_pinned(True)
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(engine, lambda: renderer)
        room._art = StorybookRoomArt(self.directory)
        room.resize(1200, 800)
        room.daytime_override = True
        room.set_home_state({"equipped_furniture": {"corner": "warm_lamp"}, "lamp_on": False})
        room._animation_timer.stop()
        before = engine.elapsed, engine.x, engine.y, engine.state, engine.pose
        try:
            image = room.grab().toImage()
            background = image.pixelColor(600, 250)
            self.assertGreater(background.blue(), background.red() + 35)
            marker = image.pixelColor(room.lamp_rect().center().toPoint())
            self.assertGreater(marker.green(), marker.red() + 70)
            self.assertGreater(marker.green(), marker.blue() + 70)
            self.assertTrue(room._hit_pet(room.pet_center()))
            self.assertEqual((engine.elapsed, engine.x, engine.y, engine.state, engine.pose), before)
            self.assertEqual({p: p.read_bytes() for p in (theme, lamp)}, original)
            self.assertTrue(image.save(str(self.directory / "artist-overrides.png")))
        finally:
            room.stop()
            room.deleteLater()
            renderer.stop()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_clicking_the_actually_rendered_training_dummy_starts_its_interaction(self):
        self.make_png("training_dummy", size=(80, 80), color=QColor("#00ff00"))
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        engine.set_pinned(True)
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(engine, lambda: renderer)
        room._art = StorybookRoomArt(self.directory)
        room.resize(1200, 800)
        room.daytime_override = True
        room.set_home_state({"equipped_furniture": {"corner": "training_dummy"}})
        room.show()
        room._animation_timer.stop()
        APP.processEvents()
        desktop = engine.x, engine.y
        try:
            image = room.grab().toImage()
            pixels = [QPoint(x, y) for y in range(0, image.height(), 6)
                      for x in range(0, image.width(), 6)
                      if image.pixelColor(x, y).green() > image.pixelColor(x, y).red() + 150
                      and image.pixelColor(x, y).green() > image.pixelColor(x, y).blue() + 150]
            self.assertGreater(len(pixels), 30)
            center = QPoint((min(p.x() for p in pixels) + max(p.x() for p in pixels)) // 2,
                            (min(p.y() for p in pixels) + max(p.y() for p in pixels)) // 2)
            QTest.mouseClick(room, Qt.MouseButton.LeftButton, pos=center)
            self.assertIsNotNone(room.performance)
            self.assertEqual(room.performance.item_id, "training_dummy")
            self.assertEqual((engine.x, engine.y), desktop)
        finally:
            room.stop()
            room.close()
            room.deleteLater()
            renderer.stop()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_paper_texture_is_subtle_deterministic_and_reused_between_frames(self):
        art = StorybookRoomArt(self.directory)
        self.assertEqual(LAYER_ORDER, ("outdoors", "walls_floor", "back_furniture", "lighting",
                                      "middle_furniture", "pet", "foreground"))
        before_key = art.paper.cacheKey()
        before_image = art.paper.toImage()
        self.assertLessEqual(max(before_image.pixelColor(x, y).alpha()
                                 for y in range(0, 128, 7) for x in range(0, 128, 7)), 14)
        second = StorybookRoomArt(self.directory).paper.toImage()
        self.assertEqual(bytes(before_image.constBits()), bytes(second.constBits()))
        palette = IllustratedRoomCanvas.THEMES["cheese_room"]
        image = QImage(500, 400, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            for _ in range(2):
                art.architecture(painter, 500, 400, palette, "cheese_room", QRectF(330, 80, 130, 140))
        finally:
            painter.end()
        self.assertEqual(art.paper.cacheKey(), before_key)
        self.assertEqual(bytes(art.paper.toImage().constBits()), bytes(before_image.constBits()))

    def test_every_equippable_furniture_id_accepts_its_own_artist_layer(self):
        class TrackingAtlas(RoomLayerAtlas):
            def __init__(self, directory):
                super().__init__(directory)
                self.used = []

            def paint(self, painter, key, rect, *, stretch=False):
                used = super().paint(painter, key, rect, stretch=stretch)
                if used:
                    self.used.append(key)
                return used

        catalog = Catalog.load()
        for key in catalog.furniture:
            self.make_png(key, color=QColor("#9b6ec2"))
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        engine.set_pinned(True)
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(engine, lambda: renderer)
        room._art = StorybookRoomArt(self.directory)
        room._art.layers = TrackingAtlas(self.directory)
        room.resize(1200, 800)
        room._animation_timer.stop()
        try:
            for key, definition in catalog.furniture.items():
                with self.subTest(furniture=key):
                    room.set_home_state({"equipped_furniture": {definition["slot"]: key}})
                    room._art.layers.used.clear()
                    self.assertFalse(room.grab().isNull())
                    self.assertIn(key, room._art.layers.used)
        finally:
            room.stop()
            room.deleteLater()
            renderer.stop()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_new_and_updated_artist_png_override_an_already_warm_vector_cache(self):
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        engine.set_pinned(True)
        renderer = SkinRenderer(ROOT / "assets/skins/default")
        room = IllustratedRoomCanvas(engine, lambda: renderer)
        room._art = StorybookRoomArt(self.directory)
        room.resize(1200, 800)
        room._animation_timer.stop()
        before = engine.x, engine.y, engine.elapsed
        scale, width, height = room._geometry()
        marker = QPointF(width * .84, room._base_foot().y() - 16).toPoint()

        def draw_table():
            image = QImage(1200, 800, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                room._paint_bowl(painter, width, height)
            finally:
                painter.end()
            return image

        try:
            vector = draw_table()
            self.assertTrue(room._art._sprite_cache)
            source = self.make_png("wood_bowl", color=QColor("#32d05f"))
            first_bytes = source.read_bytes()
            first = draw_table()
            self.assertNotEqual(vector.pixelColor(marker), first.pixelColor(marker))
            self.assertEqual(first.pixelColor(marker).name(), "#32d05f")
            self.assertEqual(source.read_bytes(), first_bytes)
            self.make_png("wood_bowl", size=(64, 32), color=QColor("#c74bc1"))
            second_bytes = source.read_bytes()
            second = draw_table()
            self.assertEqual(second.pixelColor(marker).name(), "#c74bc1")
            self.assertEqual(source.read_bytes(), second_bytes)
            self.assertEqual((engine.x, engine.y, engine.elapsed), before)
        finally:
            room.stop()
            room.deleteLater()
            renderer.stop()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_vector_cache_stays_bounded_across_food_lamp_and_resolution_variants(self):
        art = StorybookRoomArt(self.directory)
        paper_key = art.paper.cacheKey()
        image = QImage(1000, 800, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            for index in range(48):
                art.tea_table(painter, 120 + index, 220, bool(index % 2),
                              QColor.fromHsv(index * 7 % 360, 100, 180).name())
                art.lamp(painter, 100, 300, bool(index % 2))
                self.assertLessEqual(len(art._sprite_cache), 32)
                self.assertLessEqual(art._sprite_pixels, 16_000_000)
            # High-DPI lighting surfaces exercise the pixel budget independently
            # of the small-sprite count budget.
            painter.scale(3, 3)
            for index in range(3):
                art.ambience(painter, 1000, 800, QRectF(690, 130, 180, 170),
                             bool(index % 2), index, (200 + index, 450))
                self.assertLessEqual(len(art._sprite_cache), 32)
                self.assertLessEqual(art._sprite_pixels, 16_000_000)
                self.assertEqual(art._sprite_pixels, sum(pm.width() * pm.height()
                                                        for pm in art._sprite_cache.values()))
        finally:
            painter.end()
        self.assertEqual(art.paper.cacheKey(), paper_key)

    def test_live_clock_changes_pixels_without_allocating_a_sprite_for_each_tick(self):
        art = StorybookRoomArt(self.directory)
        paper_key = art.paper.cacheKey()

        def frame(moment):
            image = QImage(240, 220, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                art.wall_decoration(painter, QRectF(45, 35, 140, 140), "rice_clock",
                                    RoomCanvas.clock_angles(moment))
            finally:
                painter.end()
            return image

        first = frame(datetime(2026, 10, 23, 3, 15, 0))
        cache_size = len(art._sprite_cache)
        later = frame(datetime(2026, 10, 23, 3, 15, 20))
        self.assertNotEqual(bytes(first.constBits()), bytes(later.constBits()))
        for second in range(30):
            frame(datetime(2026, 10, 23, 3, 15, second))
        self.assertEqual(len(art._sprite_cache), cache_size)
        self.assertEqual(art.paper.cacheKey(), paper_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
