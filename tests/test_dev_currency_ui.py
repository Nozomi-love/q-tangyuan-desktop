"""Developer currency must work through real controls without leaking into saves."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
import zipfile

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QTabWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PetApplication
from models import PetData
from save_manager import SaveManager

APP = QApplication.instance() or QApplication(["developer-currency-ui"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("dev-currency-ui-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


class DeveloperCurrencyUiTests(unittest.TestCase):
    def setUp(self):
        self.work = ART / self._testMethodName
        self.work.mkdir()
        self.controllers = []
        self.c = self.make_controller(dev_mode=True)
        self.p, self.m = self.c.dashboard, self.c.model
        self.m.replace_data(PetData(coins=0, hunger=40, muted=True, overlay_visible=False))
        APP.processEvents()

    def make_controller(self, *, profile: str = "", **kwargs):
        directory = self.work / profile if profile else self.work
        directory.mkdir(exist_ok=True)
        controller = PetApplication(
            APP, save_path=directory / "save_data.json", skins_root=directory / "skins", **kwargs)
        self.controllers.append(controller)
        for timer in (controller.tick_timer, controller.autosave_timer,
                      controller.save_timer, controller.window.timer,
                      controller.dashboard.room._animation_timer):
            timer.stop()
        controller.model.set_muted(True)
        controller.model.set_overlay_visible(False)
        controller.dashboard.resize(1240, 800)
        APP.processEvents()
        return controller

    def tearDown(self):
        for controller in self.controllers:
            controller.stop()
            controller.dashboard.deleteLater()
            controller.window.deleteLater()
            controller.tray.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def click_shop(self, button):
        """Reveal the actual nested page and scroll card before a mouse click."""
        self.p.show_section("shop", animate=False)
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
                parent.ensureWidgetVisible(button, 8, 8)
        APP.processEvents()
        self.assertTrue(button.isVisible(), button.text())
        self.assertTrue(button.isEnabled(), button.text())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APP.processEvents()

    def paid_gates(self):
        return [self.p.shop_buttons["sugar"][0],
                self.p.shop_buttons["paper_star"][0],
                self.p.furniture_shop_buttons["lotus_cushion"],
                self.p.shop_trick_buttons["screen_roll"][0],
                self.p.team_skin_buttons["team_s16_tes"][0],
                self.p.accessory_shop_buttons["cooling_cap"][0]]

    def test_explicit_dev_mode_shows_unlimited_and_enables_all_price_gates(self):
        self.assertTrue(self.m.unlimited_coins)
        self.assertFalse(self.m.debug_unlock_all)
        self.assertEqual(self.p.balance.text(), "无限")
        self.assertIn("0", self.p.balance.toolTip())
        self.assertIn("无限", self.c.coins_info.text())
        self.assertTrue(self.c.feed_action.isEnabled())
        self.assertTrue(all(button.isEnabled() for button in self.paid_gates()))
        self.p.show_section("settings", animate=False)
        self.assertFalse(self.p.dev_currency_label.isHidden())
        self.assertEqual(self.m.data.coins, 0)
        self.assertFalse(self.m.has_trick("flip"), "Money cannot grant level privileges")
        self.assertFalse(self.p.furniture_shop_buttons["sunny_chime"].isEnabled())

    def test_zero_balance_food_and_gift_buttons_settle_once(self):
        self.click_shop(self.p.shop_buttons["sugar"][0])
        self.assertEqual(self.m.data.inventory["sugar"], 1)
        self.assertEqual(self.m.data.hunger, 40)
        self.assertEqual(self.m.data.stats["total_feeds"], 0)
        before_exp = self.m._lifetime_exp()
        self.click_shop(self.p.shop_buttons["sugar"][1])
        self.assertEqual(self.m.data.hunger, 40 + self.m.rules.sugar_hunger)
        self.assertEqual(self.m.data.stats["total_feeds"], 1)
        self.assertEqual(self.m.data.inventory["sugar"], 1)
        self.assertEqual(self.m._lifetime_exp(), before_exp)
        self.click_shop(self.p.shop_buttons["paper_star"][1])
        self.assertEqual(self.m._lifetime_exp(), before_exp + self.m.item("paper_star")["exp"])
        self.assertEqual(self.m.data.stats["total_presents"], 1)
        self.assertEqual(self.m.data.coins, 0)

    def test_permanent_purchase_buttons_grant_owned_items_without_debit(self):
        products = ((self.p.furniture_shop_buttons["lotus_cushion"],
                     "lotus_cushion", "owned_furniture"),
                    (self.p.shop_trick_buttons["screen_roll"][0],
                     "screen_roll", "purchased_tricks"),
                    (self.p.team_skin_buttons["team_s16_tes"][0],
                     "team_s16_tes", "owned_team_skins"),
                    (self.p.accessory_shop_buttons["cooling_cap"][0],
                     "cooling_cap", "purchased_accessories"))
        for button, key, collection in products:
            with self.subTest(key=key):
                self.click_shop(button)
                self.assertEqual(getattr(self.m.data, collection).count(key), 1)
                self.assertFalse(button.isEnabled())
                self.assertEqual(self.m.data.coins, 0)
        self.click_shop(self.p.team_skin_buttons["team_s16_tes"][1])
        self.assertEqual(self.m.data.selected_skin_id, "team_s16_tes")
        self.click_shop(self.p.accessory_shop_buttons["cooling_cap"][1])
        self.assertEqual(self.m.data.accessories["head"], "cooling_cap")

    def test_tes_requirement_survives_free_purchase(self):
        buy, use, _ = self.p.shop_buttons["tes_guitar"]
        self.assertTrue(buy.isEnabled())
        self.assertFalse(use.isEnabled())
        self.click_shop(buy)
        self.assertEqual(self.m.data.inventory["tes_guitar"], 1)
        self.assertFalse(self.m.use_item("tes_guitar"))
        self.assertEqual(self.m.data.inventory["tes_guitar"], 1)
        self.click_shop(self.p.team_skin_buttons["team_s16_tes"][0])
        self.click_shop(self.p.team_skin_buttons["team_s16_tes"][1])
        self.assertTrue(use.isEnabled())
        self.click_shop(use)
        self.assertEqual(self.m.data.inventory["tes_guitar"], 1)
        self.assertEqual(self.m.data.stats["total_presents"], 1)
        self.assertEqual(self.m.data.coins, 0)

    def test_disabling_unlimited_refreshes_every_affordability_surface(self):
        self.assertTrue(self.m.set_unlimited_coins(False))
        APP.processEvents()
        self.assertEqual(self.p.balance.text(), "0")
        self.assertNotIn("无限", self.c.coins_info.text())
        self.assertFalse(self.c.feed_action.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in self.paid_gates()))
        before = self.m.snapshot()
        self.assertFalse(self.m.buy_item("sugar"))
        self.assertEqual(self.m.snapshot(), before)

    def test_acceleration_and_debug_trial_do_not_grant_infinite_money(self):
        normal = self.make_controller(accelerated=True, profile="normal")
        normal.model.replace_data(PetData(coins=0, muted=True, overlay_visible=False))
        self.assertFalse(normal.model.unlimited_coins)
        normal.dev_action.setChecked(False)
        normal.dev_action.setChecked(True)
        self.assertFalse(normal.model.unlimited_coins)
        self.assertTrue(normal.model.set_debug_unlock(True, authorized=True))
        APP.processEvents()
        self.assertFalse(normal.model.unlimited_coins)
        self.assertFalse(normal.dashboard.shop_buttons["sugar"][0].isEnabled())
        self.assertFalse(normal.feed_action.isEnabled())
        self.assertEqual(normal.dashboard.balance.text(), "0")
        self.assertTrue(normal.dashboard.dev_currency_label.isHidden())

    def test_backup_restore_keeps_runtime_permission_but_not_in_archive(self):
        self.c._save()
        archive = self.work / "backup.zip"
        self.c._export_backup(str(archive))
        self.assertTrue(archive.is_file(), self.p.backup_status.text())
        with zipfile.ZipFile(archive) as package:
            payload = json.loads(package.read("save_data.json"))
        self.assertEqual(payload["coins"], 0)
        for key in ("unlimited_coins", "_unlimited_coins", "dev_mode"):
            self.assertNotIn(key, payload)
        self.m.data.coins = 321
        self.m.buy_item("sugar")
        self.c._save()
        self.c._restore_backup(str(archive))
        self.assertIn("恢复完成", self.p.backup_status.text())
        self.assertEqual(self.m.data.coins, 0)
        self.assertTrue(self.m.unlimited_coins)
        self.assertEqual(self.p.balance.text(), "无限")
        self.click_shop(self.p.shop_buttons["sugar"][0])
        self.assertEqual(self.m.data.inventory["sugar"], 1)
        self.assertEqual(self.m.data.coins, 0)

    def test_reopening_same_dev_save_in_release_restores_real_balance(self):
        self.click_shop(self.p.shop_trick_buttons["screen_roll"][0])
        self.c._save()
        self.c.stop()
        saved = SaveManager(self.work / "save_data.json").load_game_state()
        self.assertEqual(saved.coins, 0)
        self.assertIn("screen_roll", saved.purchased_tricks)
        release = self.make_controller(dev_mode=False)
        self.assertFalse(release.model.unlimited_coins)
        self.assertEqual(release.dashboard.balance.text(), "0")
        self.assertFalse(release.dashboard.shop_buttons["sugar"][0].isEnabled())
        self.assertIn("screen_roll", release.model.data.purchased_tricks)
        self.assertFalse(release.debug_menu.menuAction().isVisible())
        self.assertTrue(release.dashboard.dev_currency_label.isHidden())
        payload = json.loads((self.work / "save_data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["coins"], 0)
        self.assertNotIn("unlimited_coins", payload)


if __name__ == "__main__":
    unittest.main()
