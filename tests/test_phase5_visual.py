"""Illustrated game UI, PNG replacement, room layout and shared interactions."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from illustrated_assets import IconAtlas, ICON_IDS, _EMOJI, plain_text
from home_scene import IllustratedRoomCanvas
from dashboard import DashboardWindow, IconTile, IconChoice
from main import PetApplication
from models import PetData, PetModel
from pet_engine import PetEngine, SkinRenderer, WorkArea

APP = QApplication.instance() or QApplication(["illustrated-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("illustrated-unit-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


class ArtworkTests(unittest.TestCase):
    def test_all_shipped_icons_are_80px_transparent_real_pngs(self):
        hashes = set()
        for key in ICON_IDS:
            file = ROOT / "assets/item_icons" / (key + ".png")
            image = QImage(str(file))
            self.assertEqual((image.width(), image.height()), (80, 80), key)
            self.assertTrue(image.hasAlphaChannel(), key)
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0, key)
            hashes.add(hashlib.sha256(file.read_bytes()).hexdigest())
        self.assertGreaterEqual(len(hashes), len(ICON_IDS) - 4)

    def test_existing_artist_png_is_preferred_and_never_overwritten(self):
        folder = ART / "artist"; folder.mkdir()
        file = folder / "water.png"
        image = QImage(80, 80, QImage.Format.Format_ARGB32); image.fill(QColor("#4b79c9")); self.assertTrue(image.save(str(file)))
        before = file.read_bytes(); atlas = IconAtlas(folder)
        self.assertEqual(atlas.pixmap("water").toImage().pixelColor(40, 40), QColor("#4b79c9"))
        self.assertEqual(file.read_bytes(), before)
        self.assertFalse(atlas.pixmap("sugar").isNull()); self.assertTrue((folder / "sugar.png").exists())
        self.assertEqual(file.read_bytes(), before)

    def test_bad_existing_icon_uses_vector_without_modifying_artist_file(self):
        folder = ART / "bad-artist"; folder.mkdir(); file = folder / "crown.png"; file.write_bytes(b"not a png")
        atlas = IconAtlas(folder); self.assertFalse(atlas.pixmap("crown").isNull()); self.assertEqual(file.read_bytes(), b"not a png")

    def test_path_traversal_id_cannot_create_a_file_outside_atlas(self):
        folder = ART / "safe"; atlas = IconAtlas(folder)
        self.assertFalse(atlas.pixmap("../escape").isNull())
        self.assertFalse((ART / "escape.png").exists())

    def test_plain_text_removes_emoji_without_interpreting_markup(self):
        self.assertEqual(plain_text("<b>皇冠</b>\U0001f451\ufe0f"), "<b>皇冠</b>")
        self.assertEqual(plain_text("好感 +5 / 饱食 80"), "好感 +5 / 饱食 80")

    def test_current_catalog_has_no_unicode_emoji(self):
        text = (ROOT / "config/catalog.json").read_text(encoding="utf-8")
        self.assertIsNone(_EMOJI.search(text))


class IllustratedUI(unittest.TestCase):
    def setUp(self):
        self.panel = DashboardWindow(PetModel(PetData(coins=5000, affection_level=6)))
        self.panel.summon(); QTest.qWait(20)
    def tearDown(self):
        self.panel.stop(); self.panel.close(); self.panel.deleteLater(); APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_first_view_is_large_room_with_floating_game_hud(self):
        self.assertEqual(self.panel.current_section, "home")
        self.assertTrue(self.panel.room.isVisible()); self.assertGreaterEqual(self.panel.room.height(), 420)
        self.assertIs(self.panel.hud.parentWidget(), self.panel.room)
        self.assertTrue(self.panel.drawer.isHidden())
        self.assertGreater(self.panel.room.pet_bounds().width(), 120)

    def test_no_combo_boxes_or_checkboxes_exist_in_any_dashboard_page(self):
        self.assertEqual(self.panel.findChildren(QComboBox), [])
        self.assertEqual(self.panel.findChildren(QCheckBox), [])
        self.assertIsInstance(self.panel.head_combo, IconChoice)
        self.assertIsInstance(self.panel.face_check, IconTile)

    def test_all_five_navigation_entries_are_large_pixmap_buttons(self):
        self.assertEqual(set(self.panel.nav_buttons), {"home", "bag", "shop", "achievements", "settings"})
        for button in self.panel.nav_buttons.values():
            self.assertFalse(button.icon().isNull()); self.assertEqual(button.iconSize().width(), 36)
            self.assertGreaterEqual(button.height(), 60)

    def test_every_book_opens_without_squeezing_room_or_clipping_page(self):
        before = self.panel.room.height()
        for section in ("shop", "bag", "dress", "furniture", "achievements", "settings"):
            self.panel.show_section(section, animate=False); APP.processEvents()
            self.assertEqual(self.panel.room.height(), before)
            self.assertTrue(self.panel.drawer.isVisible()); self.assertGreater(self.panel.drawer.height(), 450)
            self.assertFalse(self.panel.drawer.isWindow())
            self.assertTrue(self.panel.room.isVisible())
        self.panel.show_section("home", animate=False); self.assertTrue(self.panel.drawer.isHidden())

    def test_shop_has_separate_scrollable_food_gift_furniture_and_trick_galleries(self):
        self.panel.show_section("shop", animate=False)
        self.assertEqual(self.panel.market_tabs.count(), 4)
        self.assertEqual(self.panel.shop_tabs.count(), 2)
        for key, (buy, feed, _text) in self.panel.shop_buttons.items():
            self.assertIsNotNone(buy.parentWidget().findChild(QLabel, "itemArtwork"), key)
        self.assertIn("screen_roll", self.panel.shop_trick_buttons)

    def test_equip_via_visual_tile_updates_actual_model_and_badge(self):
        model = self.panel.model
        self.panel.accessory_requested.connect(model.equip_accessory)
        self.panel.show_section("dress", animate=False); self.panel.dress_tabs.setCurrentIndex(1)
        self.panel.head_combo.buttons[self.panel.head_combo.findData("crown")].click()
        self.assertEqual(model.data.accessories["head"], "crown")
        tile = self.panel.head_combo.buttons[2]
        self.assertTrue(tile.isChecked()); self.assertEqual(tile.badge, "已穿戴")
        self.assertFalse(tile.icon().isNull())

    def test_placed_furniture_card_has_highlight_and_correct_badge(self):
        model = self.panel.model; model.buy_furniture("cat_paw_rug")
        self.panel.furniture_requested.connect(model.equip_furniture)
        self.panel.furniture_buttons["cat_paw_rug"].click()
        self.assertEqual(model.data.equipped_furniture["rug"], "cat_paw_rug")
        self.assertTrue(self.panel.furniture_buttons["cat_paw_rug"].isChecked())
        self.assertEqual(self.panel.furniture_buttons["cat_paw_rug"].badge, "已布置")

    def test_visible_texts_have_no_emoji_even_if_save_name_contains_it(self):
        self.panel.model.data.name = "小团子\U0001f451"
        self.panel.refresh()
        for widget in self.panel.findChildren(QLabel) + self.panel.findChildren(QPushButton):
            self.assertIsNone(_EMOJI.search(widget.text()), widget.text())
        self.assertEqual(self.panel.model.data.name, "小团子\U0001f451")

    def test_summon_always_returns_to_room_after_a_previous_book(self):
        self.panel.show_section("shop", animate=False); self.panel.hide(); self.panel.summon()
        self.assertEqual(self.panel.current_section, "home"); self.assertTrue(self.panel.drawer.isHidden())
        self.assertTrue(self.panel.room.isVisible())

    def test_room_food_icon_flies_into_bowl_without_charging_twice(self):
        room = self.panel.room; room.show_food("strawberry")
        before = self.panel.model.snapshot()
        frames = []
        for delta in (.12, .28, .6):
            room.advance_scene(delta)
            pixmap = room.grab().toImage(); frames.append(bytes(pixmap.constBits()))
        self.assertTrue(frames[0] != frames[1]); self.assertTrue(frames[1] != frames[2])
        self.assertEqual(self.panel.model.snapshot(), before)

    def test_all_tricks_and_large_accessories_fit_below_hud_at_minimum_room_height(self):
        self.panel.preview_timer.stop()
        room, engine = self.panel.room, self.panel._home_engine
        self.panel._home_renderer.set_accessories({"head": "crown", "face": "sunglasses", "effect": "steam", "offset_y": -30})
        for width, height in ((760, 420), (1100, 650)):
            room.setFixedSize(width, height)
            for trick, duration in (("flip", 1.1), ("clone", 2.5), ("ball", 5), ("screen_roll", 12)):
                engine.reset(); engine.set_pinned(True)
                engine.set_buff({"item_id": "sesame", "scale": 1.2, "color": "#45424a", "remaining_seconds": 60})
                self.assertTrue(engine.perform_trick(trick))
                for step in range(31):
                    bounds = room.pet_bounds()
                    self.assertGreaterEqual(bounds.left(), -1, (width, trick, step))
                    self.assertLessEqual(bounds.right(), width + 1, (width, trick, step))
                    self.assertGreaterEqual(bounds.top(), 147, (width, trick, step))
                    self.assertLessEqual(bounds.bottom(), height + 1, (width, trick, step))
                    engine.advance(duration / 31)
                engine.cancel_trick()

    def test_home_render_does_not_move_or_advance_shared_engine(self):
        engine = self.panel._home_engine; self.panel.preview_timer.stop()
        before = engine.elapsed, engine.x, engine.y, engine.vx, engine.vy
        for _ in range(8): self.panel.room.grab()
        self.assertEqual((engine.elapsed, engine.x, engine.y, engine.vx, engine.vy), before)


if __name__ == "__main__": unittest.main(verbosity=2)
