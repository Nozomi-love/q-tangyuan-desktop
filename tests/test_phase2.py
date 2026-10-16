"""Growth, migration and bubble integration checks; all saves stay in artifacts."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import GameRules, PetData, PetModel
from pet_engine import PetEngine, PetState, WorkArea
from pet_window import PetWindow, SpeechBubble
from save_manager import SaveDataError, SaveManager
from main import PetApplication

APP = QApplication.instance() or QApplication(["phase2-tests"])
APP.setQuitOnLastWindowClosed(False)
ARTIFACTS = ROOT / "tests/artifacts" / datetime.now().strftime("phase2-%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)


class FixedRandom:
    def __init__(self, roll=0.0, amount=13):
        self.roll, self.amount = roll, amount
        self.rolls = 0

    def random(self):
        self.rolls += 1
        return self.roll

    def randint(self, low, high):
        assert low <= self.amount <= high
        return self.amount


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.rng = FixedRandom()
        self.model = PetModel(rng=self.rng)

    def test_initial_values_and_signal_snapshot_is_detached(self):
        self.assertEqual((self.model.data.coins, self.model.data.hunger), (100, 80))
        view = self.model.snapshot()
        view["stats"]["total_feeds"] = 99
        self.assertEqual(self.model.data.stats["total_feeds"], 0)
        events = []
        self.model.state_changed.connect(events.append)
        self.model.poke()
        self.assertEqual(events[-1]["stats"]["total_clicks"], 1)

    def test_satiated_and_hungry_pokes_boundary(self):
        self.model.set_hunger(50)
        self.model.poke()
        self.assertEqual(self.model.data.affection_exp, 2)
        self.model.set_hunger(49)
        self.model.poke()
        self.assertEqual(self.model.data.affection_exp, 3)

    def test_first_twenty_clicks_are_opportunities_not_twenty_successes(self):
        self.rng.roll = 1.0
        for _ in range(30):
            self.model.poke()
        self.assertEqual(self.rng.rolls, 20)
        self.assertEqual(self.model.data.daily_stats["poke_attempts"], 20)
        self.assertEqual(self.model.data.daily_stats["poke_coin_drops"], 0)
        self.assertEqual(self.model.data.stats["total_clicks"], 30)

    def test_drop_probability_strict_boundary_and_two_coin_award(self):
        self.rng.roll = 0.349999
        self.model.poke()
        self.assertEqual(self.model.data.coins, 102)
        self.rng.roll = 0.35
        self.model.poke()
        self.assertEqual(self.model.data.coins, 102)
        self.assertEqual(self.model.data.daily_stats["poke_coin_drops"], 1)

    def test_daily_reset_uses_calendar_day_and_keeps_totals(self):
        now = [date(2026, 10, 16)]
        pet = PetModel(rng=self.rng, today=lambda: now[0])
        for _ in range(20):
            pet.poke()
        now[0] += timedelta(days=1)
        pet.poke()
        self.assertEqual(pet.data.daily_stats["poke_attempts"], 1)
        self.assertEqual(pet.data.daily_stats["poke_coin_drops"], 1)
        self.assertEqual(pet.data.stats["total_clicks"], 21)

    def test_hunger_drops_only_after_full_three_minutes(self):
        self.model.advance(179.9)
        self.assertEqual(self.model.data.hunger, 80)
        self.model.advance(0.1)
        self.assertEqual(self.model.data.hunger, 79)
        self.assertAlmostEqual(self.model.data.stats["total_idle_seconds"], 180)

    def test_zero_hunger_never_loses_levels_exp_or_coins(self):
        self.model.data.affection_level = 3
        self.model.data.affection_exp = 7
        events = []
        self.model.starvation_changed.connect(events.append)
        self.model.set_hunger(1)
        self.model.advance(180)
        self.assertTrue(self.model.starving)
        self.assertEqual(events, [True])
        self.model.advance(360)
        self.assertEqual(self.model.data.affection_level, 3)
        self.assertGreaterEqual(self.model.data.affection_exp, 7)
        self.assertGreaterEqual(self.model.data.coins, 100)
        self.assertEqual(self.model.data.hunger, 0)

    def test_starving_notices_repeat_without_mutating_affection(self):
        messages = []
        self.model.feedback.connect(lambda text, tone: messages.append((text, tone)))
        self.model.set_hunger(0)
        self.model.advance(45)
        self.assertEqual(sum("糯米饼" in x[0] for x in messages), 2)
        self.assertEqual(self.model.data.affection_exp, 0)

    def test_sugar_purchase_feed_recovery_and_statistics(self):
        states = []
        self.model.starvation_changed.connect(states.append)
        self.model.set_hunger(0)
        self.assertTrue(self.model.feed_sugar())
        self.assertEqual((self.model.data.coins, self.model.data.hunger, self.model.data.affection_exp), (90, 25, 10))
        self.assertEqual(self.model.data.stats["total_feeds"], 1)
        self.assertEqual(states, [True, False])
        self.model.set_hunger(99)
        self.model.feed_sugar()
        self.assertEqual(self.model.data.hunger, 100)

    def test_insufficient_coins_changes_no_stats_or_values(self):
        self.model.data.coins = 9
        before = self.model.snapshot()
        self.assertFalse(self.model.feed_sugar())
        self.assertEqual(before, self.model.snapshot())

    def test_pet_head_cooldown_and_exp(self):
        self.assertTrue(self.model.pet_head())
        self.assertFalse(self.model.pet_head())
        self.assertEqual(self.model.data.affection_exp, 3)
        self.model.advance(9.99)
        self.assertFalse(self.model.pet_head())
        self.model.advance(0.01)
        self.assertTrue(self.model.pet_head())
        self.assertEqual(self.model.data.affection_exp, 6)

    def test_level_up_remainder_award_and_signal(self):
        pet = PetModel(PetData(affection_exp=49), rng=FixedRandom(1))
        levels = []
        pet.upgraded.connect(levels.append)
        pet.poke()
        self.assertEqual((pet.data.affection_level, pet.data.affection_exp, pet.data.coins), (2, 1, 130))
        self.assertEqual(levels, [2])

    def test_max_level_stops_exp_and_repeated_upgrade_rewards(self):
        pet = PetModel(PetData(affection_level=29, affection_exp=1449), rng=FixedRandom(1))
        pet.poke()
        self.assertEqual((pet.data.affection_level, pet.data.affection_exp, pet.data.coins), (30, 0, 130))
        for _ in range(100):
            pet.poke()
        self.assertEqual((pet.data.affection_level, pet.data.affection_exp, pet.data.coins), (30, 0, 130))

    def test_multiple_levels_from_one_feed_reward_each_level(self):
        pet = PetModel(rules=GameRules(sugar_exp=301))
        levels = []
        pet.upgraded.connect(levels.append)
        pet.feed_sugar()
        self.assertEqual(levels, [2, 3, 4])
        self.assertEqual((pet.data.affection_level, pet.data.affection_exp, pet.data.coins), (4, 1, 180))

    def test_gift_appears_at_ninety_seconds_and_claims_once(self):
        self.model.advance(89.9)
        self.assertFalse(self.model.has_collectible)
        self.model.advance(0.1)
        self.assertTrue(self.model.has_collectible)
        self.assertEqual(self.model.data.coins, 100)
        self.assertTrue(self.model.claim_collectible())
        self.assertFalse(self.model.claim_collectible())
        self.assertEqual((self.model.data.coins, self.model.data.affection_exp), (113, 5))

    def test_gift_timeout_automatically_credits_once(self):
        self.model.advance(90)
        self.model.advance(29.9)
        self.assertEqual(self.model.data.coins, 100)
        self.model.advance(0.1)
        self.assertEqual(self.model.data.coins, 113)
        self.assertFalse(self.model.has_collectible)
        self.model.advance(1)
        self.assertEqual(self.model.data.coins, 113)

    def test_click_pet_claims_gift_plus_poke_without_double_credit(self):
        self.model.offer_collectible()
        self.model.poke()
        self.assertFalse(self.model.has_collectible)
        self.assertEqual((self.model.data.coins, self.model.data.affection_exp), (115, 7))
        self.assertEqual(self.model.data.stats["total_clicks"], 1)

    def test_gift_amount_bounds_across_seeded_samples(self):
        pet = PetModel(rng=random.Random(42))
        seen = set()
        for _ in range(100):
            pet.offer_collectible()
            seen.add(pet.data.pending_reward["coins"])
            pet.claim_collectible()
        self.assertEqual(seen, set(range(10, 21)))

    def test_event_boundary_processing_matches_one_second_steps(self):
        big, small = PetModel(rng=FixedRandom()), PetModel(rng=FixedRandom())
        big.advance(361)
        for _ in range(361):
            small.advance(1)
        self.assertEqual(big.snapshot(), small.snapshot())

    def test_pending_reward_and_partial_timers_survive_model_restart(self):
        self.model.advance(102.5)
        restored = PetModel(PetData.from_dict(self.model.snapshot()), rng=self.rng)
        self.assertAlmostEqual(restored.data.pending_reward["remaining_seconds"], 17.5)
        restored.advance(17.5)
        self.assertEqual(restored.data.coins, 113)
        restored.advance(60)
        self.assertEqual(restored.data.hunger, 79)
        self.assertTrue(restored.has_collectible)

    def test_new_day_on_loading_resets_only_daily_counters(self):
        self.model.poke()
        restored = PetModel(PetData.from_dict(self.model.snapshot()), today=lambda: date.today() + timedelta(days=1))
        self.assertEqual(restored.data.daily_stats["poke_attempts"], 0)
        self.assertEqual(restored.data.stats["total_clicks"], 1)
        self.assertEqual(restored.data.coins, 102)

    def test_invalid_deltas_do_not_modify_model(self):
        before = self.model.snapshot()
        for value in (-1, 0, float("nan"), float("inf")):
            self.model.advance(value)
        self.assertEqual(self.model.snapshot(), before)

    def test_catalog_normal_and_accelerated_intervals(self):
        normal = GameRules.from_catalog(ROOT / "config/catalog.json")
        fast = GameRules.from_catalog(ROOT / "config/catalog.json", True)
        self.assertEqual((normal.hunger_seconds, normal.gift_seconds), (180, 90))
        pet = PetModel(rules=fast)
        pet.advance(10)
        self.assertEqual(pet.data.hunger, 75)
        self.assertTrue(pet.has_collectible)

    def test_gift_lifetime_must_fit_the_persistent_thirty_second_limit(self):
        with self.assertRaises(ValueError):
            GameRules(gift_lifetime=31)

    def test_reset_cancels_queued_level_jumps(self):
        engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        engine.celebrate()
        engine.reset()
        for _ in range(180):
            engine.advance(1 / 60)
        self.assertEqual(engine.landing_count, 0)
        self.assertEqual(engine._celebration_hops, 0)

    def test_bad_growth_values_are_rejected(self):
        for value in ({"coins": True}, {"hunger": float("nan")}, {"hunger": -1},
                      {"affection_level": 31}, {"affection_exp": 50},
                      {"daily_stats": {"date": "bad"}}, {"stats": {"total_clicks": -1}},
                      {"pending_reward": {"coins": 4}}, {"timers": {"coin_elapsed": True}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PetData.from_dict(value)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = ARTIFACTS / self._testMethodName
        self.directory.mkdir()
        self.file = self.directory / "save_data.json"
        self.manager = SaveManager(self.file)

    def test_phase1_upgrade_keeps_position_unknown_fields_and_backup(self):
        original = {"schema_version": 1, "window": {"pinned": True, "screen": "display", "x_ratio": 0.6, "y_ratio": 0.4},
                    "inventory": {"keep": 3}, "stats": {"future_stat": 12}}
        before = json.dumps(original).encode()
        self.file.write_bytes(before)
        pet, position = self.manager.load_all()
        self.manager.update_game(pet.to_dict(), position)
        saved = json.loads(self.file.read_bytes())
        self.assertEqual(saved["schema_version"], 4)
        self.assertEqual(saved["window"], original["window"])
        self.assertEqual(saved["inventory"], original["inventory"])
        self.assertEqual(saved["stats"]["future_stat"], 12)
        self.assertEqual(saved["coins"], 100)
        backups = list(self.directory.glob("save_data.json.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.manager.update_game(pet.to_dict())
        self.assertEqual(len(list(self.directory.glob("save_data.json.bak.*"))), 1)

    def test_game_and_window_writers_preserve_each_other(self):
        self.manager.update_game(PetData(coins=123).to_dict(), {"pinned": False})
        self.manager.update_window({"pinned": True, "screen": "a", "x_ratio": 0.3, "y_ratio": 0.4})
        pet, window = self.manager.load_all()
        self.assertEqual(pet.coins, 123)
        self.assertTrue(window["pinned"])

    def test_stale_game_session_cannot_overwrite_newer_coins(self):
        self.manager.update_game(PetData().to_dict())
        other = SaveManager(self.file)
        other.load_all()
        self.manager.update_game(PetData(coins=987).to_dict())
        before = self.file.read_bytes()
        with self.assertRaises(SaveDataError):
            other.update_game(PetData(coins=101).to_dict())
        self.assertEqual(self.file.read_bytes(), before)

    def test_invalid_game_retains_original_without_backups(self):
        raw = b'{"schema_version":2,"hunger":-5}'
        self.file.write_bytes(raw)
        with self.assertRaises(SaveDataError):
            self.manager.load_all()
        self.assertEqual(self.file.read_bytes(), raw)
        self.assertEqual(list(self.directory.glob("*.bak.*")), [])

    def test_round_trip_keeps_pending_gift_cooldown_and_all_counters(self):
        pet = PetModel(rng=FixedRandom())
        pet.pet_head()
        pet.poke()
        pet.feed_sugar()
        pet.advance(95)
        self.manager.update_game(pet.snapshot())
        restored = PetModel(self.manager.load_game_state(), rng=FixedRandom())
        self.assertEqual(restored.snapshot(), pet.snapshot())
        restored.claim_collectible()
        self.manager.update_game(restored.snapshot())
        self.assertFalse(PetModel(self.manager.load_game_state()).has_collectible)


class UIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.file = ARTIFACTS / (self._testMethodName + ".json")
        with patch("main.PetWindow", side_effect=lambda _: PetWindow(ARTIFACTS / "no-art")):
            self.controller = PetApplication(APP, save_path=self.file)
        self.window = self.controller.window
        self.window.timer.stop()
        self.controller.tick_timer.stop()
        self.controller.autosave_timer.stop()
        self.window.set_pinned(True)
        self.bubble = self.window.bubble

    def tearDown(self):
        self.controller.stop()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_menu_live_status_and_quick_feed_restore_true_flat(self):
        self.controller.hunger_zero_action.trigger()
        self.assertTrue(self.window.engine.starving)
        self.assertEqual(self.window.engine.state, PetState.FLAT)
        self.assertIn("0/100", self.controller.hunger_info.text())
        self.controller.feed_action.trigger()
        self.assertFalse(self.window.engine.flat)
        self.assertEqual(self.window.engine.state, PetState.HAPPY)
        self.assertIn("25/100", self.controller.hunger_info.text())
        self.assertIn("90", self.controller.coins_info.text())
        self.assertLess(self.window.engine.spring, 0)

    def test_manual_flat_cannot_mask_or_clear_true_starvation(self):
        self.controller.flat_action.trigger()
        self.assertEqual(self.controller.model.data.hunger, 80)
        self.controller.hunger_zero_action.trigger()
        self.controller.flat_action.trigger()
        self.assertTrue(self.window.engine.flat)
        self.controller.feed_action.trigger()
        self.assertFalse(self.window.engine.flat)
        self.assertFalse(self.controller.flat_action.isChecked())

    def test_feeding_also_ends_cosmetic_test_flat(self):
        self.controller.flat_action.trigger()
        self.controller.feed_action.trigger()
        self.assertFalse(self.window.engine.flat)
        self.assertFalse(self.controller.flat_action.isChecked())

    def test_starving_stays_flat_during_drag_and_click_does_not_jump(self):
        self.controller.hunger_zero_action.trigger()
        self.window.set_pinned(False)
        self.window.engine.reset()
        self.window.engine.click()
        self.assertEqual(self.window.engine.vy, 0)
        self.window.engine.begin_drag()
        self.assertEqual(self.window.engine.state, PetState.FLAT)
        self.window.engine.release_drag(0, 0)

    def test_level_feedback_has_priority_and_queues_celebration(self):
        self.controller.model.data.affection_exp = 49
        self.controller.model.rng = FixedRandom(1)
        self.window.clicked.emit()
        self.assertEqual(self.controller.model.data.affection_level, 2)
        self.assertEqual(self.window.engine._celebration_hops, 3)
        self.assertIn("Lv.2", self.bubble._text)
        self.window.show_message("普通提示")
        self.assertIn("Lv.2", self.bubble._text)
        anchor = (self.window.engine.x, self.window.engine.y)
        for _ in range(180):
            self.window.engine.advance(1 / 60)
        self.assertEqual(self.window.engine._celebration_hops, 0)
        self.assertEqual((self.window.engine.x, self.window.engine.y), anchor)

    def test_free_mode_level_feedback_really_hops_three_times(self):
        self.window.set_pinned(False)
        self.window.engine.reset()
        self.window.engine.celebrate()
        for _ in range(240):
            self.window.engine.advance(1 / 60)
        self.assertEqual(self.window.engine.landing_count, 3)
        self.assertEqual(self.window.engine._celebration_hops, 0)

    def test_actual_pet_mouse_click_changes_stats_but_drag_does_not(self):
        at = self.window.local_foot() + QPointF(0, -50)
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, pos=at.toPoint())
        QTest.qWait(240)
        self.assertEqual(self.controller.model.data.stats["total_clicks"], 1)
        start = self.window.mapToGlobal(at)
        self.window.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, at, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.window.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, at + QPointF(-30, -40), start + QPointF(-30, -40), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.window.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, at + QPointF(-30, -40), start + QPointF(-30, -40), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.controller.model.data.stats["total_clicks"], 1)

    def test_clickable_bubble_claims_exactly_once_without_pet_poke(self):
        self.controller.model.rng = FixedRandom()
        self.controller.gift_action.trigger()
        self.assertTrue(self.bubble._showing_gift)
        self.assertTrue(self.bubble.isVisible())
        QTest.mouseClick(self.bubble, Qt.MouseButton.LeftButton, pos=self.bubble.rect().center())
        self.assertFalse(self.controller.model.has_collectible)
        self.assertEqual(self.controller.model.data.coins, 113)
        self.assertEqual(self.controller.model.data.stats["total_clicks"], 0)
        self.assertFalse(self.bubble._showing_gift)

    def test_bubble_stays_on_work_area_at_all_edges_and_negative_monitor(self):
        self.bubble.show_message("好饿呀…要变成糯米饼了 T_T")
        area = WorkArea(-1920, -200, 1920, 1080)
        for x, y in ((-1920, -200), (-1, -200), (-1920, 800), (-1, 800)):
            self.bubble.follow(QRectF(x - 64, y - 116, 128, 116), area)
            self.assertGreaterEqual(self.bubble.x(), area.left)
            self.assertGreaterEqual(self.bubble.y(), area.top)
            self.assertLessEqual(self.bubble.x() + self.bubble.width(), area.right)
            self.assertLessEqual(self.bubble.y() + self.bubble.height(), area.bottom)
        self.assertTrue(self.bubble.isWindow())
        self.assertTrue(self.bubble.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)

    def test_bubble_normal_message_fades_and_gift_returns_after_level(self):
        with patch("pet_window.time.perf_counter", return_value=100):
            self.bubble.show_message("测试气泡")
        with patch("pet_window.time.perf_counter", return_value=100.09):
            self.bubble._refresh()
            self.assertAlmostEqual(self.bubble._alpha, 0.5)
        with patch("pet_window.time.perf_counter", return_value=103):
            self.bubble._refresh()
            self.assertFalse(self.bubble.isVisible())
            self.bubble.set_collectible(True)
            self.bubble.show_message("🎉 升级啦", "level")
            self.assertFalse(self.bubble._showing_gift)
        with patch("pet_window.time.perf_counter", return_value=106):
            self.bubble._refresh()
            self.assertTrue(self.bubble._showing_gift)
            self.assertTrue(self.bubble.isVisible())

    def test_gift_follow_uses_pet_position_and_pause_does_not_catch_up(self):
        self.controller.model.rng = FixedRandom()
        with patch("main.time.monotonic", return_value=self.controller._last_tick + 900):
            self.controller._tick()
        self.assertEqual(self.controller.model.data.stats["total_idle_seconds"], 1)
        self.assertEqual(self.controller.model.data.hunger, 80)
        self.controller.model.offer_collectible()
        old_x = self.bubble.x()
        area = self.window.engine.area
        self.window.engine.place(area.left + 220, area.top + 400)
        self.window._sync_window()
        self.assertNotEqual(self.bubble.x(), old_x)

    def test_autosave_then_new_controller_restores_growth_and_position(self):
        self.controller.model.rng = FixedRandom()
        self.controller.model.poke()
        self.controller.model.feed_sugar()
        self.controller.model.offer_collectible()
        self.controller._save()
        before = self.controller.model.snapshot()
        self.controller.stop()
        with patch("main.PetWindow", side_effect=lambda _: PetWindow(ARTIFACTS / "no-art")):
            second = PetApplication(APP, save_path=self.file)
        try:
            self.assertEqual(second.model.snapshot(), before)
            self.assertTrue(second.window.engine.pinned)
            self.assertTrue(second.window.bubble._showing_gift)
        finally:
            second.stop()
            second.window.deleteLater()

    def test_insufficient_coins_disables_food_and_pet_cooldown_disables_action(self):
        self.controller.model.data.coins = 0
        self.controller._refresh_menu()
        self.assertFalse(self.controller.feed_action.isEnabled())
        self.controller.pet_action.trigger()
        self.assertFalse(self.controller.pet_action.isEnabled())
        self.controller.model.advance(10)
        self.assertTrue(self.controller.pet_action.isEnabled())


if __name__ == "__main__":
    print(f"Retained Phase 2 artifacts: {ARTIFACTS}", flush=True)
    unittest.main(verbosity=2)
