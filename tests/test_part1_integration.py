"""Real controller integration for Part 1 acceptance, cleanup and saved ownership."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PetApplication
from models import PetData
from pet_engine import WorkArea
from save_manager import SaveManager

APP = QApplication.instance() or QApplication(["part1-controller-integration"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part1-integration-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


class PartOneControllerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work = ART / self._testMethodName
        self.work.mkdir()
        self.controllers = []
        self.c = self.make_controller(dev_mode=True)
        self.m, self.e, self.r = self.c.model, self.c.window.engine, self.c.dashboard.room
        self.m.replace_data(PetData(coins=0, hunger=20, affection_level=30, muted=True))
        self.e.set_work_area(WorkArea(0, 0, 1600, 1000))
        self.c.window.set_pinned(True)
        self.e.place(700, 760)
        self.r.life.wait = 1000
        APP.processEvents()
        self.freeze(self.c)

    @staticmethod
    def freeze(controller):
        # Timers are stopped, not replaced; signal wiring and real physics stay live.
        for owner in (controller.window, controller.dashboard):
            for timer in owner.findChildren(QTimer):
                timer.stop()

    def make_controller(self, *, dev_mode):
        controller = PetApplication(APP, save_path=self.work / "save_data.json",
                                    skins_root=self.work / "skins", dev_mode=dev_mode)
        self.controllers.append(controller)
        controller.dashboard.resize(1240, 800)
        APP.processEvents()
        self.freeze(controller)
        return controller

    def tearDown(self):
        for controller in self.controllers:
            controller.stop()
            controller.dashboard.deleteLater()
            controller.window.deleteLater()
            controller.tray.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def advance(self, seconds):
        for _ in range(round(seconds * 60)):
            self.e.advance(1 / 60)
            self.r.advance_scene(1 / 60)

    def foot(self):
        return self.r._pet_transform().map(self.r._render_foot() + self.r._view().visual_offset)

    def assert_clean(self):
        self.assertEqual(self.e.active_trick, "")
        self.assertEqual(self.m._active_trick_id, "")
        self.assertEqual(self.m.trick_busy, 0)
        self.assertIsNone(self.e.presentation.active)
        self.assertIsNone(self.r.presentation.active)
        self.assertIsNone(self.r.performance)
        self.assertEqual(self.r._gift_queue, [])
        self.assertEqual(self.r._food_queue, [])
        self.assertEqual(self.r._food_id, "")
        self.assertEqual(self.r._last_toy, "")
        self.assertEqual(self.r.foreground_kind, "")

    def assert_home(self):
        self.assertAlmostEqual(self.r.life.x, .48, places=6)
        point, home = self.foot(), self.r._base_foot()
        self.assertAlmostEqual(point.x(), home.x(), places=5)
        self.assertAlmostEqual(point.y(), home.y(), places=5)

    def test_valid_trick_replacement_cancels_one_token_and_accepts_once(self):
        engine_events, model_events = [], []
        self.c.window.presentation_event.connect(engine_events.append)
        self.m.trick_lifecycle.connect(model_events.append)
        self.assertTrue(self.c._perform_trick("clone"))
        first_token = self.e.presentation.active["token"]
        self.advance(.4)
        self.assertTrue(self.c._perform_trick("ball"))
        self.assertEqual((self.e.active_trick, self.m._active_trick_id, self.r._room_trick), ("ball", "ball", "ball"))
        self.assertGreater(self.e.presentation.active["token"], first_token)
        cancelled = [event for event in engine_events if event["phase"] == "cancelled"]
        self.assertEqual([(event["id"], event["reason"], event["token"]) for event in cancelled],
                         [("clone", "replaced", first_token)])
        self.assertEqual([event["phase"] for event in model_events], ["started", "interrupted", "started"])
        self.assertEqual(self.m.data.interaction_history, [{"event": "trick", "item_id": "clone"},
                                                        {"event": "trick", "item_id": "ball"}])
        self.assertEqual(self.m.data.coins, 0)
        self.advance(5.1)
        self.assert_clean()

    def test_rejected_permission_cooldown_or_physical_request_preserves_old_trick(self):
        events = []
        self.c.window.presentation_event.connect(events.append)
        self.assertTrue(self.c._perform_trick("clone"))
        accepted = dict(self.e.presentation.active)
        before = self.m.snapshot()
        self.assertFalse(self.c._perform_trick("clone"), "Own cooldown is still enforced")
        self.assertFalse(self.c._perform_trick("screen_roll"), "Store ownership is required at Lv.30")
        self.e.held = True
        self.assertFalse(self.c._perform_trick("ball"), "A held body cannot perform")
        self.e.held = False
        self.assertEqual(self.e.presentation.active, accepted)
        self.assertEqual(self.m.snapshot(), before)
        self.assertEqual(self.m._active_trick_id, "clone")
        self.assertEqual([event["phase"] for event in events], ["accepted"])

    def test_model_timer_waits_for_real_engine_and_duplicate_finish_is_harmless(self):
        events = []
        self.m.trick_lifecycle.connect(events.append)
        self.assertTrue(self.c._perform_trick("clone"))
        elapsed = self.e.elapsed
        self.m.advance(3)
        self.assertEqual(self.e.elapsed, elapsed)
        self.assertEqual(self.e.active_trick, "clone")
        self.assertEqual(self.m._active_trick_id, "clone")
        self.assertGreater(self.m.trick_busy, 0)
        self.assertEqual([event["phase"] for event in events], ["started"])
        self.advance(2.6)
        self.assertEqual(self.e.active_trick, "")
        self.assertEqual(self.m._active_trick_id, "")
        self.assertEqual(self.m.trick_busy, 0)
        self.c._presentation_event({"kind": "trick", "phase": "finished", "id": "clone"})
        self.assertEqual([event["phase"] for event in events], ["started", "finished"])
        self.assertEqual(self.m.data.interaction_history, [{"event": "trick", "item_id": "clone"}])

    def test_same_class_queues_and_cross_class_cleanup_never_repeat_settlement(self):
        presentations = []
        self.m.presentation_requested.connect(presentations.append)
        self.assertTrue(self.m.buy_item("sugar", feed_now=True))
        self.assertTrue(self.m.buy_item("sugar", feed_now=True))
        self.assertEqual((self.r.foreground_kind, len(self.r._food_queue)), ("food", 1))
        self.assertEqual(self.m.data.stats["total_feeds"], 2)
        self.assertTrue(self.m.buy_item("spinning_top", feed_now=True))
        self.assertEqual(self.r._food_queue, [])
        self.assertEqual(self.r._food_id, "")
        self.assertEqual(self.r.foreground_kind, "gift")
        self.assertTrue(self.m.buy_item("music_box", feed_now=True))
        self.assertEqual(len(self.r._gift_queue), 1)
        settled = (self.m.data.stats["total_feeds"], self.m.data.stats["total_presents"], self.m.data.hunger,
                   self.m._lifetime_exp(), self.m.data.coins)
        self.advance(17)
        self.assertEqual((self.m.data.stats["total_feeds"], self.m.data.stats["total_presents"], self.m.data.hunger,
                          self.m._lifetime_exp(), self.m.data.coins), settled)
        self.assertEqual(len(presentations), 4)
        self.assert_clean()
        self.assert_home()

    def test_food_replaces_gift_and_queued_props_without_recrediting(self):
        self.assertTrue(self.m.buy_item("flower_bouquet", feed_now=True))
        self.assertTrue(self.m.buy_item("music_box", feed_now=True))
        self.advance(1.5)
        self.assertTrue(self.m.buy_item("sugar", feed_now=True))
        self.assertIsNone(self.r.performance)
        self.assertEqual(self.r._gift_queue, [])
        self.assertEqual(self.r.foreground_kind, "food")
        self.advance(8)
        self.assertEqual((self.m.data.stats["total_feeds"], self.m.data.stats["total_presents"]), (1, 2))
        self.assertEqual(self.m.data.coins, 0)
        self.assert_clean()
        self.assert_home()

    def test_room_interruption_preserves_painted_foot_then_returns_home(self):
        self.r.life.x = .64
        self.assertTrue(self.m.buy_item("flower_bouquet", feed_now=True))
        self.advance(2)
        desktop = self.c.window.capture_position()
        current = self.foot()
        self.c._cancel_presentation("input")
        immediate = self.foot()
        self.assertAlmostEqual(immediate.x(), current.x(), places=5)
        self.assertAlmostEqual(immediate.y(), current.y(), places=5)
        self.advance(8)
        self.assert_home()
        self.assert_clean()
        self.assertEqual(self.c.window.capture_position(), desktop)

    def test_hide_and_skin_change_cancel_tricks_without_changing_desktop_anchor(self):
        self.m.set_overlay_visible(True)
        desktop = self.c.window.capture_position()
        self.assertTrue(self.c._perform_trick("clone"))
        self.advance(.4)
        self.m.set_overlay_visible(False)
        self.assert_clean()
        self.assertEqual(self.c.window.capture_position(), desktop)
        self.m.advance(6)
        self.assertTrue(self.c._perform_trick("ball"))
        self.advance(.4)
        self.assertTrue(self.c._select_skin("team_s16_tes"))
        self.assertEqual(self.m.data.selected_skin_id, "team_s16_tes")
        self.assert_clean()
        self.assertEqual(self.c.window.capture_position(), desktop)
        self.advance(8)
        self.assert_home()

    def test_explicit_reset_clears_tricks_and_saves_new_resting_anchor(self):
        self.assertTrue(self.m.buy_trick("screen_roll"))
        self.assertTrue(self.c._perform_trick("screen_roll"))
        self.advance(2)
        self.c.window.reset_to_primary()
        self.assert_clean()
        reset = self.c.window.capture_position()
        self.assertTrue(reset["pinned"])
        self.advance(8)
        self.assertEqual(self.c.window.capture_position(), reset)
        self.assert_home()
        self.c._save()
        _data, saved = SaveManager(self.work / "save_data.json").load_all()
        self.assertEqual(saved, reset)

    def test_saved_history_has_three_model_actions_and_dev_currency_is_process_only(self):
        self.m.poke()
        self.m.pet_head()
        self.assertTrue(self.m.buy_item("sugar", feed_now=True))
        self.assertTrue(self.m.buy_item("music_box", feed_now=True))
        self.assertTrue(self.c._perform_trick("clone"))
        self.c._cancel_presentation("input")
        expected = [{"event": "feed", "item_id": "sugar"}, {"event": "gift", "item_id": "music_box"},
                    {"event": "trick", "item_id": "clone"}]
        self.assertEqual(self.m.data.interaction_history, expected)
        self.assertEqual(self.r.recent_interactions, ["sugar", "music_box", "clone"])
        self.assertTrue(self.m.unlimited_coins)
        # Pokes may legitimately earn coins; free spending never changes that balance.
        balance = self.m.data.coins
        self.assertTrue(self.m.buy_item("sugar"))
        self.assertEqual(self.m.data.coins, balance)
        self.c._save()
        self.c.stop()
        payload = json.loads((self.work / "save_data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["interaction_history"], expected)
        for runtime in ("unlimited_coins", "_unlimited_coins", "_presentation_managed", "dev_mode"):
            self.assertNotIn(runtime, payload)
        release = self.make_controller(dev_mode=False)
        self.assertFalse(release.model.unlimited_coins)
        self.assertEqual(release.model.data.coins, balance)
        self.assertEqual(release.model.data.interaction_history, expected)
        self.assertEqual(release.dashboard.room.recent_interactions, ["sugar", "music_box", "clone"])
        self.assertFalse(release.debug_menu.menuAction().isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
