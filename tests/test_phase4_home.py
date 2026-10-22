"""Home room, shared pet state, furniture commerce and independent restart."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from main import PetApplication
from models import Catalog, PetData, PetModel
from pet_engine import PetEngine, PetState, RoomCanvas, SkinRenderer, WorkArea
from save_manager import SaveManager, SaveDataError
from pet_window import SpeechBubble

APP = QApplication.instance() or QApplication(["home-scene-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ARTIFACTS = ROOT / "tests/artifacts" / datetime.now().strftime("home-scene-%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)
DEFAULTS = {"theme": "cheese_room", "rug": "cloud_cushion", "wall": "", "corner": "", "bowl": "wood_bowl"}


def rich(**kwargs):
    return PetModel(PetData(coins=10000, **kwargs), rng=random.Random(1))


class HomeFurnitureModelTests(unittest.TestCase):
    def test_catalog_has_twelve_priced_painter_furniture_in_five_slots(self):
        furniture = Catalog.load().furniture
        expected = {"cloud_cushion": ("rug", 0), "lotus_cushion": ("rug", 40),
                    "cat_paw_rug": ("rug", 80), "wood_bowl": ("bowl", 0),
                    "porcelain_bowl": ("bowl", 50), "sunflower_painting": ("wall", 60),
                    "rice_clock": ("wall", 70), "ficus_plant": ("corner", 60),
                    "warm_lamp": ("corner", 90), "cheese_room": ("theme", 0),
                    "sakura_room": ("theme", 100), "matcha_room": ("theme", 100)}
        self.assertEqual(set(furniture), set(expected))
        for key, (slot, cost) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(furniture[key]["slot"], slot)
                self.assertEqual(furniture[key]["price"], cost)

    def test_defaults_are_owned_equipped_without_expense_or_achievement(self):
        model = PetModel()
        self.assertEqual(model.data.equipped_furniture, DEFAULTS)
        self.assertEqual(set(model.data.owned_furniture), {"cheese_room", "cloud_cushion", "wood_bowl"})
        self.assertEqual(model.data.coins, 100)
        achievement = next(row for row in model.catalog.achievements if row["name"] == "温馨小家")
        self.assertNotIn(achievement["id"], model.data.unlocked_achievements)
        self.assertFalse(model.data.overlay_visible)
        self.assertTrue(model.data.lamp_on)

    def test_purchase_enters_owned_list_without_auto_redecoration(self):
        model = rich()
        self.assertTrue(model.buy_furniture("lotus_cushion"))
        self.assertEqual(model.data.coins, 9960)
        self.assertIn("lotus_cushion", model.data.owned_furniture)
        self.assertEqual(model.data.equipped_furniture["rug"], "cloud_cushion")
        self.assertTrue(model.equip_furniture("rug", "lotus_cushion"))
        self.assertEqual(model.data.equipped_furniture["rug"], "lotus_cushion")
        self.assertEqual(model.data.coins, 9960)

    def test_repeated_purchase_never_charges_twice(self):
        model = rich()
        self.assertTrue(model.buy_furniture("warm_lamp"))
        before = model.snapshot()
        model.buy_furniture("warm_lamp")
        self.assertEqual(model.snapshot(), before)

    def test_unaffordable_or_unknown_purchase_is_atomic(self):
        for key in ("warm_lamp", "../outside", "absent"):
            with self.subTest(key=key):
                model = PetModel(PetData(coins=1))
                before = model.snapshot()
                self.assertFalse(model.buy_furniture(key))
                self.assertEqual(model.snapshot(), before)

    def test_wrong_slot_unowned_unknown_equips_are_atomic(self):
        model = rich()
        for slot, key in (("rug", "wood_bowl"), ("wall", "sunflower_painting"),
                          ("ceiling", "cloud_cushion"), ("rug", "missing")):
            with self.subTest(slot=slot, key=key):
                before = model.snapshot()
                self.assertFalse(model.equip_furniture(slot, key))
                self.assertEqual(model.snapshot(), before)

    def test_first_purchase_and_placement_unlocks_claimable_once(self):
        model = rich()
        achievement = next(row for row in model.catalog.achievements if row["name"] == "温馨小家")
        events = []
        model.achievement_unlocked.connect(events.append)
        model.buy_furniture("rice_clock")
        self.assertNotIn(achievement["id"], model.data.unlocked_achievements)
        model.equip_furniture("wall", "rice_clock")
        self.assertIn(achievement["id"], model.data.unlocked_achievements)
        self.assertEqual(sum(row["id"] == achievement["id"] for row in events), 1)
        coins = model.data.coins
        self.assertTrue(model.claim_achievement(achievement["id"]))
        self.assertEqual(model.data.coins, coins + 60)
        self.assertFalse(model.claim_achievement(achievement["id"]))
        model.equip_furniture("wall", "rice_clock")
        self.assertEqual(model.data.coins, coins + 60)
        self.assertEqual(sum(row["id"] == achievement["id"] for row in events), 1)

    def test_each_slot_can_be_redecorated_and_persisted(self):
        model = rich()
        chosen = {"theme": "matcha_room", "rug": "cat_paw_rug", "wall": "sunflower_painting",
                  "corner": "ficus_plant", "bowl": "porcelain_bowl"}
        for slot, key in chosen.items():
            self.assertTrue(model.buy_furniture(key))
            self.assertTrue(model.equip_furniture(slot, key))
        self.assertEqual(model.data.equipped_furniture, chosen)
        self.assertEqual(PetData.from_dict(model.snapshot()).equipped_furniture, chosen)

    def test_name_is_free_trimmed_saved_and_announced(self):
        model = rich()
        messages = []
        model.feedback.connect(lambda *args: messages.append(args))
        self.assertTrue(model.rename_pet("  芝麻阿一古  "))
        self.assertEqual(model.data.name, "芝麻阿一古")
        self.assertEqual(model.data.coins, 10000)
        self.assertEqual(PetData.from_dict(model.snapshot()).name, "芝麻阿一古")
        self.assertTrue(messages)

    def test_invalid_names_cannot_change_pet_or_charge_coins(self):
        model = rich()
        for value in ("", "   ", "坏\n名字", "x" * 41, None, 123):
            with self.subTest(value=value):
                before = model.snapshot()
                self.assertFalse(model.rename_pet(value))
                self.assertEqual(model.snapshot(), before)

    def test_visibility_and_lamp_changes_publish_but_cost_nothing(self):
        model = rich()
        events = []
        model.state_changed.connect(events.append)
        model.set_overlay_visible(True)
        model.set_lamp_on(False)
        self.assertTrue(model.data.overlay_visible)
        self.assertFalse(model.data.lamp_on)
        self.assertEqual(model.data.coins, 10000)
        self.assertGreaterEqual(len(events), 2)
        again = PetData.from_dict(model.snapshot())
        self.assertTrue(again.overlay_visible)
        self.assertFalse(again.lamp_on)

    def test_food_consumed_event_is_not_emitted_for_gift_or_failed_food(self):
        model = rich()
        eaten = []
        model.food_consumed.connect(eaten.append)
        self.assertFalse(model.use_item("sugar"))
        model.buy_item("paper_star", True)
        self.assertEqual(eaten, [])
        model.buy_item("sesame")
        self.assertEqual(eaten, [])
        model.use_item("sesame")
        self.assertEqual(eaten, ["sesame"])
        model.buy_item("water", True)
        self.assertEqual(eaten, ["sesame", "water"])

    def test_poke_line_is_the_requested_new_phrase(self):
        model = rich()
        messages = []
        model.feedback.connect(lambda *args: messages.append(args))
        model.poke()
        self.assertEqual(messages[-1], ("急咯急咯", "interaction"))


class HomeSaveTests(unittest.TestCase):
    def test_schema_five_adds_home_defaults_and_preserves_prior_progress(self):
        file = ARTIFACTS / "old-v5-home-defaults.json"
        old = {"schema_version": 5, "name": "老汤圆", "coins": 987, "hunger": 37,
               "affection_level": 6, "affection_exp": 888, "selected_skin_id": "user_" + "a" * 32,
               "accessories": {"head": "crown", "offset_y": -14}, "inventory": {"sugar": 3},
               "purchased_tricks": ["screen_roll"], "future": {"keep": True},
               "window": {"pinned": True, "x_ratio": .4, "y_ratio": .3}}
        file.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        save = SaveManager(file)
        data, window = save.load_all()
        self.assertEqual(data.equipped_furniture, DEFAULTS)
        save.update_game(data.to_dict(), window)
        restored = json.loads(file.read_text(encoding="utf-8"))
        for key in ("coins", "hunger", "affection_level", "affection_exp", "selected_skin_id", "inventory", "purchased_tricks", "future", "window"):
            self.assertEqual(restored[key], old[key], key)
        self.assertEqual(restored["name"], "老汤圆")
        self.assertEqual(restored["accessories"]["head"], "crown")
        self.assertEqual(restored["equipped_furniture"], DEFAULTS)

    def test_independent_process_restores_five_slots_name_and_visibility(self):
        file = ARTIFACTS / "cross-process-home.json"
        model = rich()
        for slot, key in (("theme", "sakura_room"), ("rug", "lotus_cushion"), ("wall", "rice_clock"),
                          ("corner", "warm_lamp"), ("bowl", "porcelain_bowl")):
            model.buy_furniture(key)
            model.equip_furniture(slot, key)
        model.rename_pet("阿一古的小窝")
        model.set_overlay_visible(True)
        model.set_lamp_on(False)
        SaveManager(file).update_game(model.snapshot(), {"pinned": True, "x_ratio": .3, "y_ratio": .6})
        code = ("import json,sys; from pathlib import Path; from save_manager import SaveManager; "
                "data,window=SaveManager(Path(sys.argv[1])).load_all(); "
                "print(json.dumps({'pet':data.to_dict(),'window':window},ensure_ascii=False))")
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", code, str(file)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual["pet"], model.snapshot())
        self.assertEqual(actual["window"], {"pinned": True, "x_ratio": .3, "y_ratio": .6})

    def test_unowned_cross_slot_and_unknown_furniture_save_rejected_without_overwrite(self):
        file = ARTIFACTS / "invalid-furniture-save.json"
        save = SaveManager(file)
        original = rich().snapshot()
        save.update_game(original)
        before = file.read_bytes()
        for slot, key in (("wall", "rice_clock"), ("rug", "wood_bowl"), ("corner", "missing")):
            bad = deepcopy(original)
            bad["equipped_furniture"][slot] = key
            with self.subTest(slot=slot, key=key), self.assertRaises(SaveDataError):
                save.update_game(bad)
            self.assertEqual(file.read_bytes(), before)


class HomeRoomPainterTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1000, 800))
        self.renderer = SkinRenderer(ARTIFACTS / "missing-fallback-skin")
        self.room = RoomCanvas(self.engine, lambda: self.renderer)
        self.room.resize(850, 440)
        self.model = rich()
        self.room.set_home_state(self.model.snapshot(), self.model.catalog.furniture)
        self.room.show()
        APP.processEvents()

    def tearDown(self):
        self.room.stop()
        self.renderer.stop()
        self.room.close()
        self.room.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def image(self):
        image = QImage(self.room.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        self.room.render(image)
        return image

    def test_day_night_switch_follows_local_hour(self):
        for hour in (7, 12, 17):
            self.assertTrue(RoomCanvas.is_daytime(datetime(2026, 10, 17, hour)))
        for hour in (0, 2, 22, 23):
            self.assertFalse(RoomCanvas.is_daytime(datetime(2026, 10, 17, hour)))

    def test_canvas_day_night_and_themes_have_distinct_pixels(self):
        self.room.daytime_override = True
        day = self.image()
        self.room.daytime_override = False
        night = self.image()
        self.assertNotEqual(bytes(day.constBits()), bytes(night.constBits()))
        self.model.buy_furniture("sakura_room")
        self.model.equip_furniture("theme", "sakura_room")
        self.room.set_home_state(self.model.snapshot(), self.model.catalog.furniture)
        pink = self.image()
        self.assertNotEqual(bytes(night.constBits()), bytes(pink.constBits()))
        self.assertTrue(pink.save(str(ARTIFACTS / "room-night-sakura.png")))

    def test_left_click_pokes_and_right_click_pets_only_the_body(self):
        pokes, pets = [], []
        self.room.poke_requested.connect(lambda: pokes.append(True))
        self.room.pet_requested.connect(lambda: pets.append(True))
        center = self.room.pet_center().toPoint()
        self.assertTrue(self.room.rect().contains(center))
        QTest.mouseClick(self.room, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseClick(self.room, Qt.MouseButton.RightButton, pos=center)
        self.assertEqual(pokes, [True])
        self.assertEqual(pets, [True])
        QTest.mouseClick(self.room, Qt.MouseButton.LeftButton, pos=QPointF(10, 10).toPoint())
        self.assertEqual(pokes, [True])

    def test_render_does_not_advance_or_reposition_shared_desktop_engine(self):
        self.engine.set_pinned(True)
        self.engine.place(333, 444)
        self.engine.click()
        before = (self.engine.x, self.engine.y, self.engine.elapsed, self.engine.spring, self.engine.vy)
        for _ in range(3):
            self.image()
        self.assertEqual((self.engine.x, self.engine.y, self.engine.elapsed, self.engine.spring, self.engine.vy), before)
        self.assertTrue(self.room.rect().contains(self.room.pet_center().toPoint()))

    def test_room_and_desktop_dialogue_priority_queue_and_expiry_match(self):
        bubble = SpeechBubble(self.room)
        try:
            with patch("pet_engine.monotonic", return_value=100), patch("pet_window.time.perf_counter", return_value=100):
                for text,tone in (("急咯急咯","interaction"),("成就达成","achievement"),("升级啦","level"),("急咯急咯","interaction")):
                    self.room.show_message(text,tone)
                    bubble.show_message(text,tone)
                    self.assertEqual((self.room._message,self.room._message_tone),(bubble._text,bubble._tone))
                    self.assertEqual(list(self.room._notifications),list(bubble._notifications))
                self.assertEqual(self.room._message,"急咯急咯")
                self.assertEqual([row[0] for row in self.room._notifications],["成就达成","升级啦"])
            for now,expected in ((103,"成就达成"),(106,"升级啦")):
                with patch("pet_engine.monotonic", return_value=now),patch("pet_window.time.perf_counter", return_value=now):
                    self.room._advance_message()
                    bubble._refresh()
                    self.assertEqual(self.room._message,expected)
                    self.assertEqual((self.room._message,self.room._message_tone),(bubble._text,bubble._tone))
                    self.assertEqual(list(self.room._notifications),list(bubble._notifications))
        finally:
            bubble.stop()
            bubble.deleteLater()

    def test_food_and_dialogue_are_drawn_without_advancing_model(self):
        before = self.model.snapshot()
        plain = self.image()
        self.room.show_food("strawberry")
        self.room.show_message("急咯急咯", "interaction")
        active = self.image()
        self.assertNotEqual(bytes(plain.constBits()), bytes(active.constBits()))
        self.assertEqual(self.model.snapshot(), before)
        self.assertTrue(active.save(str(ARTIFACTS / "room-food-dialogue.png")))

    def test_lamp_click_emits_separate_signal_without_poke(self):
        self.model.buy_furniture("warm_lamp")
        self.model.equip_furniture("corner", "warm_lamp")
        self.room.set_home_state(self.model.snapshot(), self.model.catalog.furniture)
        lamps, pokes = [], []
        self.room.lamp_toggle_requested.connect(lambda: lamps.append(True))
        self.room.poke_requested.connect(lambda: pokes.append(True))
        area = self.room.lamp_rect()
        self.assertFalse(area.isEmpty())
        QTest.mouseClick(self.room, Qt.MouseButton.LeftButton, pos=area.center().toPoint())
        self.assertEqual(lamps, [True])
        self.assertEqual(pokes, [])


class HomeControllerTests(unittest.TestCase):
    def setUp(self):
        self.folder = ARTIFACTS / self._testMethodName
        self.folder.mkdir()
        self.file = self.folder / "save_data.json"
        SaveManager(self.file).update_game(PetData(coins=1000, affection_level=6).to_dict())
        self.controller = PetApplication(APP, save_path=self.file, skins_root=self.folder / "skins")
        self.panel = self.controller.dashboard
        self.model = self.controller.model
        self.pet = self.controller.window
        self.pet.timer.stop()
        self.controller.tick_timer.stop()
        self.controller.autosave_timer.stop()
        QTest.qWait(25)

    def tearDown(self):
        self.controller.stop()
        self.panel.deleteLater()
        self.pet.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_home_opens_by_default_with_optional_hidden_desktop_pet(self):
        self.assertTrue(self.panel.isVisible())
        self.assertTrue(self.panel.room.isVisible())
        self.assertFalse(self.pet.isVisible())
        self.assertFalse(self.model.data.overlay_visible)
        self.assertTrue(self.panel.tabs.tabBar().isHidden())
        self.assertEqual(set(self.panel.nav_buttons), {"home", "bag", "shop", "dress", "achievements"})

    def test_tray_double_click_summons_dashboard_without_resetting_position(self):
        self.pet.set_pinned(True)
        self.pet.engine.place(333, 444)
        before = self.pet.engine.x, self.pet.engine.y, self.pet.engine.pinned
        self.panel.hide()
        self.controller._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertTrue(self.panel.isVisible())
        self.assertEqual((self.pet.engine.x, self.pet.engine.y, self.pet.engine.pinned), before)
        self.assertFalse(self.pet.isVisible())

    def test_overlay_toggle_button_updates_visibility_and_survives_save(self):
        self.panel.overlay_button.click()
        self.assertTrue(self.pet.isVisible())
        self.assertTrue(self.model.data.overlay_visible)
        self.panel.overlay_button.click()
        self.assertFalse(self.pet.isVisible())
        self.assertFalse(self.model.data.overlay_visible)
        self.controller._save()
        self.assertFalse(SaveManager(self.file).load_game_state().overlay_visible)

    def test_hidden_overlay_cannot_resurrect_bubble_during_income_or_feedback(self):
        self.model.set_overlay_visible(True)
        self.model.poke()
        self.assertTrue(self.pet.bubble.isVisible())
        self.model.set_overlay_visible(False)
        self.assertFalse(self.pet.isVisible())
        self.assertFalse(self.pet.bubble.isVisible())
        self.model.offer_collectible()
        self.pet.show_collectible(False)
        self.model.feedback.emit("小窝里继续陪你", "interaction")
        APP.processEvents()
        self.assertFalse(self.pet.bubble.isVisible())
        self.assertFalse(self.pet.isVisible())
        self.assertEqual(self.panel.room._message,"小窝里继续陪你")
        self.assertTrue(self.panel.room.isVisible())

    def test_naming_dialog_signal_updates_hud_and_save(self):
        with patch("dashboard.QInputDialog.getText", return_value=("家里的糯米糍", True)):
            self.panel.rename_button.click()
        self.assertEqual(self.model.data.name, "家里的糯米糍")
        self.assertIn("家里的糯米糍", self.panel.hud_name.text())
        self.controller._save()
        self.assertEqual(SaveManager(self.file).load_game_state().name, "家里的糯米糍")

    def test_home_poke_changes_model_and_shared_engine_once_with_desktop_hidden(self):
        before = self.model.data.stats["total_clicks"]
        QTest.mouseClick(self.panel.room, Qt.MouseButton.LeftButton,
                         pos=self.panel.room.pet_center().toPoint())
        self.assertEqual(self.model.data.stats["total_clicks"], before + 1)
        self.assertEqual(self.pet.engine.state, PetState.HAPPY)
        self.assertFalse(self.pet.isVisible())
        self.assertFalse(self.pet.bubble.isVisible())

    def test_room_pet_head_uses_existing_cooldown_and_affection(self):
        exp = self.model.data.affection_exp
        pos = self.panel.room.pet_center().toPoint()
        QTest.mouseClick(self.panel.room, Qt.MouseButton.RightButton, pos=pos)
        self.assertEqual(self.model.data.affection_exp, exp + 3)
        QTest.mouseClick(self.panel.room, Qt.MouseButton.RightButton, pos=pos)
        self.assertEqual(self.model.data.affection_exp, exp + 3)

    def test_feeding_shelf_consumes_owned_food_and_rescues_real_flatness(self):
        self.model.set_hunger(0)
        self.model.buy_item("sesame")
        self.panel.refresh()
        button = self.panel.feeding_buttons["sesame"]
        self.assertTrue(button.isEnabled())
        self.assertIn("1", button.text())
        exp = self.model.data.affection_exp
        button.click()
        self.assertEqual(self.model.data.inventory["sesame"], 0)
        self.assertEqual(self.model.data.hunger, 35)
        self.assertEqual(self.model.data.affection_exp, exp)
        self.assertFalse(self.pet.engine.starving)
        self.assertEqual(self.pet.engine.buff["scale"], 1.2)
        self.assertFalse(self.pet.isVisible())

    def test_all_five_navigation_drawers_keep_room_visible(self):
        for section in ("bag", "shop", "dress", "achievements", "home"):
            with self.subTest(section=section):
                self.panel.nav_buttons[section].click()
                QTest.qWait(20)
                self.assertTrue(self.panel.room.isVisible())
                self.assertGreater(self.panel.room.height(), 120)
        QTest.qWait(200)
        self.assertTrue(self.panel.drawer.isHidden())
        self.assertFalse(self.panel.drawer.isWindow())

    def test_furniture_request_updates_canvas_and_achievement(self):
        self.model.buy_furniture("warm_lamp")
        self.panel.furniture_requested.emit("corner", "warm_lamp")
        self.assertEqual(self.model.data.equipped_furniture["corner"], "warm_lamp")
        self.assertFalse(self.panel.room.lamp_rect().isEmpty())
        pos = self.panel.room.lamp_rect().center().toPoint()
        self.assertTrue(self.model.data.lamp_on)
        QTest.mouseClick(self.panel.room, Qt.MouseButton.LeftButton, pos=pos)
        self.assertFalse(self.model.data.lamp_on)

    def test_close_hides_dashboard_but_keeps_raising_running(self):
        self.controller.tick_timer.start(1000)
        self.panel.close()
        self.assertFalse(self.panel.isVisible())
        self.assertFalse(self.controller._stopped)
        self.assertTrue(self.controller.tick_timer.isActive())
        self.controller.dashboard_action.trigger()
        self.assertTrue(self.panel.isVisible())

    def test_shop_keeps_food_gifts_and_permanent_trick_beside_furniture(self):
        self.panel.show_section("shop")
        self.assertEqual(self.panel.market_tabs.count(), 3)
        self.assertEqual([self.panel.shop_tabs.tabText(i) for i in range(2)], ["食物", "礼物"])
        self.assertEqual(set(self.panel.shop_buttons), set(self.model.catalog.items))
        self.assertIn("screen_roll", self.panel.shop_trick_buttons)


if __name__ == "__main__":
    unittest.main(verbosity=2)
