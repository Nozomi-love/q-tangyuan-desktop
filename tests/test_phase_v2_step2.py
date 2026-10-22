"""V2 step 2: activity/transaction/animation/audio boundaries, using isolated saves."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import json
import math
import random
import struct
import sys
import unittest
from unittest.mock import patch
import wave
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from home_scene import RoomLife, GiftPerformance
from models import PetData, PetModel
from dashboard import DashboardWindow
from main import PetApplication
from save_manager import SaveManager, SaveDataError
from pet_window import synthesize_sound, ensure_sound_files, ProceduralAudio, SOUND_NAMES
APP = QApplication.instance() or QApplication(["v2-step2-tests"])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT / "tests/artifacts" / datetime.now().strftime("v2-step2-unit-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True)


class LifeTests(unittest.TestCase):
    def test_normal_waits_are_twelve_to_twenty_five_seconds(self):
        life = RoomLife(random.Random(23))
        for _ in range(100):
            self.assertGreaterEqual(life.wait, 12); self.assertLessEqual(life.wait, 25)
            life.interact()

    def test_random_autonomy_exercises_all_five_behaviours_without_fixed_cycle(self):
        life = RoomLife(random.Random(17)); chosen = []
        for _ in range(100):
            life.state = "idle"; life.wait = 0; life.quiet = 7
            life.advance(.05); chosen.append(life._previous_kind)
        self.assertEqual(set(chosen), set(life.KINDS))
        self.assertTrue(all(a != b for a, b in zip(chosen, chosen[1:])))
        self.assertNotEqual(chosen[:5], chosen[5:10])

    def test_acceleration_waits_two_to_four_seconds(self):
        life = RoomLife(random.Random(9)); life.accelerated = True
        for _ in range(20):
            life.interact(); self.assertTrue(2 <= life.wait <= 4)

    def test_interrupt_preserves_pose_and_position_then_blends_neutral(self):
        life = RoomLife(); life.start_activity("nap"); life.advance(2)
        pose, x = life.pose, life.x; life.interact()
        self.assertEqual(life.pose, pose); self.assertEqual(life.x, x)
        life.advance(.1); self.assertGreater(life.pose[1], pose[1]); self.assertLess(life.pose[1], 1)
        life.advance(.2); self.assertEqual(life.pose, (1, 1, 0, 0))

    def test_humming_and_hopping_have_distinct_poses_and_finish(self):
        poses = []
        for kind in ("hum", "hop"):
            life = RoomLife(); self.assertTrue(life.start_activity(kind)); life.advance(.6)
            poses.append(life.pose); life.advance(5)
            self.assertEqual(life.state, "idle")
        self.assertNotEqual(*poses); self.assertLess(poses[1][3], -20)

    def test_deep_night_and_mealtime_context_and_low_frequency(self):
        self.assertIn("休息", RoomLife.daily_line(23, 80, 6))
        self.assertIn("午饭", RoomLife.daily_line(12, 80, 1))
        life = RoomLife(random.Random(1)); lines = []
        for _ in range(2500): lines += life.advance(.1, hour=3)
        self.assertGreater(len(lines), 0); self.assertLessEqual(len(lines), 5)

    def test_top_bump_only_once_and_rebounds_with_local_drift(self):
        top = GiftPerformance("spinning_top"); top.advance(2.5)
        self.assertFalse(top.bumped); old = top.top_x
        top.advance(.2); self.assertTrue(top.bumped); self.assertGreater(top.top_x, old)
        self.assertGreater(top.speed, 1000); stamp = top.bump_age
        top.advance(2); self.assertEqual(top.bump_age, stamp); self.assertLessEqual(top.top_x, .84)

    def test_gift_approach_starts_at_current_room_position(self):
        top = GiftPerformance("spinning_top", start_x=.56)
        self.assertEqual(top.pet_x, .56); top.advance(2.7)
        self.assertAlmostEqual(top.pet_x, .61); self.assertTrue(top.bumped)


class GainTests(unittest.TestCase):
    def setUp(self):
        self.m = PetModel(PetData(coins=5000), rng=random.Random(1)); self.events = []
        self.m.gains_received.connect(self.events.append)

    def total(self, key): return sum(e.get(key, 0) for e in self.events)

    def test_food_only_emits_clamped_actual_hunger(self):
        self.m.set_hunger(97); self.m.buy_item("sugar", True)
        self.assertEqual(self.total("hunger"), 3); self.assertEqual(self.total("exp"), 0)
        self.m.buy_item("sugar", True); self.assertEqual(self.total("hunger"), 3)

    def test_coin_spending_is_not_a_positive_gain(self):
        self.m.buy_item("spinning_top"); self.assertEqual(self.events, [])

    def test_gift_level_crossing_emits_actual_exp_and_separate_level_coins(self):
        self.m.data.affection_exp = 490
        self.m.buy_item("paper_star", True)
        self.assertEqual(self.total("exp"), 20); self.assertEqual(self.total("coins"), 30)
        self.assertEqual(self.m.data.affection_level, 2)

    def test_max_level_and_near_cap_do_not_invent_exp(self):
        self.m.data.affection_level = 29; self.m.data.affection_exp = 14490
        self.m.buy_item("paper_star", True); self.assertEqual(self.total("exp"), 10)
        self.events.clear(); self.m.buy_item("music_box", True); self.assertEqual(self.total("exp"), 0)

    def test_poke_pet_and_auto_income_emit_once_each(self):
        self.m.poke(); self.assertEqual(self.total("exp"), 2)
        self.assertEqual(self.total("coins"), 2)
        self.events.clear(); self.m.pet_head(); self.assertEqual(self.total("exp"), 3)
        self.events.clear(); self.m.offer_collectible()
        self.assertTrue(10 <= self.total("coins") <= 20); self.assertEqual(self.total("exp"), 5)
        count = len(self.events); self.assertFalse(self.m.claim_collectible()); self.assertEqual(len(self.events), count)

    def test_achievement_reward_emits_once(self):
        self.m.poke(); self.events.clear()
        key = self.m.data.unlocked_achievements[0]
        self.assertTrue(self.m.claim_achievement(key)); amount = self.total("coins")
        self.assertGreater(amount, 0); self.assertFalse(self.m.claim_achievement(key)); self.assertEqual(self.total("coins"), amount)

    def test_four_gift_durations_are_between_six_and_eight(self):
        for item in self.m.catalog.items.values():
            if item["category"] == "gift": self.assertTrue(6 <= item["performance_seconds"] <= 8)

    def test_failed_actions_emit_neither_interaction_nor_gain(self):
        started = []; self.m.interaction_started.connect(started.append)
        self.m.data.coins = 0
        self.assertFalse(self.m.buy_item("music_box", True)); self.assertFalse(self.m.use_item("sugar"))
        self.assertEqual(self.events, []); self.assertEqual(started, [])


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.m = PetModel(PetData(coins=5000, affection_level=6))
        self.p = DashboardWindow(self.m); self.p.show(); APP.processEvents()
        self.p.preview_timer.stop(); self.r = self.p.room; self.r._animation_timer.stop()
        self.sounds = []; self.r.sound_requested.connect(self.sounds.append)

    def tearDown(self):
        self.p.stop(); self.p.close(); self.p.deleteLater(); APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_food_arrival_gates_sound_chewing_and_hunger_text(self):
        self.m.set_hunger(90); self.m.buy_item("water", True)
        self.r.advance_scene(.77); self.assertFalse(self.r._food_arrived); self.assertNotIn("eat", self.sounds)
        self.assertFalse(self.r._floating)
        self.r.advance_scene(.02); self.assertTrue(self.r._food_arrived); self.assertEqual(self.sounds.count("eat"), 1)
        self.assertEqual(self.r._floating[-1][0], "+10 饱食度")
        self.r.advance_scene(2); self.assertEqual(self.sounds.count("eat"), 1)

    def test_chewing_is_exactly_three_squashes_and_returns_neutral(self):
        self.r.show_food("sugar"); self.r.advance_scene(.78)
        for i in range(3):
            self.r._food_age = .78 + .15 + i * .3
            self.assertLess(self.r._local_pose()[1], .9)
            self.r._food_age = .78 + .3 + i * .3
            self.assertAlmostEqual(self.r._local_pose()[1], 1)
        self.r.advance_scene(1); self.assertEqual(self.r._local_pose(), (1, 1, 0, 0))

    def test_rapid_food_queues_visuals_without_reconsuming(self):
        for _ in range(3): self.m.buy_item("water", True)
        before = self.m.snapshot(); self.assertEqual(len(self.r._food_queue), 2)
        for _ in range(60): self.r.advance_scene(.1)
        self.assertEqual(self.m.snapshot(), before); self.assertEqual(self.sounds.count("eat"), 3)

    def test_floating_actual_rewards_are_colored_lanes_and_expire_after_1_2_seconds(self):
        self.r.show_gains({"coins": 12, "exp": 5})
        self.assertEqual([text for text, _ in self.r._floating], ["+12 糯米币", "+5 好感"])
        born = self.r._floating[0][1]
        with patch("home_scene.monotonic", return_value=born + 1.21): self.r.advance_scene(.01)
        self.assertFalse(self.r._floating)

    def test_fast_gains_coalesce_without_losing_value(self):
        for _ in range(15): self.r.show_gains({"exp": 2})
        self.assertEqual([t for t, _ in self.r._floating], ["+30 好感"])

    def test_music_box_sound_and_top_bump_dialogue_are_one_shot(self):
        self.m.buy_item("music_box", True); self.r.advance_scene(2)
        self.assertEqual(self.sounds.count("music_box"), 1)
        self.r.performance = None; self.m.buy_item("spinning_top", True)
        self.r.advance_scene(2.7); self.assertIn("再转快", self.r._message)
        self.assertTrue(self.r.performance.bumped)

    def test_own_nap_mood_does_not_cancel_the_nap_next_frame(self):
        self.r.start_activity("nap"); self.r._repaint_if_visible()
        self.assertEqual(self.r.life.state, "nap")
        self.m.poke(); self.assertEqual(self.r.life.state, "idle")

    def test_manual_preview_does_not_change_save(self):
        self.p.set_phase4_context([], True); before = self.m.snapshot()
        for button in self.p.activity_buttons.values(): button.click(); self.r.advance_scene(.1)
        for button in self.p.preview_gift_buttons.values(): button.click(); self.r.advance_scene(.1)
        self.assertEqual(self.m.snapshot(), before)

    def test_food_priority_interrupts_nap_and_gift_without_teleporting(self):
        self.r.start_activity("nap"); self.r.advance_scene(1)
        self.m.buy_item("water", True); self.assertEqual(self.r.life.state, "idle")
        self.r.performance = None; self.r._food_age = 100
        self.m.buy_item("spinning_top", True); self.r.advance_scene(2)
        x = self.r.performance.pet_x; self.m.buy_item("water", True)
        self.assertIsNone(self.r.performance); self.assertEqual(self.r.life.x, x)

    def test_three_feed_entrypoints_share_single_transaction(self):
        self.p.show_section("shop", animate=False); APP.processEvents()
        before = self.m.data.stats["total_feeds"]
        self.p.shop_buttons["water"][1].click()
        self.assertEqual(self.m.data.stats["total_feeds"], before + 1)
        self.assertIsNotNone(self.r._fly_from)
        self.m.buy_item("water"); self.m.buy_item("water")
        self.p.feeding_buttons["water"].click()
        self.p.show_section("bag", animate=False); APP.processEvents()
        self.p.inventory_widgets["water"][2].click()
        self.assertEqual(self.m.data.stats["total_feeds"], before + 3)
        self.assertEqual(self.m.data.inventory.get("water", 0), 0)
        self.assertEqual(len(self.r._food_queue), 2)
        self.assertTrue(all(origin is not None for _, _, origin in self.r._food_queue))

    def test_hud_mute_control_fits_narrow_drawer(self):
        self.p.resize(820, 650); self.p.show_section("shop", animate=False); APP.processEvents()
        for button in (self.p.mute_button, self.p.overlay_button):
            self.assertTrue(self.p.hud_right.rect().contains(button.mapTo(self.p.hud_right, button.rect().topLeft())))
            self.assertTrue(self.p.hud_right.rect().contains(button.mapTo(self.p.hud_right, button.rect().bottomRight())))


class SoundTests(unittest.TestCase):
    def test_all_four_waveforms_are_valid_quiet_pcm_and_distinct(self):
        values = []
        for name in SOUND_NAMES:
            raw = synthesize_sound(name); values.append(raw)
            with wave.open(BytesIO(raw), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 22050))
                duration = wav.getnframes() / wav.getframerate()
                self.assertTrue(.15 < duration < 7)
                samples = struct.unpack("<" + "h" * wav.getnframes(), wav.readframes(wav.getnframes()))
                self.assertGreater(max(samples), 1000); self.assertLessEqual(max(map(abs, samples)), 24575)
                self.assertEqual(samples[0], 0); self.assertLess(abs(samples[-1]), 20)
        self.assertEqual(len(set(values)), 5)

    def test_unknown_sound_is_rejected(self):
        with self.assertRaises(ValueError): synthesize_sound("../private")

    def test_asset_generator_never_overwrites_existing_audio(self):
        folder = ART / "preserved"; folder.mkdir(); target = folder / "poke.wav"; target.write_bytes(b"artist original")
        files = ensure_sound_files(folder); self.assertEqual(target.read_bytes(), b"artist original")
        self.assertEqual(len(files), 5)

    def test_missing_readonly_location_degrades_without_gameplay_failure(self):
        file = ART / "not-a-folder"; file.write_bytes(b"kept")
        audio = ProceduralAudio(file, True); self.assertTrue(audio.errors); self.assertFalse(audio.play("poke"))
        self.assertEqual(file.read_bytes(), b"kept"); audio.stop()

    def test_muting_stops_every_sound_and_prevents_replay(self):
        audio = ProceduralAudio(ROOT / "assets/sounds", True)
        self.assertEqual(len(audio.effects), 5); self.assertFalse(audio.play("poke"))
        audio.set_muted(False)
        with patch.object(audio.effects["poke"], "play") as play:
            self.assertTrue(audio.play("poke")); self.assertEqual(play.call_count, 1)
            self.assertFalse(audio.play("poke"))
        audio.set_muted(True)
        self.assertTrue(all(e.isMuted() and not e.isPlaying() for e in audio.effects.values())); audio.stop()

    def test_old_save_defaults_unmuted_and_new_flag_is_strict_bool(self):
        self.assertFalse(PetData.from_dict({"schema_version": 5}).muted)
        for value in (1, "false", None):
            with self.assertRaises(ValueError): PetData.from_dict({"muted": value})

    def test_save_roundtrip_preserves_mute_window_and_unknown_fields(self):
        file = ART / "mute-save.json"
        file.write_text(json.dumps({"schema_version": 5, "future_data": {"keep": 1},
            "window": {"pinned": True, "x_ratio": .2, "y_ratio": .4}}), encoding="utf8")
        manager = SaveManager(file); data, window = manager.load_all(); data.muted = True
        manager.update_game(data.to_dict(), window)
        restored, position = SaveManager(file).load_all()
        self.assertTrue(restored.muted); self.assertEqual(position, window)
        self.assertEqual(json.loads(file.read_text(encoding="utf8"))["future_data"], {"keep": 1})


class ControllerTests(unittest.TestCase):
    def test_hud_context_and_tray_mute_synchronize_and_restore(self):
        file = ART / "controller.json"
        c = PetApplication(APP, file, skins_root=ART / "skins", dev_mode=True)
        try:
            c.tick_timer.stop(); c.window.timer.stop()
            c.dashboard.mute_button.click()
            self.assertTrue(c.model.data.muted and c.audio.muted and c.mute_action.isChecked())
            c.mute_action.setChecked(False)
            self.assertFalse(c.model.data.muted or c.audio.muted or c.dashboard.mute_button.isChecked())
            c.mute_action.setChecked(True); c._save()
        finally:
            c.stop(); c.dashboard.deleteLater(); c.window.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        restored = PetApplication(APP, file, skins_root=ART / "skins", dev_mode=True)
        try:
            self.assertTrue(restored.model.data.muted and restored.audio.muted)
            self.assertTrue(restored.mute_action.isChecked() and restored.dashboard.mute_button.isChecked())
        finally:
            restored.stop(); restored.dashboard.deleteLater(); restored.window.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__": unittest.main()
