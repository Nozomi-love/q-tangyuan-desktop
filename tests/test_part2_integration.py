"""Part 2 through real controls, controller signals and final painted feet."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QTabWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PetApplication
from models import PetData
from pet_engine import WorkArea
from save_manager import SaveManager

APP = QApplication.instance() or QApplication(["part2-integration"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part2-integration-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)
CONSUMABLES = ("gnar_workbook", "practice_hourglass", "fist_bump_glove", "postmatch_noodles", "late_practice_snack")


class PartTwoIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work = ART / self._testMethodName
        self.work.mkdir()
        self.controllers = []
        self.c = self.make_controller(dev_mode=True)
        self.m, self.e, self.r, self.p = self.c.model, self.c.window.engine, self.c.dashboard.room, self.c.dashboard
        self.m.replace_data(PetData(coins=0, hunger=20, affection_level=6, muted=True))
        self.e.set_work_area(WorkArea(0, 0, 1600, 1000))
        self.c.window.set_pinned(True)
        self.e.place(700, 760)
        self.r.life.wait = 1000
        APP.processEvents()
        self.freeze(self.c)

    def make_controller(self, *, dev_mode):
        c = PetApplication(APP, save_path=self.work / "save_data.json", skins_root=self.work / "skins", dev_mode=dev_mode)
        self.controllers.append(c)
        c.dashboard.resize(1240, 800)
        APP.processEvents()
        self.freeze(c)
        return c

    @staticmethod
    def freeze(c):
        for owner in (c.window, c.dashboard):
            for timer in owner.findChildren(QTimer):
                timer.stop()

    def tearDown(self):
        for c in self.controllers:
            c.stop()
            c.dashboard.deleteLater()
            c.window.deleteLater()
            c.tray.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def advance(self, seconds):
        for _ in range(round(seconds * 60)):
            self.e.advance(1 / 60)
            self.r.advance_scene(1 / 60)

    def foot(self):
        return self.r._pet_transform().map(self.r._render_foot() + self.r._view().visual_offset)

    def resources(self):
        d = self.m.data
        return (d.coins, self.m._lifetime_exp(), d.hunger, d.stats["total_clicks"],
                d.stats["total_feeds"], d.stats["total_presents"])

    def click(self, button, *, section="shop"):
        self.p.show_section(section, animate=False)
        ancestors, parent = [], button.parentWidget()
        while parent is not None:
            ancestors.append(parent)
            parent = parent.parentWidget()
        for parent in reversed(ancestors):
            if isinstance(parent, QTabWidget):
                for index in range(parent.count()):
                    page = parent.widget(index)
                    if page is button or page.isAncestorOf(button):
                        parent.setCurrentIndex(index)
                        break
        APP.processEvents()
        for parent in ancestors:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(button, 6, 6)
        APP.processEvents()
        self.assertTrue(button.isVisible(), button.text())
        self.assertTrue(button.isEnabled(), button.text())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APP.processEvents()
        self.freeze(self.c)

    def clean(self):
        self.assertEqual(self.e.active_trick, "")
        self.assertEqual(self.m._active_trick_id, "")
        self.assertEqual(self.m.trick_busy, 0)
        self.assertIsNone(self.r.performance)
        self.assertEqual(self.r._food_id, "")
        self.assertEqual((self.r._food_queue, self.r._gift_queue), ([], []))
        self.assertEqual(self.r._last_toy, "")
        self.assertEqual(self.r.foreground_kind, "")
        self.assertIsNone(self.e.presentation.active)
        self.assertIsNone(self.r.presentation.active)

    def home(self):
        actual, target = self.foot(), self.r._base_foot()
        self.assertAlmostEqual(self.r.life.x, .48, places=5)
        self.assertAlmostEqual(actual.x(), target.x(), places=4)
        self.assertAlmostEqual(actual.y(), target.y(), places=4)

    def paint_layer(self, method, name):
        image = QImage(1100, 700, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            method(painter, 1100., 700.)
        finally:
            painter.end()
        self.assertTrue(image.save(str(self.work / (name + ".png"))))
        return hashlib.sha256(image.constBits().tobytes()).hexdigest()

    def test_all_ten_products_have_real_purchase_and_use_controls(self):
        for key in CONSUMABLES:
            self.assertIn(key, self.p.shop_buttons)
            self.click(self.p.shop_buttons[key][0])
            self.assertEqual(self.m.data.inventory[key], 1)
            self.click(self.p.inventory_widgets[key][2], section="bag")
            self.assertEqual(self.m.data.inventory[key], 0)
        for key, slot in (("seven_goggles", "face"), ("kiting_scarf", "back")):
            buy, wear = self.p.accessory_shop_buttons[key]
            self.click(buy)
            self.click(wear)
            self.assertEqual(self.m.effective_accessories()[slot], key)
        for key, slot in (("practice_room", "theme"), ("summit_wall", "wall")):
            self.click(self.p.furniture_shop_buttons[key])
            self.click(self.p.furniture_buttons[key], section="bag")
            self.assertEqual(self.m.data.equipped_furniture[slot], key)
        buy, perform, _ = self.p.shop_trick_buttons["reverse_flash"]
        self.click(buy)
        self.assertIn("reverse_flash", self.m.data.purchased_tricks)
        self.click(perform)
        self.assertEqual(self.e.active_trick, "reverse_flash")
        self.assertEqual(self.m.data.coins, 0)
        self.advance(11)
        self.clean()
        self.home()

    def test_fist_actual_mouse_and_unattended_paths_have_equal_single_rewards(self):
        outcomes = []
        for clicked in (True, False):
            before = self.resources()
            self.assertTrue(self.m.buy_item("fist_bump_glove", feed_now=True))
            settled = self.resources()
            self.advance(.7)
            perf = self.r.performance
            self.assertEqual(perf.item_id, "fist_bump_glove")
            if clicked:
                hit = self.r.fist_bump_rect()
                self.assertFalse(hit.isEmpty())
                QTest.mouseClick(self.r, Qt.MouseButton.LeftButton, pos=hit.center().toPoint())
                APP.processEvents()
                self.freeze(self.c)
                self.assertTrue(perf.fist_bumped)
                self.assertIs(self.r.performance, perf)
                self.assertTrue(self.r.fist_bump_rect().isEmpty())
            self.advance(8)
            self.assertEqual(self.resources(), settled)
            outcomes.append(tuple(after-start for start, after in zip(before, settled)))
            self.clean()
            self.home()
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], (0, 20, 0, 0, 0, 1))

    def test_real_dummy_signal_completes_three_experiences_and_survives_restart(self):
        signals = []
        self.r.furniture_interacted.connect(signals.append)
        self.assertFalse(self.r.activate_furniture("training_dummy"))
        self.assertEqual(signals, [])
        self.assertTrue(self.m.buy_furniture("training_dummy"))
        self.assertTrue(self.m.equip_furniture("corner", "training_dummy"))
        QTest.mouseClick(self.r, Qt.MouseButton.LeftButton, pos=self.r.furniture_rect("training_dummy").center().toPoint())
        APP.processEvents()
        self.freeze(self.c)
        self.assertEqual(signals, ["training_dummy"])
        self.assertEqual(self.m.data.practice_experiences, ["training_dummy"])
        self.advance(4)
        for key in ("gnar_workbook", "practice_hourglass"):
            self.assertTrue(self.m.buy_item(key, feed_now=True))
            self.advance(8)
        self.assertEqual(set(self.m.data.practice_experiences), {"gnar_workbook", "practice_hourglass", "training_dummy"})
        self.assertEqual(self.m.data.titles.count("这次真练好了"), 1)
        before = self.resources()
        self.assertTrue(self.r.activate_furniture("training_dummy"))
        self.advance(8)
        self.assertEqual(self.resources(), before)
        self.c._save()
        self.c.stop()
        restored = self.make_controller(dev_mode=False)
        self.assertEqual(restored.model.data.practice_experiences, self.m.data.practice_experiences)
        self.assertEqual(restored.model.data.titles.count("这次真练好了"), 1)

    def test_new_foods_keep_three_seconds_of_extra_visuals_then_clear_without_exp(self):
        for key, amount in (("postmatch_noodles", 15), ("late_practice_snack", 35)):
            self.m.set_hunger(40)
            before = self.resources()
            self.assertTrue(self.m.buy_item(key, feed_now=True))
            settled = self.resources()
            self.assertEqual(settled[1], before[1])
            self.assertEqual(settled[2], 40+amount)
            self.advance(self.r.FLIGHT_SECONDS + 1.4)
            self.assertEqual(self.r.foreground_kind, "food")
            self.assertEqual(self.r._food_id, key)
            self.assertIsNotNone(self.r.presentation.active)
            self.advance(1.8)
            self.assertEqual(self.r._food_id, "")
            self.assertIsNone(self.r.presentation.active)
            self.advance(8)
            self.assertEqual(self.resources(), settled)
            self.clean()
            self.home()

    def test_training_theme_counter_and_visual_combo_are_specific_to_this_performance(self):
        for key in ("training_dummy", "practice_room"):
            self.assertTrue(self.m.buy_furniture(key))
        self.assertTrue(self.m.equip_furniture("corner", "training_dummy"))
        self.assertTrue(self.m.equip_furniture("theme", "practice_room"))
        self.assertTrue(self.m.buy_accessory("mini_gnar_hat"))
        self.assertTrue(self.m.equip_accessory("head", "mini_gnar_hat"))
        self.assertTrue(self.m.buy_item("gnar_workbook", feed_now=True))
        self.assertTrue(self.r.performance.practice_combo)
        self.assertTrue(self.r.performance.training_theme)
        before = self.resources()
        # Counter stamps follow completed throws, not the start of a round.
        self.advance(2.3)
        first = self.paint_layer(self.r._paint_practice_counter, "practice-round-one")
        self.advance(4.6)
        third = self.paint_layer(self.r._paint_practice_counter, "practice-round-three")
        self.assertNotEqual(first, third)
        self.advance(4)
        idle = self.paint_layer(self.r._paint_practice_counter, "practice-counter-idle")
        self.assertNotEqual(idle, first)
        self.assertEqual(self.resources(), before)
        self.assertTrue(self.m.equip_accessory("head", ""))
        self.assertTrue(self.m.buy_item("gnar_workbook", feed_now=True))
        self.assertFalse(self.r.performance.practice_combo)
        self.advance(8)
        self.clean()

    def test_summit_holds_light_in_stages_only_when_wall_is_installed(self):
        self.assertTrue(self.m.buy_furniture("summit_wall"))
        self.assertTrue(self.m.equip_furniture("wall", "summit_wall"))
        self.assertTrue(self.m.buy_accessory("summit_backpack"))
        self.assertTrue(self.m.equip_accessory("back", "summit_backpack"))
        idle = self.paint_layer(self.r._paint_wall_decoration, "summit-idle")
        self.assertTrue(self.m.buy_item("summit_pickaxe", feed_now=True))
        self.assertTrue(self.r.performance.summit_combo)
        before = self.resources()
        hashes = []
        for elapsed, name in ((.3, "summit-start"), (1.4, "summit-middle"), (2.5, "summit-final")):
            self.advance(elapsed)
            hashes.append(self.paint_layer(self.r._paint_wall_decoration, name))
        self.assertEqual(len(set(hashes)), 3)
        self.advance(6)
        self.assertEqual(self.paint_layer(self.r._paint_wall_decoration, "summit-clean"), idle)
        self.assertEqual(self.resources(), before)
        self.assertTrue(self.m.equip_furniture("wall", ""))
        uninstalled = self.paint_layer(self.r._paint_wall_decoration, "summit-uninstalled")
        self.assertNotEqual(uninstalled, idle)
        self.assertIn("登峰造圆", self.m.data.titles)
        self.clean()

    def test_reverse_flash_free_and_pinned_return_actual_feet_then_home(self):
        self.assertTrue(self.m.buy_trick("reverse_flash"))
        for pinned in (True, False):
            self.c._cancel_presentation("input")
            self.c.window.set_pinned(pinned)
            self.e.place(700, 760 if pinned else self.e.area.bottom)
            self.advance(1)
            self.r.life.x = .61
            self.r.life.interact()
            self.r.life.wait = 1000
            self.m.advance(12)
            origin, anchor = self.foot(), self.c.window.capture_position()
            before = self.resources()
            self.assertTrue(self.c._perform_trick("reverse_flash"))
            self.advance(.8)
            moved = self.foot()
            self.assertGreater(origin.x()-moved.x(), 1)
            self.assertLessEqual(origin.x()-moved.x(), 60.01)
            self.assertAlmostEqual(moved.y(), origin.y(), places=4)
            self.assertEqual(self.c.window.capture_position(), anchor)
            if pinned:
                self.assertEqual(self.e.visual_offset, QPointF())
            self.advance(2)
            self.assertAlmostEqual(self.foot().x(), origin.x(), places=4)
            self.assertAlmostEqual(self.foot().y(), origin.y(), places=4)
            self.advance(8)
            self.assertEqual(self.c.window.capture_position(), anchor)
            self.assertEqual(self.resources(), before)
            self.clean()
            self.home()

    def test_reverse_flash_interrupt_skin_hide_and_food_clear_old_layers(self):
        self.assertTrue(self.m.buy_trick("reverse_flash"))
        for reason in ("input", "skin", "hide", "food"):
            self.m.advance(12)
            self.r.life.x = .62
            self.r.life.interact()
            self.r.life.wait = 1000
            anchor = self.c.window.capture_position()
            self.assertTrue(self.c._perform_trick("reverse_flash"))
            self.advance(.85)
            current = self.foot()
            if reason == "input":
                self.c._cancel_presentation("input")
                self.assertAlmostEqual(self.foot().x(), current.x(), places=4)
                self.assertAlmostEqual(self.foot().y(), current.y(), places=4)
            elif reason == "skin":
                self.assertTrue(self.c._select_skin("team_s16_blg"))
            elif reason == "hide":
                self.p.hide()
                APP.processEvents()
                self.p.summon()
                APP.processEvents()
                self.freeze(self.c)
            else:
                self.assertTrue(self.m.buy_item("postmatch_noodles", feed_now=True))
                self.assertEqual(self.r.foreground_kind, "food")
            self.assertEqual(self.e.active_trick, "")
            self.assertEqual(self.m._active_trick_id, "")
            self.advance(12)
            self.assertEqual(self.c.window.capture_position(), anchor)
            self.clean()
            self.home()

    def test_rejected_flash_keeps_old_performance_and_never_starts_cooldown(self):
        self.assertTrue(self.c._perform_trick("clone"))
        accepted, before = dict(self.e.presentation.active), self.m.snapshot()
        self.assertFalse(self.c._perform_trick("reverse_flash"))
        self.assertEqual(self.e.presentation.active, accepted)
        self.assertEqual(self.m.snapshot(), before)
        self.assertTrue(self.m.buy_trick("reverse_flash"))
        before = self.m.snapshot()
        self.e.held = True
        self.assertFalse(self.c._perform_trick("reverse_flash"))
        self.e.held = False
        self.assertEqual(self.e.presentation.active, accepted)
        self.assertEqual(self.m.snapshot(), before)
        self.assertEqual(self.m.trick_cooldowns["reverse_flash"], 0)
        self.assertTrue(self.c._perform_trick("reverse_flash"))
        accepted = dict(self.e.presentation.active)
        self.assertFalse(self.c._perform_trick("reverse_flash"))
        self.assertEqual(self.e.presentation.active, accepted)
        self.advance(11)
        self.clean()
        self.home()

    def test_new_ownership_and_partial_progress_restart_without_dev_currency_leak(self):
        for key in CONSUMABLES:
            self.assertTrue(self.m.buy_item(key))
        for key, slot in (("seven_goggles", "face"), ("kiting_scarf", "back")):
            self.assertTrue(self.m.buy_accessory(key))
            self.assertTrue(self.m.equip_accessory(slot, key))
        for key, slot in (("practice_room", "theme"), ("summit_wall", "wall")):
            self.assertTrue(self.m.buy_furniture(key))
            self.assertTrue(self.m.equip_furniture(slot, key))
        self.assertTrue(self.m.buy_trick("reverse_flash"))
        self.assertTrue(self.m.use_item("gnar_workbook"))
        self.c._save()
        self.c.stop()
        data, _ = SaveManager(self.work / "save_data.json").load_all()
        restored = self.make_controller(dev_mode=False)
        self.assertFalse(restored.model.unlimited_coins)
        self.assertEqual(restored.model.data.practice_experiences, ["gnar_workbook"])
        self.assertEqual(restored.model.effective_accessories(), self.m.effective_accessories())
        self.assertEqual(restored.model.data.equipped_furniture, data.equipped_furniture)
        self.assertEqual(restored.model.data.inventory, data.inventory)
        self.assertTrue(restored.model.has_trick("reverse_flash"))
        self.assertEqual(restored.model.data.coins, 0)
        self.assertFalse(restored.model.buy_item("postmatch_noodles"))
        self.assertFalse(restored.debug_menu.menuAction().isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
