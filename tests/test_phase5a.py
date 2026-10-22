"""Phase 5A: visible drawers, local daily life and real gift performances."""
from datetime import datetime
from pathlib import Path
import json
import random
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractButton, QScrollArea
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from home_scene import RoomLife, GiftPerformance, RoomPetView
from models import PetData, PetModel
from pet_engine import PetEngine, PetState, WorkArea
from main import PetApplication

APP = QApplication.instance() or QApplication(["phase5a-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
ART = ROOT / "tests/artifacts" / datetime.now().strftime("phase5a-unit-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def pixels(widget):
    image = widget.grab().toImage()
    return bytes(image.constBits())


class LifeTests(unittest.TestCase):
    def test_wait_then_autonomous_bowl_visit_and_return(self):
        life = RoomLife(random.Random(3)); states = set()
        for _ in range(650):
            life.advance(.05); states.add(life.state)
        self.assertTrue({"walk_bowl", "sniff", "return", "idle"} <= states)
        self.assertAlmostEqual(life.x, .48, places=3)

    def test_window_visit_mentions_clouds_by_day_and_moon_at_night(self):
        for hour, word in ((9, "云朵"), (23, "月亮")):
            life = RoomLife(); life.start_activity("window")
            lines = life.advance(3, hour=hour)
            self.assertEqual(life.state, "look_window"); self.assertIn(word, lines[0])

    def test_nap_squashes_then_stretches_and_recovers(self):
        life = RoomLife(); life.start_activity("nap")
        lines = life.advance(1)
        self.assertEqual(len(lines), 1); self.assertIn("zZ", lines[0])
        self.assertLess(life.pose[1], .85)
        life.advance(4.8); self.assertEqual(life.state, "stretch"); self.assertGreater(life.pose[1], 1)
        life.advance(3); self.assertEqual(life.state, "idle"); self.assertEqual(life.pose, (1, 1, 0, 0))

    def test_user_interaction_interrupts_idle_without_teleport(self):
        life = RoomLife(); life.start_activity("bowl"); life.advance(2)
        x = life.x; life.interact()
        self.assertEqual(life.state, "idle"); self.assertEqual(life.x, x)
        life.advance(5); self.assertEqual(life.state, "idle")

    def test_blocked_flat_or_trick_suppresses_autonomy(self):
        life = RoomLife(); life.start_activity("nap"); life.advance(30, blocked=True)
        self.assertEqual(life.state, "idle"); self.assertEqual(life.pose, (1, 1, 0, 0))

    def test_hungry_pet_sniffs_and_asks_for_food(self):
        life = RoomLife(); life.start_activity("bowl")
        lines = life.advance(4, hunger=20)
        self.assertEqual(life.state, "sniff"); self.assertIn("留一口", lines[0])

    def test_toy_is_only_an_autonomous_choice_when_available(self):
        life = RoomLife(); life.accelerated = True; life.toy_available = True; life.cycle = 3; life.wait = 0
        life.advance(2.1); self.assertEqual(life.state, "walk_toy")
        life.advance(3); self.assertEqual(life.state, "inspect")

    def test_daily_dialogue_varies_with_time_hunger_and_affection(self):
        lines = {RoomLife.daily_line(h, 80, 1) for h in (3, 8, 14, 20)}
        self.assertEqual(len(lines), 4)
        self.assertIn("留着", RoomLife.daily_line(22, 80, 6))
        self.assertIn("饭香", RoomLife.daily_line(12, 20, 1))

    def test_ambient_messages_have_real_cooldown(self):
        life = RoomLife(); life.start_activity("window"); self.assertTrue(life.advance(3))
        life.start_activity("bowl"); self.assertEqual(life.advance(3), [])
        self.assertGreaterEqual(life.last_line, 0)

    def test_long_run_positions_stay_inside_safe_floor_area(self):
        life = RoomLife(random.Random(1)); life.toy_available = True
        for _ in range(5000):
            life.advance(.1)
            self.assertGreaterEqual(life.x, .28); self.assertLessEqual(life.x, .70)

    def test_invalid_activity_does_not_change_state(self):
        life = RoomLife(); self.assertFalse(life.start_activity("outside")); self.assertEqual(life.state, "idle")


class GiftModelTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel(PetData(coins=5000)); self.events = []
        self.model.presentation_requested.connect(self.events.append)

    def test_all_four_gifts_emit_one_identified_performance_and_real_gain(self):
        for key in ("paper_star", "flower_bouquet", "music_box", "spinning_top"):
            before = len(self.events); old = self.model._lifetime_exp()
            self.assertTrue(self.model.buy_item(key, feed_now=True))
            event = self.events[-1]
            self.assertEqual(len(self.events), before + 1); self.assertEqual(event["effect"], key)
            self.assertEqual(event["exp_gain"], self.model._lifetime_exp() - old)
            self.assertEqual(event["hunger_gain"], 0)

    def test_food_reports_clamped_actual_hunger_and_zero_affection(self):
        self.model.set_hunger(98); old = self.model._lifetime_exp()
        self.model.buy_item("sugar", feed_now=True)
        self.assertEqual(self.events[-1]["hunger_gain"], 2)
        self.assertEqual(self.events[-1]["exp_gain"], 0); self.assertEqual(self.model._lifetime_exp(), old)
        self.model.buy_item("sugar", feed_now=True); self.assertEqual(self.events[-1]["hunger_gain"], 0)

    def test_inventory_use_is_once_and_failed_purchase_has_no_performance(self):
        self.model.buy_item("paper_star"); self.assertFalse(self.events)
        self.model.use_item("paper_star"); self.assertEqual(len(self.events), 1)
        self.assertFalse(self.model.use_item("paper_star")); self.assertEqual(len(self.events), 1)
        self.model.data.coins = 0
        self.assertFalse(self.model.buy_item("music_box", True)); self.assertEqual(len(self.events), 1)

    def test_max_level_gift_does_not_display_nonexistent_experience(self):
        self.model.data.affection_level = 30; self.model.data.affection_exp = 0
        self.model.buy_item("music_box", True); self.assertEqual(self.events[-1]["exp_gain"], 0)

    def test_top_accelerates_after_pet_bump_then_slows(self):
        top = GiftPerformance("spinning_top"); top.advance(2.5); speed = top.speed; angle = top.angle
        self.assertFalse(top.bumped); top.advance(.2)
        self.assertTrue(top.bumped); self.assertGreater(top.speed, speed); self.assertNotEqual(top.angle, angle)
        speed = top.speed; top.advance(1); self.assertLess(top.speed, speed)

    def test_gifts_have_distinct_motion_and_finite_duration(self):
        poses = []
        for key in ("paper_star", "flower_bouquet", "music_box", "spinning_top"):
            gift = GiftPerformance(key); gift.advance(1); poses.append(gift.pose)
            gift.advance(20); self.assertFalse(gift.active)
        self.assertEqual(len(set(poses)), 4)


class RoomIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel(PetData(coins=5000, affection_level=6))
        self.engine = PetEngine(WorkArea(0, 0, 1600, 900)); self.engine.set_pinned(True)
        self.panel = DashboardWindow(self.model, self.engine)
        self.panel.show(); self.panel.resize(1160, 800); APP.processEvents()
        self.room = self.panel.room; self.room._animation_timer.stop()

    def tearDown(self):
        self.panel.stop(); self.panel.close(); self.panel.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_all_drawers_are_children_and_room_remains_inside_visible_viewport(self):
        for size in ((820, 650), (1000, 720), (1280, 840)):
            self.panel.resize(*size)
            for section in ("bag", "shop", "dress", "furniture", "achievements", "settings"):
                self.panel.show_section(section, animate=False); APP.processEvents()
                self.assertFalse(self.panel.drawer.isWindow()); self.assertTrue(self.panel.drawer.isVisible())
                self.assertTrue(self.room.isVisible()); self.assertGreaterEqual(self.room.height(), 420)
                viewport = self.panel.home_scroll.viewport()
                for widget in (self.room, self.panel.drawer, *self.panel.nav_buttons.values()):
                    pos = widget.mapTo(viewport, QPoint())
                    self.assertTrue(viewport.rect().contains(pos), (size, section, widget.objectName(), pos))
                    self.assertTrue(viewport.rect().contains(pos + widget.rect().bottomRight()), (size, section, widget.geometry()))

    def test_every_purchase_button_can_be_scrolled_fully_into_400px_drawer(self):
        self.panel.resize(820, 720); self.panel.show_section("shop", animate=False); APP.processEvents()
        for category in (0, 1):
            self.panel.shop_tabs.setCurrentIndex(category); APP.processEvents()
            page = self.panel.shop_tabs.currentWidget()
            keys = [k for k, v in self.model.catalog.items.items() if v["category"] == ("food" if category == 0 else "gift")]
            for key in keys:
                for button in self.panel.shop_buttons[key][:2]:
                    page.ensureWidgetVisible(button); APP.processEvents()
                    pos = button.mapTo(page.viewport(), QPoint())
                    self.assertTrue(page.viewport().rect().contains(pos), (key, pos))
                    self.assertTrue(page.viewport().rect().contains(pos + button.rect().bottomRight()), key)

    def test_no_native_button_focus_rect_and_hud_is_compact(self):
        for button in self.panel.findChildren(QAbstractButton):
            self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertLessEqual(self.panel.hud.height(), 108)
        self.assertEqual(self.panel.offset_slider.focusPolicy(), Qt.FocusPolicy.StrongFocus)

    def test_pinned_desktop_is_unchanged_during_roaming_gifts_and_rendering(self):
        before = (self.engine.x, self.engine.y, self.engine.elapsed, self.engine.vx, self.engine.vy, self.engine.pinned)
        self.room.start_activity("window"); self.room.advance_scene(2); self.room.grab()
        for key in ("spinning_top", "music_box", "paper_star", "flower_bouquet"):
            self.room.performance = None; self.model.buy_item(key, True)
            self.room.advance_scene(3); self.room.grab()
        self.assertEqual(before, (self.engine.x, self.engine.y, self.engine.elapsed, self.engine.vx, self.engine.vy, self.engine.pinned))

    def test_shared_expression_is_identical_during_room_gift_and_desktop_playback(self):
        self.room.performance = GiftPerformance("music_box", age=2)
        for mode in ("idle", "happy", "dizzy", "flat"):
            self.engine.happy_until = self.engine.dizzy_until = 0
            self.engine.set_starving(mode == "flat")
            if mode == "happy": self.engine.enjoy_interaction(12)
            if mode == "dizzy": self.engine.get_dizzy()
            self.assertEqual(self.room._view().state, self.engine.state, mode)
        self.assertEqual(self.room._view().state, PetState.FLAT)

    def test_shared_trick_and_starvation_override_local_pose(self):
        self.room.start_activity("nap"); self.room.advance_scene(1)
        self.engine.perform_trick("flip")
        self.assertEqual(self.room._view().pose, self.engine.pose)
        self.engine.cancel_trick(); self.engine.set_starving(True); self.room.advance_scene(.1)
        self.assertEqual(self.room._view().state, PetState.FLAT); self.assertEqual(self.room._view().pose, self.engine.pose)
        self.assertFalse(self.room.start_activity("nap"))

    def test_feeding_chews_and_displays_only_actual_hunger_gain(self):
        self.model.set_hunger(95); self.model.buy_item("water", True)
        self.assertEqual(self.room._floating[-1][0], "+5 饱食")
        start = self.room._chew_started
        with patch("home_scene.monotonic", return_value=start + .85):
            self.assertNotEqual(self.room._view().pose, self.engine.pose); self.room.grab()
        self.assertIsNone(self.room.performance)

    def test_burst_gifts_queue_visuals_without_repeating_model_transactions(self):
        for key in ("spinning_top", "music_box", "paper_star"):
            self.model.buy_item(key, True)
        self.assertEqual(self.model.data.stats["total_presents"], 3)
        self.assertEqual(self.room.performance.item_id, "spinning_top"); self.assertEqual(len(self.room._gift_queue), 2)
        before = self.model.snapshot(); self.room.advance_scene(11)
        self.assertEqual(self.room.performance.item_id, "music_box"); self.assertEqual(self.model.snapshot(), before)

    def test_hidden_room_pauses_local_time(self):
        self.panel.hide(); before = self.room.life.elapsed
        self.room._repaint_if_visible(); self.assertEqual(self.room.life.elapsed, before)

    def test_local_pet_hit_test_tracks_roaming_and_nap(self):
        for activity in ("window", "bowl", "nap"):
            self.room.start_activity(activity); self.room.advance_scene(2)
            self.assertTrue(self.room._hit_pet(self.room.pet_center()), activity)
            self.assertFalse(self.room._hit_pet(QPointF(3, 200)), activity)

    def test_ambient_dialogue_does_not_replace_interaction_or_achievement(self):
        self.room.show_message("急咯急咯", "interaction")
        self.room.show_message("看看窗外", "ambient")
        self.assertEqual(self.room._message, "急咯急咯")

    def test_cloud_cushion_has_one_solid_fill_in_overlapping_lobes(self):
        self.room.set_home_state({"equipped_furniture": {"rug": "cloud_cushion"}})
        image = QImage(320, 120, QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image); self.room._paint_rug(painter, QPointF(160, 40)); painter.end()
        for point in ((80, 53), (120, 53), (160, 53), (210, 53), (240, 53)):
            self.assertEqual(image.pixelColor(*point), QColor("#f8ecd9"), point)

    def test_day_night_and_lamp_have_distinct_frames(self):
        self.room.set_home_state({"equipped_furniture": {"corner": "warm_lamp"}, "lamp_on": False})
        self.room.daytime_override = True; day = pixels(self.room)
        self.room.daytime_override = False; night = pixels(self.room)
        self.room.set_home_state({"equipped_furniture": {"corner": "warm_lamp"}, "lamp_on": True})
        lamp = pixels(self.room)
        self.assertNotEqual(day, night); self.assertNotEqual(night, lamp)

    def test_all_gift_drawings_change_over_time_and_finish(self):
        for key in ("spinning_top", "music_box", "paper_star", "flower_bouquet"):
            self.room.performance = GiftPerformance(key); self.room.advance_scene(1)
            first = pixels(self.room); self.room.advance_scene(.4)
            self.assertNotEqual(first, pixels(self.room), key)
            self.room.advance_scene(20); self.assertIsNone(self.room.performance)

    def test_dev_daily_previews_are_only_shown_with_dev_context(self):
        self.panel.show_section("settings", animate=False)
        self.assertTrue(self.panel.room_debug.isHidden())
        self.panel.set_phase4_context([], True); self.assertFalse(self.panel.room_debug.isHidden())
        self.panel.set_phase4_context([], False); self.assertTrue(self.panel.room_debug.isHidden())


if __name__ == "__main__": unittest.main(verbosity=2)
