"""V2 step 1: compact game HUD, responsive drawers and ambient rendering."""
from datetime import datetime
from pathlib import Path
import sys
import unittest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionFocusRect
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow, AdaptiveGrid, FocusFreeStyle
from home_scene import IllustratedRoomCanvas
from models import PetData, PetModel
from pet_engine import RoomCanvas
APP = QApplication.instance() or QApplication(["v2-step1-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))


class CompactHomeTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel(PetData(coins=5000, affection_level=6))
        self.panel = DashboardWindow(self.model)
        self.panel.show(); APP.processEvents()
        self.panel.preview_timer.stop(); self.panel.room._animation_timer.stop()
        self.panel.accessory_requested.connect(self.model.equip_accessory)
        self.panel.offset_requested.connect(self.model.set_accessory_offset)
        self.panel.furniture_requested.connect(self.model.equip_furniture)

    def tearDown(self):
        self.panel.stop(); self.panel.close(); self.panel.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_default_home_devotes_about_four_fifths_to_scene(self):
        p = self.panel
        ratio = p.room.width() * p.room.height() / (p.width() * p.height())
        self.assertGreaterEqual(ratio, .75); self.assertLessEqual(ratio, .83)
        self.assertTrue(p.drawer.isHidden())

    def test_wide_hud_is_separate_cards_with_clear_wall_between(self):
        p = self.panel
        self.assertLessEqual(p.hud_profile.width(), 340)
        self.assertLessEqual(p.hud_right.width(), 190)
        self.assertLess(p.hud_profile.geometry().right() + 200, p.hud_right.geometry().left())
        self.assertEqual(p.hud.objectName(), "floatingHud")
        self.assertGreater(p.room.pet_bounds().width(), 140)

    def test_narrow_hud_cards_and_controls_do_not_overlap(self):
        p = self.panel
        for width in (820, 1000, 1240):
            p.resize(width, 720); p.show_section("shop", animate=False); APP.processEvents()
            self.assertLess(p.hud_profile.geometry().right(), p.hud_right.geometry().left())
            self.assertLessEqual(p.hud_right.geometry().right(), p.hud.width())
            self.assertGreater(p.hud_hunger_bar.width(), 100)
            self.assertTrue(p.hud_right.isAncestorOf(p.overlay_button))

    def test_drawer_expands_and_closes_smoothly_inside_same_window(self):
        p = self.panel; p.show_section("shop")
        p.drawer_animation.setCurrentTime(90); APP.processEvents()
        self.assertGreater(p.drawer.width(), 1); self.assertLess(p.drawer.width(), p._drawer_target)
        self.assertTrue(p.room.isVisible()); self.assertFalse(p.drawer.isWindow())
        p.drawer_animation.setCurrentTime(220); APP.processEvents()
        self.assertEqual(p.drawer.width(), p._drawer_target)
        p.show_section("home"); p.drawer_animation.setCurrentTime(100)
        self.assertTrue(p.drawer.isVisible())
        p.drawer_animation.setCurrentTime(220); APP.processEvents(); self.assertTrue(p.drawer.isHidden())

    def test_rapid_navigation_does_not_hide_new_drawer_after_old_transition(self):
        p = self.panel; p.show_section("shop"); p.drawer_animation.setCurrentTime(50)
        p.show_section("home"); p.drawer_animation.setCurrentTime(60)
        p.show_section("dress"); p.drawer_animation.setCurrentTime(220); APP.processEvents()
        self.assertEqual(p.current_section, "bag"); self.assertTrue(p.drawer.isVisible())
        self.assertEqual(p.drawer.width(), p._drawer_target)

    def test_shop_reflows_three_columns_wide_two_columns_narrow(self):
        p = self.panel
        for width, columns in ((1240, 3), (820, 2)):
            p.resize(width, 760); p.show_section("shop", animate=False); APP.processEvents()
            page = p.shop_tabs.widget(0); grids = page.widget().findChildren(AdaptiveGrid)
            self.assertEqual(grids[0].columns, columns)
            for key in ("water", "sugar", "sesame"):
                for button in p.shop_buttons[key][:2]:
                    page.ensureWidgetVisible(button); APP.processEvents()
                    pos = button.mapTo(page.viewport(), QPoint())
                    self.assertTrue(page.viewport().rect().contains(pos))
                    self.assertTrue(page.viewport().rect().contains(pos + button.rect().bottomRight()), key)

    def test_sparse_inventory_packs_owned_cards_without_empty_holes(self):
        p = self.panel
        self.model.buy_item("chili"); self.model.buy_item("spinning_top")
        p.show_section("bag", animate=False); APP.processEvents()
        grid = p.inventory_grid
        visible = [w for w in grid.cards if w.property("gridVisible")]
        self.assertEqual(len(visible), 2)
        self.assertIs(grid.itemAtPosition(0, 0).widget(), visible[0])
        self.assertIs(grid.itemAtPosition(0, 1).widget(), visible[1])

    def test_equipping_and_offset_preview_stays_visible_in_drawer(self):
        p = self.panel; p.show_section("dress", animate=False); p.dress_tabs.setCurrentIndex(1)
        p.head_combo.buttons[p.head_combo.findData("crown")].click(); p.offset_slider.setValue(19)
        self.assertEqual(self.model.data.accessories["head"], "crown")
        self.assertEqual(self.model.data.accessories["offset_y"], 19)
        self.assertEqual(p._home_renderer.accessories["offset_y"], 19)
        self.assertTrue(p.room.isVisible())

    def test_decorating_the_room_is_immediately_visible_beside_drawer(self):
        p = self.panel; self.model.buy_furniture("sakura_room"); p.show_section("furniture", animate=False)
        p.furniture_buttons["sakura_room"].click()
        self.assertEqual(p.room._slot("theme"), "sakura_room")
        self.assertTrue(p.room.isVisible()); self.assertTrue(p.drawer.isVisible())

    def test_all_illustrated_dock_buttons_are_shallow(self):
        for button in self.panel.nav_buttons.values():
            self.assertEqual(button.height(), 62); self.assertFalse(button.icon().isNull())

    def test_native_focus_primitive_draws_no_dots_but_slider_keeps_keyboard(self):
        image = QImage(80, 40, QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image); option = QStyleOptionFocusRect(); option.rect = QRect(2, 2, 75, 35)
        style = FocusFreeStyle("fusion"); style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, option, painter)
        painter.end(); self.assertFalse(any(bytes(image.constBits())))
        p = self.panel; p.show_section("dress", animate=False); p.dress_tabs.setCurrentIndex(1)
        old = p.offset_slider.value(); p.offset_slider.setFocus(); QTest.keyClick(p.offset_slider, Qt.Key.Key_Right)
        self.assertEqual(p.offset_slider.value(), old + 1)

    def test_dev_day_night_preview_is_temporary_and_can_restore_system_time(self):
        p = self.panel; before = self.model.snapshot()
        p.set_phase4_context([], True); p.show_section("settings", animate=False)
        p.environment_buttons["night"].click(); self.assertIs(p.room.daytime_override, False)
        p.environment_buttons["day"].click(); self.assertIs(p.room.daytime_override, True)
        p.environment_buttons["auto"].click(); self.assertIsNone(p.room.daytime_override)
        self.assertEqual(self.model.snapshot(), before)
        self.assertTrue(p.environment_buttons["auto"].isChecked())

    def test_clock_is_drawn_at_current_time_in_equipped_room(self):
        p = self.panel; self.model.buy_furniture("rice_clock"); self.model.equip_furniture("wall", "rice_clock")
        self.assertEqual(p.room._slot("wall"), "rice_clock"); self.assertFalse(p.room.grab().isNull())


class EnvironmentTests(unittest.TestCase):
    def test_day_clouds_move_slowly_and_wrap_inside_clip_budget(self):
        first = IllustratedRoomCanvas.cloud_centers(0, 174)
        later = IllustratedRoomCanvas.cloud_centers(10, 174)
        self.assertNotEqual(first, later)
        self.assertLess(abs(first[0][0] - later[0][0]), 20)
        for time in (0, 100, 10000):
            for x, _y in IllustratedRoomCanvas.cloud_centers(time, 174):
                self.assertGreaterEqual(x, -33); self.assertLessEqual(x, 207)

    def test_starlight_fades_gently_without_flash(self):
        for index in range(7):
            values = [IllustratedRoomCanvas.star_opacity(index, t) for t in (0, 1, 2, 3)]
            self.assertGreaterEqual(min(values), .35); self.assertLessEqual(max(values), .81)
            self.assertNotEqual(values[0], values[-1])
            self.assertLess(abs(IllustratedRoomCanvas.star_opacity(index, 1.016) - values[1]), .004)

    def test_clock_angles_include_seconds_and_hour_carry(self):
        self.assertEqual(RoomCanvas.clock_angles(datetime(2026, 10, 22, 3, 15, 30)), (97.75, 93.0, 180.0))
        h, m, s = RoomCanvas.clock_angles(datetime(2026, 10, 22, 12, 0, 0, 500000))
        self.assertAlmostEqual(h, 1 / 240); self.assertAlmostEqual(m, .05); self.assertEqual(s, 3)
        self.assertEqual(RoomCanvas.clock_angles(datetime(2026, 10, 23)), (0, 0, 0))

    def test_night_tone_changes_the_foreground_and_lamp_adds_warmth(self):
        panel = DashboardWindow(PetModel()); panel.preview_timer.stop(); room = panel.room
        def color(day, on):
            room.daytime_override = day
            room.set_home_state({"equipped_furniture": {"corner": "warm_lamp"}, "lamp_on": on})
            image = QImage(960, 500, QImage.Format.Format_ARGB32); image.fill(QColor("#fff8ec"))
            p = QPainter(image); room._paint_ambient(p, 960, 500); p.end()
            return image.pixelColor(170, 300)
        day, night, lamp = color(True, False), color(False, False), color(False, True)
        self.assertLess(night.lightness(), day.lightness()); self.assertGreater(lamp.red(), night.red())
        panel.stop(); panel.close(); panel.deleteLater(); APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__": unittest.main(verbosity=2)
