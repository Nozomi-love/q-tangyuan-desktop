"""Part 1: presentation ownership, real painted anchors and idempotent exits."""
from pathlib import Path
import sys
import unittest

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_registry import BUILTIN_TRICKS
from home_scene import IllustratedRoomCanvas
from pet_engine import PetEngine, PresentationLifecycle, SkinRenderer, WorkArea
from pet_window import PetWindow

APP = QApplication.instance() or QApplication(["part1-lifecycle"])
APP.setQuitOnLastWindowClosed(False)


def painted_foot(room):
    return room._pet_transform().map(room._render_foot() + room._view().visual_offset)


def tick(room, seconds):
    for _ in range(round(seconds * 60)):
        room.advance_scene(1 / 60)


class LifecycleContractTests(unittest.TestCase):
    def test_repeat_end_is_noop_and_events_preserve_acceptance_anchor(self):
        lifecycle = PresentationLifecycle()
        events = []
        lifecycle.changed.connect(events.append)
        lifecycle.begin("gift", "music_box", QPointF(123, 456))
        lifecycle.cancel("input")
        lifecycle.cancel("input")
        lifecycle.finish()
        self.assertEqual([event["phase"] for event in events], ["accepted", "cancelled"])
        self.assertEqual(events[1]["anchor"], [123., 456.])
        self.assertEqual(events[0]["token"], events[1]["token"])

    def test_reentrant_end_can_start_new_token_without_old_end_erasing_it(self):
        for end in ("finish", "cancel"):
            lifecycle = PresentationLifecycle()
            events = []
            def changed(event):
                events.append(event)
                if event["phase"] in ("finished", "cancelled") and event["id"] == "water":
                    lifecycle.cancel("already_ended")
                    lifecycle.begin("gift", "paper_star", QPointF(3, 4))
            lifecycle.changed.connect(changed)
            lifecycle.begin("food", "water", QPointF(1, 2))
            getattr(lifecycle, end)()
            self.assertEqual(lifecycle.active["id"], "paper_star")
            self.assertEqual([event["phase"] for event in events],
                             ["accepted", "finished" if end == "finish" else "cancelled", "accepted"])

    def test_replacement_terminates_old_token_before_accepting_new(self):
        lifecycle = PresentationLifecycle()
        events = []
        lifecycle.changed.connect(events.append)
        lifecycle.begin("food", "water", QPointF())
        lifecycle.begin("gift", "paper_star", QPointF(1, 2))
        self.assertEqual([event["phase"] for event in events], ["accepted", "cancelled", "accepted"])
        self.assertEqual(events[1]["reason"], "replaced")
        self.assertNotEqual(events[0]["token"], events[2]["token"])


class EnginePresentationTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        self.engine.set_pinned(True)

    def test_timings_come_from_implemented_registry_and_drafts_cannot_run(self):
        for key, definition in BUILTIN_TRICKS.items():
            self.assertTrue(self.engine.perform_trick(key))
            self.assertEqual(self.engine._trick_duration, definition.duration)
            self.engine.cancel_trick()
        self.assertFalse(self.engine.perform_trick("recall_taunt"))

    def test_side_effect_free_replacement_preflight_retains_running_trick(self):
        self.engine.perform_trick("flip")
        before = dict(self.engine.presentation.active)
        self.assertTrue(self.engine.can_start_trick("clone", replacing=True))
        self.assertFalse(self.engine.can_start_trick("unknown", replacing=True))
        self.engine.held = True
        self.assertFalse(self.engine.can_start_trick("clone", replacing=True))
        self.engine.held = False
        self.engine.dizzy_until = self.engine.elapsed + 3
        self.assertFalse(self.engine.can_start_trick("clone", replacing=True))
        self.assertEqual(self.engine.presentation.active, before)
        self.assertEqual(self.engine.active_trick, "flip")

    def test_natural_completion_has_one_finish_event_and_no_leftover_ball_or_roll(self):
        for key in BUILTIN_TRICKS:
            with self.subTest(trick=key):
                events = []
                self.engine.presentation.changed.connect(events.append)
                anchor = (self.engine.x, self.engine.y)
                self.engine.perform_trick(key)
                self.engine.advance(BUILTIN_TRICKS[key].duration + .01)
                self.assertEqual([event["phase"] for event in events], ["accepted", "finished"])
                self.assertEqual(self.engine.visual_offset, QPointF())
                self.assertEqual(self.engine.visual_angle, 0)
                self.assertTrue(self.engine._roll_rect.isNull())
                self.assertEqual((self.engine.ball_x, self.engine.ball_y,
                                  self.engine.ball_vx, self.engine.ball_vy), (0, 0, 0, 0))
                self.assertEqual((self.engine.x, self.engine.y), anchor)
                self.engine.presentation.changed.disconnect(events.append)


class RoomPresentationTests(unittest.TestCase):
    def setUp(self):
        self.engine = PetEngine(WorkArea(0, 0, 1600, 1000))
        self.engine.set_pinned(True)
        self.renderer = SkinRenderer(ROOT / "assets/skins/default")
        self.room = IllustratedRoomCanvas(self.engine, lambda: self.renderer)
        self.room.resize(1240, 760)
        self.room._animation_timer.stop()
        self.room.life.wait = 1000
        self.desktop = (self.engine.x, self.engine.y)

    def tearDown(self):
        self.room.stop()
        self.room.deleteLater()
        self.renderer.stop()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def assertReturned(self):
        self.assertAlmostEqual(self.room.life.x, .48, places=6)
        foot = painted_foot(self.room)
        self.assertAlmostEqual(foot.x(), self.room._base_foot().x(), places=5)
        self.assertAlmostEqual(foot.y(), self.room._base_foot().y(), places=5)
        self.assertEqual((self.engine.x, self.engine.y), self.desktop)

    def test_cancel_trick_keeps_actual_painted_foot_then_settles_home(self):
        for key in BUILTIN_TRICKS:
            with self.subTest(trick=key):
                self.room.cancel_presentation("reset", False, cancel_engine=True)
                self.room.life.x = .62
                self.engine.perform_trick(key)
                self.room.begin_trick(key)
                self.engine.elapsed += BUILTIN_TRICKS[key].duration * .36
                before = painted_foot(self.room)
                self.room.cancel_presentation("input")
                self.engine.cancel_trick("input")
                after = painted_foot(self.room)
                self.assertAlmostEqual(before.x(), after.x(), places=5)
                self.assertAlmostEqual(before.y(), after.y(), places=5)
                tick(self.room, .5)
                self.assertLess(self.room._settle_age, 1)
                tick(self.room, 7)
                self.assertReturned()

    def test_cancel_gift_and_food_clears_all_props_and_queues(self):
        self.room.present_item({"category": "gift", "item_id": "flower_bouquet"})
        self.room.present_item({"category": "gift", "item_id": "music_box"})
        self.room.advance_scene(2)
        self.room.cancel_presentation("input")
        self.room.show_food("sugar", 15)
        self.room.show_food("water", 10)
        self.room.cancel_presentation("skin_changed")
        self.room.cancel_presentation("skin_changed")
        self.assertIsNone(self.room.performance)
        self.assertEqual((self.room._gift_queue, self.room._food_queue), ([], []))
        self.assertEqual(self.room._food_id, "")
        self.assertEqual(self.room._last_toy, "")
        self.assertIsNone(self.room.presentation.active)
        tick(self.room, 7)
        self.assertReturned()

    def test_cancel_autonomous_hop_preserves_foot_without_doubling_local_hop(self):
        for activity in ("bowl", "window", "nap", "hum", "hop"):
            self.room.life.x = .55
            self.room.life.start_activity(activity)
            self.room.advance_scene(.37)
            before = painted_foot(self.room)
            self.room.cancel_presentation("input")
            after = painted_foot(self.room)
            self.assertAlmostEqual(before.x(), after.x(), places=5)
            self.assertAlmostEqual(before.y(), after.y(), places=5)
            tick(self.room, 7)
            self.assertReturned()

    def test_cross_type_replaces_but_same_type_gifts_and_food_queue(self):
        events = []
        self.room.presentation_event.connect(events.append)
        self.room.show_food("water", 10)
        self.room.show_food("sugar", 15)
        self.assertEqual(len(self.room._food_queue), 1)
        self.room.present_item({"category": "gift", "item_id": "music_box"})
        self.room.present_item({"category": "gift", "item_id": "paper_star"})
        self.assertEqual(self.room.foreground_kind, "gift")
        self.assertEqual(self.room._food_queue, [])
        self.assertEqual(len(self.room._gift_queue), 1)
        self.room.show_food("water", 10)
        self.assertEqual(self.room.foreground_kind, "food")
        self.assertIsNone(self.room.performance)
        self.assertEqual(self.room._gift_queue, [])
        active = 0
        for event in events:
            active += 1 if event["phase"] == "accepted" else -1
            self.assertIn(active, (0, 1))

    def test_queued_gifts_finish_each_token_once_without_advancing_engine(self):
        events = []
        self.room.presentation_event.connect(events.append)
        self.room.present_item({"category": "gift", "item_id": "music_box"})
        self.room.present_item({"category": "gift", "item_id": "paper_star"})
        tick(self.room, 15)
        self.assertEqual([event["phase"] for event in events],
                         ["accepted", "finished", "accepted", "finished"])
        self.assertEqual(self.engine.elapsed, 0)

    def test_hide_clears_shared_trick_and_retains_location_until_visible_again(self):
        self.room.show()
        self.room.life.x = .61
        self.engine.perform_trick("flip")
        self.room.begin_trick("flip")
        self.engine.elapsed += .4
        self.room.hide()
        self.assertEqual(self.engine.active_trick, "")
        self.assertEqual(self.room._room_trick, "")
        self.assertEqual(self.room._food_id, "")
        self.room.show()
        tick(self.room, 7)
        self.assertReturned()

    def test_stop_is_idempotent_and_cancels_visuals_without_clearing_buff_or_accessories(self):
        self.engine.set_buff({"scale": 1.2, "remaining_seconds": 60})
        self.renderer.set_accessories({"head": "crown"})
        self.room.present_item({"category": "gift", "item_id": "music_box"})
        self.room.stop()
        self.room.stop()
        self.assertEqual(self.room.foreground_kind, "")
        self.assertEqual(self.engine.buff["scale"], 1.2)
        self.assertEqual(self.renderer.accessories["head"], "crown")

    def test_preview_and_rendering_do_not_create_model_history(self):
        history = [{"event": "poke", "item_id": ""},
                   {"event": "gift", "item_id": "music_box"},
                   {"event": "trick", "item_id": "flip"}]
        self.room.set_home_state({"interaction_history": history})
        self.room.present_item({"category": "gift", "item_id": "paper_star"})
        self.room.record_interaction("poke")
        self.room.grab()
        self.assertEqual(self.room.recent_interactions, ["avatar", "music_box", "flip"])
        self.assertEqual(self.room._home["interaction_history"], history)


class DesktopPresentationTests(unittest.TestCase):
    def test_pre_change_hooks_see_old_trick_and_unchanged_accessories_do_not_cancel(self):
        window = PetWindow(ROOT / "assets/skins/default")
        window.timer.stop()
        try:
            window.engine.set_pinned(True)
            window.perform_trick("screen_roll")
            before = dict(window.renderer.accessories)
            window.set_accessories(before)
            self.assertEqual(window.engine.active_trick, "screen_roll")
            events = []
            window.presentation_interrupt_requested.connect(
                lambda reason: events.append((reason, window.engine.active_trick, dict(window.renderer.accessories))))
            window.set_accessories({"head": "crown"})
            self.assertEqual(events[0], ("accessories_changed", "screen_roll", before))
            self.assertEqual(window.engine.active_trick, "")
            window.perform_trick("flip")
            window.set_starving(True)
            self.assertEqual(events[-1][0:2], ("starving", "flip"))
            self.assertEqual(window.engine.active_trick, "")
        finally:
            window.stop()
            window.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_fixed_and_free_cancel_never_save_temporary_offset(self):
        window = PetWindow(ROOT / "assets/skins/default")
        window.timer.stop()
        try:
            for pinned in (False, True):
                for key in BUILTIN_TRICKS:
                    with self.subTest(pinned=pinned, trick=key):
                        window.engine.set_pinned(pinned)
                        window.engine.grounded = True
                        before = window.capture_position()
                        self.assertTrue(window.perform_trick(key))
                        window.engine.elapsed += BUILTIN_TRICKS[key].duration * .4
                        during = window.capture_position()
                        self.assertTrue(window.cancel_presentation("input"))
                        self.assertFalse(window.cancel_presentation("input"))
                        self.assertEqual(window.capture_position(), before)
                        self.assertEqual(during, before)
                        self.assertEqual(window.engine.visual_offset, QPointF())
        finally:
            window.stop()
            window.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
