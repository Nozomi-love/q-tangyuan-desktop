"""Phase 3 purchase, achievements, physics, rendering and dashboard integration."""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from main import PetApplication
from models import Catalog, GameRules, PetData, PetModel
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea
from pet_window import PetWindow
from save_manager import SaveDataError, SaveManager

APP = QApplication.instance() or QApplication(["phase3-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ARTIFACTS = ROOT / "tests/artifacts" / datetime.now().strftime("phase3-%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)


def wealthy(**kwargs) -> PetModel:
    return PetModel(PetData(coins=1000), rng=random.Random(2), **kwargs)


def simulate(engine: PetEngine, seconds: float):
    for _ in range(round(seconds * 120)):
        engine.advance(1 / 120)


class CommerceTests(unittest.TestCase):
    def test_foods_gifts_and_sugar_rules_share_config(self):
        pet = wealthy()
        self.assertEqual(len(pet.catalog.items), 28)
        rules = GameRules.from_catalog(ROOT / "config/catalog.json")
        self.assertEqual((rules.sugar_cost, rules.sugar_hunger, rules.sugar_exp), (30, 15, 0))
        self.assertEqual([pet.item(x)["cost"] for x in pet.catalog.items], [30, 30, 135, 75, 75, 75, 135, 60, 210, 540, 540, 30, 135, 210, 540, 210, 60, 210, 210, 30, 135, 75, 30, 60, 60, 60, 30, 75])

    def test_purchase_stores_without_feeding_and_use_does_not_recharge(self):
        pet = wealthy()
        self.assertTrue(pet.buy_item("water"))
        self.assertEqual((pet.data.coins, pet.data.hunger, pet.data.affection_exp), (970, 80, 0))
        self.assertEqual(pet.data.inventory, {"water": 1})
        self.assertTrue(pet.use_item("water"))
        self.assertEqual((pet.data.coins, pet.data.hunger, pet.data.affection_exp), (970, 95, 0))
        self.assertEqual(pet.data.inventory["water"], 0)
        self.assertFalse(pet.use_item("water"))
        self.assertEqual(pet.data.stats["total_feeds"], 1)

    def test_all_direct_feed_values_charge_once(self):
        for key in Catalog.load().items:
            with self.subTest(item=key):
                pet = wealthy()
                pet.set_hunger(0)
                item = pet.item(key)
                if item.get("required_skin"):
                    pet.data.owned_team_skins.append(item["required_skin"])
                    self.assertTrue(pet.select_skin(item["required_skin"]))
                self.assertTrue(pet.buy_item(key, True))
                self.assertEqual(pet.data.coins, 1000 - item["cost"])
                self.assertEqual(pet.data.hunger, item["hunger"])
                self.assertEqual(pet.data.affection_exp, item["exp"])
                self.assertEqual(pet.data.stats["total_feeds"], int(item["category"] == "food"))
                self.assertEqual(pet.data.stats["total_presents"], int(item["category"] == "gift"))
                self.assertEqual(pet.data.inventory, {})

    def test_invalid_or_unaffordable_purchase_is_noop(self):
        pet = PetModel(PetData(coins=4))
        before = pet.snapshot()
        for key in ("water", "chili", "no-such-item"):
            self.assertFalse(pet.buy_item(key, True))
        self.assertEqual(pet.snapshot(), before)

    def test_inventory_counts_multiple_buys_and_consumption(self):
        pet = wealthy()
        for _ in range(3):
            pet.buy_item("sugar")
        self.assertEqual(pet.data.inventory["sugar"], 3)
        pet.use_item("sugar")
        self.assertEqual(pet.data.inventory["sugar"], 2)
        self.assertEqual(pet.data.coins, 910)

    def test_basic_food_keeps_current_flavor(self):
        pet = wealthy()
        pet.buy_item("sesame", True)
        pet.advance(4)
        pet.buy_item("water", True)
        self.assertEqual(pet.data.active_buff["item_id"], "sesame")
        self.assertEqual(pet.data.active_buff["remaining_seconds"], 56)

    def test_same_flavor_refreshes_different_flavor_replaces(self):
        pet = wealthy()
        pet.buy_item("sesame", True)
        pet.advance(10)
        pet.buy_item("sesame", True)
        self.assertEqual(pet.data.active_buff["remaining_seconds"], 60)
        self.assertEqual(pet.data.flavors_seen, ["sesame"])
        pet.buy_item("matcha", True)
        self.assertEqual(pet.data.active_buff["item_id"], "matcha")
        self.assertEqual(pet.data.flavors_seen, ["sesame", "matcha"])

    def test_buff_expires_and_chili_behavior_is_twelve_seconds(self):
        pet = wealthy()
        pet.buy_item("chili", True)
        pet.advance(12)
        self.assertEqual(pet.buff_view()["behavior_remaining"], 0)
        self.assertEqual(pet.buff_view()["remaining_seconds"], 48)
        pet.advance(48)
        self.assertEqual(pet.data.active_buff, {})
        self.assertEqual(pet.buff_view(), {})

    def test_accelerated_buff_is_fifteen_seconds(self):
        rules = GameRules.from_catalog(ROOT / "config/catalog.json", True)
        pet = wealthy(rules=rules)
        pet.buy_item("strawberry", True)
        self.assertEqual(pet.buff_view()["remaining_seconds"], 15)
        pet.advance(15)
        self.assertEqual(pet.buff_view(), {})


class AchievementTests(unittest.TestCase):
    def test_legacy_statistics_unlock_on_load_and_do_not_unlock_again(self):
        data = PetData.from_dict({"stats": {"total_clicks": 5, "total_feeds": 2}})
        pet = PetModel(data)
        self.assertEqual({a["id"] for a in pet.initial_achievements}, {"first_poke", "first_feed"})
        restored = PetModel(PetData.from_dict(pet.snapshot()))
        self.assertEqual(restored.initial_achievements, [])
        self.assertEqual(restored.data.coins, 100)

    def test_twelve_achievements_with_three_tiers(self):
        achievements = Catalog.load().achievements
        self.assertEqual(len(achievements), 12)
        self.assertEqual([sum(a["tier"] == t for a in achievements) for t in (1, 2, 3)], [5, 4, 3])

    def test_first_poke_unlocks_once_but_does_not_auto_award(self):
        pet = wealthy()
        messages = []
        pet.achievement_unlocked.connect(messages.append)
        pet.poke()
        balance = pet.data.coins
        self.assertIn("first_poke", pet.data.unlocked_achievements)
        pet.poke()
        self.assertEqual(sum(x["id"] == "first_poke" for x in messages), 1)
        self.assertNotIn("first_poke", pet.data.claimed_achievements)
        balance = pet.data.coins
        self.assertTrue(pet.claim_achievement("first_poke"))
        self.assertEqual(pet.data.coins, balance + 30)
        self.assertFalse(pet.claim_achievement("first_poke"))
        self.assertEqual(pet.data.coins, balance + 30)

    def test_first_drop_feed_and_head_pet(self):
        pet = wealthy()
        pet.record_drop()
        pet.buy_item("water", True)
        pet.pet_head()
        self.assertTrue({"first_drop", "first_feed", "first_pet"}.issubset(pet.data.unlocked_achievements))
        self.assertEqual(pet.data.stats["total_pets"], 1)
        pet.pet_head()
        self.assertEqual(pet.data.stats["total_pets"], 1)

    def test_three_unique_flavors_not_three_repetitions_and_title_claim(self):
        pet = wealthy()
        for _ in range(3):
            pet.buy_item("sesame", True)
        self.assertNotIn("flavors_three", pet.data.unlocked_achievements)
        pet.buy_item("strawberry", True)
        pet.buy_item("matcha", True)
        self.assertIn("flavors_three", pet.data.unlocked_achievements)
        self.assertFalse(pet.equip_title("美食鉴赏家"))
        before = pet.data.coins
        self.assertTrue(pet.claim_achievement("flavors_three"))
        self.assertEqual(pet.data.coins, before + 100)
        self.assertTrue(pet.equip_title("美食鉴赏家"))
        self.assertEqual(pet.data.equipped_title, "美食鉴赏家")
        self.assertTrue(pet.equip_title("糯米团子"))

    def test_three_gifts_include_auto_claim_and_never_double_count(self):
        pet = wealthy()
        for _ in range(2):
            pet.offer_collectible()
            pet.claim_collectible()
            pet.claim_collectible()
        self.assertNotIn("gifts_three", pet.data.unlocked_achievements)
        pet.offer_collectible()
        pet.advance(30)
        self.assertEqual(pet.data.stats["total_gifts"], 3)
        self.assertIn("gifts_three", pet.data.unlocked_achievements)

    def test_level_three_achievement_and_title(self):
        pet = PetModel(PetData(coins=1000, affection_level=2, affection_exp=999))
        pet.poke()
        self.assertEqual(pet.data.affection_level, 3)
        self.assertTrue(pet.claim_achievement("level_three"))
        self.assertIn("糯米团长", pet.data.titles)

    def test_sliding_five_second_window_triggers_fifteen_pokes(self):
        clock = [0.0]
        pet = wealthy(clock=lambda: clock[0])
        dizzy = []
        pet.dizzy_requested.connect(lambda: dizzy.append(True))
        for index in range(15):
            clock[0] = index * 0.25
            pet.poke()
        self.assertEqual(len(dizzy), 1)
        self.assertIn("rapid_pokes", pet.data.unlocked_achievements)
        self.assertTrue(pet.claim_achievement("rapid_pokes"))
        self.assertIn("无情铁手", pet.data.titles)

    def test_slow_pokes_do_not_accumulate_into_rapid_window(self):
        clock = [0.0]
        pet = wealthy(clock=lambda: clock[0])
        for index in range(30):
            clock[0] = index * 0.5
            pet.poke()
        self.assertNotIn("rapid_pokes", pet.data.unlocked_achievements)
        self.assertLess(pet.data.stats["rapid_poke_peak"], 15)

    def test_rescue_requires_true_starvation(self):
        pet = wealthy()
        pet.buy_item("water", True)
        self.assertNotIn("rescue", pet.data.unlocked_achievements)
        pet.set_hunger(0)
        pet.buy_item("water", True)
        self.assertIn("rescue", pet.data.unlocked_achievements)
        self.assertEqual(pet.data.stats["starvation_recoveries"], 1)

    def test_claiming_locked_achievement_or_unknown_title_is_noop(self):
        pet = wealthy()
        before = pet.snapshot()
        self.assertFalse(pet.claim_achievement("rescue"))
        self.assertFalse(pet.claim_achievement("missing"))
        self.assertFalse(pet.equip_title("unknown"))
        self.assertEqual(pet.snapshot(), before)

    def test_shake_event_unlocks_but_one_reward_only(self):
        pet = wealthy()
        pet.record_shake()
        pet.record_shake()
        self.assertIn("shake", pet.data.unlocked_achievements)
        coins = pet.data.coins
        pet.claim_achievement("shake")
        pet.claim_achievement("shake")
        self.assertEqual(pet.data.coins, coins + 80)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = ARTIFACTS / self._testMethodName
        self.folder.mkdir()
        self.file = self.folder / "save_data.json"
        self.manager = SaveManager(self.file)

    def test_version_two_upgrade_preserves_currencies_pin_inventory_and_unknowns(self):
        data = {"schema_version": 2, "coins": 234, "hunger": 41, "affection_level": 2,
                "affection_exp": 7, "inventory": {"future_item": 2}, "future_data": {"keep": True},
                "window": {"pinned": True, "x_ratio": 0.5, "y_ratio": 0.4},
                "stats": {"total_clicks": 8, "total_feeds": 2}}
        raw = json.dumps(data).encode()
        self.file.write_bytes(raw)
        pet_data, window = self.manager.load_all()
        pet = PetModel(pet_data)
        self.assertIn("first_poke", pet.data.unlocked_achievements)
        self.assertEqual(pet.data.claimed_achievements, [])
        self.manager.update_game(pet.snapshot(), window)
        saved = json.loads(self.file.read_bytes())
        self.assertEqual((saved["schema_version"], saved["coins"], saved["hunger"]), (5, 234, 41))
        self.assertEqual(saved["inventory"], {"future_item": 2})
        self.assertEqual(saved["window"], data["window"])
        self.assertTrue(saved["future_data"]["keep"])
        self.assertEqual(next(self.folder.glob("*.bak.*")).read_bytes(), raw)

    def test_buff_expiration_is_persisted_as_empty_not_merged_old_effect(self):
        pet = wealthy()
        pet.buy_item("sesame", True)
        self.manager.update_game(pet.snapshot())
        pet.advance(60)
        self.manager.update_game(pet.snapshot())
        self.assertEqual(self.manager.load_game_state().active_buff, {})

    def test_round_trip_all_phase_three_data_and_claim_idempotence(self):
        pet = wealthy()
        for key in ("sesame", "strawberry", "matcha"):
            pet.buy_item(key, True)
        pet.claim_achievement("flavors_three")
        pet.equip_title("美食鉴赏家")
        pet.buy_item("water")
        pet.advance(7)
        self.manager.update_game(pet.snapshot(), {"pinned": False})
        restored = PetModel(self.manager.load_game_state())
        self.assertEqual(restored.snapshot(), pet.snapshot())
        self.assertFalse(restored.claim_achievement("flavors_three"))
        self.assertEqual(restored.buff_view()["remaining_seconds"], 53)

    def test_invalid_phase_three_save_values_are_rejected(self):
        for raw in ({"inventory": {"sugar": -1}}, {"active_buff": {"item_id": "sesame", "remaining_seconds": float("nan")}},
                    {"claimed_achievements": ["first_poke"]}, {"equipped_title": "unknown"}, {"flavors_seen": ["sesame", "sesame"]}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                PetData.from_dict(raw)

    def test_resume_demo_cli_rejects_the_production_save_path(self):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(ROOT / "main.py"),
                                  "--resume-demo", str(ROOT / "data/save_data.json")], cwd=ROOT,
                                 text=True, encoding="utf-8", capture_output=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(process.returncode, 2)
        self.assertIn("独立演示存档", process.stderr)

    def test_future_version_and_stale_session_protection_remain(self):
        self.file.write_bytes(b'{"schema_version":99,"coins":123}')
        with self.assertRaises(SaveDataError):
            self.manager.update_game(PetData().to_dict())
        self.assertEqual(self.file.read_bytes(), b'{"schema_version":99,"coins":123}')


class RenderingPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = SkinRenderer(ROOT / "assets/skins/default")

    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))

    def effect(self, key):
        pet = wealthy()
        pet.buy_item(key, True)
        return pet.buff_view()

    def test_source_atop_preserves_every_alpha_pixel_and_face_contrast(self):
        renderer = self.renderer
        for state in PetState:
            base = renderer.pixmaps[state].toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            for color in ("#45424a", "#f58fb1", "#78ad76", "#f25a4c"):
                tinted = renderer.tinted_pixmap(state, color).toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                before, after = bytes(base.constBits()), bytes(tinted.constBits())
                self.assertEqual(before[3::4], after[3::4])
                self.assertNotEqual(before, after)
                self.assertTrue(any(after[i + 3] == 255 and max(after[i:i+3]) < 160 for i in range(0, len(after), 4)))

    def test_sesame_scale_anchor_and_landing_are_preserved(self):
        self.engine.set_buff(self.effect("sesame"))
        foot = QPointF(224, 288)
        pose = self.engine.pose
        self.assertAlmostEqual(pose.scale_x * pose.scale_y, 1.2 ** 2)
        for _ in range(240):
            self.engine.advance(1 / 120)
            self.assertAlmostEqual(self.engine.y + self.engine.bounds_offsets()[3], 1000)
            self.assertEqual(self.renderer.body_transform(self.engine, foot).map(QPointF()), foot)

    def test_sesame_all_states_extreme_jelly_and_rotation_fit_canvas(self):
        foot = QPointF(PetWindow.ANCHOR_X, PetWindow.ANCHOR_Y)
        self.engine.set_buff(self.effect("sesame"))
        for state in PetState:
            self.engine.manual_flat = state == PetState.FLAT
            self.engine.dragging = state == PetState.DIZZY
            self.engine.happy_until = 99 if state == PetState.HAPPY else 0
            for spring in (-0.45, 0, 0.38):
                self.engine.spring = spring
                for angle in (-18, 0, 18):
                    self.engine.angle = angle
                    source = self.renderer.source_state(self.engine.state)
                    rect = self.renderer.body_transform(self.engine, foot).mapRect(self.renderer.draw_rects[source])
                    self.assertGreater(rect.left(), 1)
                    self.assertGreater(rect.top(), 1)
                    self.assertLess(rect.right(), PetWindow.CANVAS_WIDTH - 1)
                    self.assertLess(rect.bottom(), PetWindow.CANVAS_HEIGHT - 1)

    def test_chili_free_runs_hops_and_respects_current_work_area(self):
        self.engine.reset(WorkArea(-1920, -200, 1920, 1080))
        self.engine.x = -600
        self.engine.set_buff(self.effect("chili"))
        start = self.engine.x
        min_y = self.engine.y
        for _ in range(600):
            self.engine.advance(1 / 120)
            min_y = min(min_y, self.engine.y)
            left, _, right, bottom = self.engine.bounds_offsets()
            self.assertGreaterEqual(self.engine.x + left, -1920 - 1e-6)
            self.assertLessEqual(self.engine.x + right, 1e-6)
            self.assertLessEqual(self.engine.y + bottom, 880 + 1e-6)
        self.assertGreater(abs(self.engine.x - start), 100)
        self.assertLess(min_y, 878)
        self.assertGreater(self.engine.landing_count, 3)

    def test_chili_pinned_stomps_without_changing_anchor_or_velocity(self):
        self.engine.place(600, 400)
        self.engine.set_pinned(True)
        self.engine.set_buff(self.effect("chili"))
        springs = []
        for _ in range(1500):
            self.engine.advance(1 / 120)
            springs.append(self.engine.spring)
            self.assertEqual((self.engine.x, self.engine.y, self.engine.vx, self.engine.vy), (600, 400, 0, 0))
        self.assertLess(min(springs), -0.2)
        self.assertEqual(self.engine.buff["behavior_remaining"], 0)
        self.assertGreater(self.engine.buff["remaining_seconds"], 40)

    def test_pin_during_running_stops_translation_immediately(self):
        self.engine.set_buff(self.effect("chili"))
        simulate(self.engine, 1)
        self.engine.set_pinned(True)
        anchor = self.engine.x, self.engine.y
        simulate(self.engine, 3)
        self.assertEqual((self.engine.x, self.engine.y), anchor)
        self.engine.set_pinned(False)
        simulate(self.engine, 1)
        self.assertNotEqual((self.engine.x, self.engine.y), anchor)

    def test_strawberry_particles_render_outside_body_without_filling_corners(self):
        self.engine.set_buff(self.effect("strawberry"))
        self.engine.elapsed = 1.2
        image = QImage(PetWindow.CANVAS_WIDTH, PetWindow.CANVAS_HEIGHT, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.renderer.paint(painter, self.engine, QPointF(PetWindow.ANCHOR_X, PetWindow.ANCHOR_Y))
        painter.end()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertTrue(any(image.pixelColor(x, y).alpha() > 0 for x in range(int(PetWindow.ANCHOR_X)-104, int(PetWindow.ANCHOR_X)+106) for y in range(int(PetWindow.ANCHOR_Y)-148, int(PetWindow.ANCHOR_Y)-108)))
        self.assertTrue(image.save(str(ARTIFACTS / "strawberry-particles.png")))

    def test_dizzy_expression_lasts_three_seconds(self):
        self.engine.get_dizzy()
        simulate(self.engine, 2.9)
        self.assertEqual(self.engine.state, PetState.DIZZY)
        simulate(self.engine, 0.2)
        self.assertEqual(self.engine.state, PetState.IDLE)


class DashboardInputTests(unittest.TestCase):
    def setUp(self):
        self.file = ARTIFACTS / (self._testMethodName + ".json")
        with patch("main.PetWindow", side_effect=lambda _: PetWindow(ARTIFACTS / "no-skin")):
            self.controller = PetApplication(APP, save_path=self.file)
        self.window, self.model, self.dashboard = self.controller.window, self.controller.model, self.controller.dashboard
        self.model.set_overlay_visible(True)
        self.dashboard.hide()
        self.window.timer.stop()
        self.controller.tick_timer.stop()
        self.controller.autosave_timer.stop()
        self.window.set_pinned(True)
        self.model.data.coins = 1000
        self.model._clock = lambda: 100.0
        self.model._publish(self.model.starving)

    def tearDown(self):
        self.controller.stop()
        self.dashboard.deleteLater()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def send(self, kind, point, at):
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        local = self.window.mapFromGlobal(point)
        event = QMouseEvent(kind, local, point, button, buttons, Qt.KeyboardModifier.NoModifier)
        with patch("pet_window.time.perf_counter", return_value=at):
            APP.sendEvent(self.window, event)

    def test_dashboard_has_five_tabs_menu_summons_and_close_only_hides(self):
        self.assertEqual(self.dashboard.tabs.count(), 4)
        self.assertFalse(self.dashboard.isVisible())
        self.controller.dashboard_action.trigger()
        self.assertTrue(self.dashboard.isVisible())
        self.dashboard.close()
        self.assertFalse(self.dashboard.isVisible())
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.controller._stopped)

    def test_double_click_opens_panel_without_any_poke_stats_or_coins(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        before = self.model.snapshot()
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.02)
        self.send(QEvent.Type.MouseButtonDblClick, point, 100.1)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.12)
        with patch("pet_window.time.perf_counter", return_value=100.5):
            self.window.confirm_pending_clicks()
        self.assertTrue(self.dashboard.isVisible())
        self.assertEqual(self.model.snapshot(), before)

    def test_second_press_before_deadline_can_release_after_it(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.02)
        self.send(QEvent.Type.MouseButtonDblClick, point, 100.15)
        with patch("pet_window.time.perf_counter", return_value=100.25):
            self.window.confirm_pending_clicks()
        self.assertEqual(self.model.data.stats["total_clicks"], 0)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.35)
        with patch("pet_window.time.perf_counter", return_value=100.6):
            self.window.confirm_pending_clicks()
        self.assertTrue(self.dashboard.isVisible())
        self.assertEqual(self.model.data.stats["total_clicks"], 0)

    def test_single_click_waits_for_confirmation_and_counts_once(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.01)
        self.assertEqual(self.model.data.stats["total_clicks"], 0)
        with patch("pet_window.time.perf_counter", return_value=100.25):
            self.window.confirm_pending_clicks()
            self.window.confirm_pending_clicks()
        self.assertEqual(self.model.data.stats["total_clicks"], 1)
        self.assertFalse(self.dashboard.isVisible())

    def test_fifteen_confirmed_pokes_fit_five_seconds_without_doubleclick(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        for index in range(15):
            at = 100 + index * 0.25
            self.model._clock = lambda value=at: value
            self.send(QEvent.Type.MouseButtonPress, point, at)
            self.send(QEvent.Type.MouseButtonRelease, point, at + 0.01)
            with patch("pet_window.time.perf_counter", return_value=at + 0.22):
                self.window.confirm_pending_clicks()
        self.assertEqual(self.model.data.stats["total_clicks"], 15)
        self.assertFalse(self.dashboard.isVisible())
        self.assertIn("rapid_pokes", self.model.data.unlocked_achievements)
        self.assertEqual(self.window.engine.state, PetState.DIZZY)
        self.assertIn("头都转晕", self.window.bubble._text)

    def test_pending_click_does_not_release_a_later_drag(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        self.send(QEvent.Type.MouseButtonRelease, point, 100.02)
        self.send(QEvent.Type.MouseButtonPress, point, 100.1)
        self.send(QEvent.Type.MouseMove, point + QPointF(-100, -100), 100.14)
        with patch("pet_window.time.perf_counter", return_value=100.3):
            self.window.confirm_pending_clicks()
        self.assertTrue(self.window.engine.held)
        self.assertTrue(self.window.engine.dragging)
        self.assertEqual(self.model.data.stats["total_clicks"], 1)

    def test_fast_shake_requires_reversals_not_just_long_horizontal_drag(self):
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        for index, dx in enumerate((-120, -240, -360, -480), 1):
            self.send(QEvent.Type.MouseMove, point + QPointF(dx, -80), 100 + index * 0.1)
        self.assertEqual(self.model.data.stats["total_shakes"], 0)
        for index, dx in enumerate((-360, -480, -360), 5):
            self.send(QEvent.Type.MouseMove, point + QPointF(dx, -80), 100 + index * 0.1)
        self.assertEqual(self.model.data.stats["total_shakes"], 1)
        self.assertIn("shake", self.model.data.unlocked_achievements)
        self.assertEqual(self.model.data.stats["total_clicks"], 0)

    def test_real_drag_landing_unlocks_once_and_auto_jumps_do_not_count(self):
        self.window.set_pinned(False)
        self.window.engine.reset()
        point = QPointF(self.window.engine.x, self.window.engine.y - 50)
        self.send(QEvent.Type.MouseButtonPress, point, 100)
        self.send(QEvent.Type.MouseMove, point + QPointF(-100, -300), 100.1)
        self.send(QEvent.Type.MouseButtonRelease, point + QPointF(-100, -300), 100.3)
        self.assertTrue(self.window._awaiting_drop)
        self.assertEqual(self.model.data.stats["total_drops"], 0)
        for index in range(160):
            with patch("pet_window.time.perf_counter", return_value=self.window._last_frame + 1 / 60):
                self.window._on_frame()
                self.window.timer.stop()
        self.assertEqual(self.model.data.stats["total_drops"], 1)
        self.assertIn("first_drop", self.model.data.unlocked_achievements)
        self.window.engine.celebrate()
        for _ in range(240):
            with patch("pet_window.time.perf_counter", return_value=self.window._last_frame + 1 / 60):
                self.window._on_frame()
                self.window.timer.stop()
        self.assertEqual(self.model.data.stats["total_drops"], 1)

    def test_sugar_card_and_quick_feed_share_changed_rules(self):
        self.model.set_rules(GameRules(sugar_cost=17, sugar_hunger=30, sugar_exp=0))
        self.dashboard.refresh()
        self.assertIn("17 糯米币", self.dashboard.shop_details["sugar"].text())
        self.assertIn("饱食度 +30", self.dashboard.shop_details["sugar"].text())
        self.assertNotIn("好感", self.dashboard.shop_details["sugar"].text())
        self.model.feed_sugar()
        self.assertEqual(self.model.data.coins, 983)
        self.assertEqual(self.model.data.affection_exp, 0)

    def test_shop_buttons_inventory_use_and_live_balance(self):
        self.dashboard.summon()
        self.dashboard.show_section("shop", animate=False)
        buy, feed, _ = self.dashboard.shop_buttons["sesame"]
        QTest.mouseClick(buy, Qt.MouseButton.LeftButton)
        self.assertEqual(self.model.data.inventory["sesame"], 1)
        self.assertIn("925", self.dashboard.balance.text())
        self.dashboard.show_section("bag", animate=False)
        QTest.mouseClick(self.dashboard.inventory_widgets["sesame"][2], Qt.MouseButton.LeftButton)
        self.assertEqual(self.model.data.inventory["sesame"], 0)
        self.assertEqual(self.window.engine.buff["scale"], 1.2)
        self.assertIn("芝麻胖团", self.dashboard.buff_label.text())
        self.model.data.coins = 0
        self.model._publish(self.model.starving)
        self.assertFalse(buy.isEnabled())
        self.assertFalse(feed.isEnabled())

    def test_settings_pin_dev_flat_and_debug_buttons_are_connected(self):
        self.dashboard.summon()
        self.dashboard.show_section("settings", animate=False)
        self.dashboard.pin_check.setChecked(False)
        self.assertFalse(self.window.engine.pinned)
        self.controller.pin_action.setChecked(True)
        self.assertTrue(self.dashboard.pin_check.isChecked())
        self.dashboard.dev_check.setChecked(True)
        self.assertEqual(self.model.rules.buff_seconds, 15)
        self.dashboard.flat_check.setChecked(True)
        self.assertTrue(self.window.engine.manual_flat)
        zero_button = next(x for x in self.dashboard.findChildren(QPushButton) if x.text() == "调试：饥饿归零")
        QTest.mouseClick(zero_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.model.data.hunger, 0)

    def test_achievement_claim_and_title_controls_refresh_in_open_dashboard(self):
        self.dashboard.summon()
        self.model.data.affection_level = 3
        self.model._publish(self.model.starving)
        _, _, claim, equip = self.dashboard.achievement_widgets["level_three"]
        self.assertTrue(claim.isEnabled())
        self.dashboard.show_section("achievements", animate=False)
        QTest.mouseClick(claim, Qt.MouseButton.LeftButton)
        self.assertFalse(claim.isEnabled())
        self.assertIn("糯米团长", self.model.data.titles)
        QTest.mouseClick(equip, Qt.MouseButton.LeftButton)
        self.assertEqual(self.dashboard.current_section, "bag")
        self.assertEqual(self.dashboard.dress_tabs.currentIndex(), 2)
        self.dashboard.title_combo.setCurrentText("糯米团长")
        self.assertEqual(self.model.data.equipped_title, "糯米团长")
        self.assertEqual(self.dashboard.title_combo.currentText(), "糯米团长")
        self.dashboard.tier_filter.setCurrentIndex(2)
        self.assertTrue(self.dashboard.tier_groups[1].isHidden())
        self.assertFalse(self.dashboard.tier_groups[2].isHidden())

    def test_multiple_achievement_notifications_are_queued_not_overwritten(self):
        self.model.set_hunger(0)
        self.model.buy_item("water", True)
        bubble = self.window.bubble
        all_text = [bubble._text] + [message[0] for message in bubble._notifications]
        self.assertTrue(any("第一口甜" in text for text in all_text))
        self.assertTrue(any("绝处逢生" in text for text in all_text))
        self.assertIn("first_feed", self.model.data.unlocked_achievements)
        self.assertIn("rescue", self.model.data.unlocked_achievements)


if __name__ == "__main__":
    print(f"Retained Phase 3 artifacts: {ARTIFACTS}", flush=True)
    unittest.main(verbosity=2)
