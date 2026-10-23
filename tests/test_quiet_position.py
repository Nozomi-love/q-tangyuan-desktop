"""Passive income stays silent; cosmetic actions do not overwrite resting anchors."""
from datetime import datetime
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from home_scene import GiftPerformance
from main import PetApplication
from models import PetData, PetModel
from pet_engine import PetEngine, WorkArea
from pet_window import PetWindow

APP = QApplication.instance() or QApplication(['quiet-position-tests'])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT / 'tests/artifacts' / datetime.now().strftime('quiet-position-%Y%m%d-%H%M%S-%f')
ART.mkdir(parents=True, exist_ok=False)
GIFTS = ('paper_star', 'flower_bouquet', 'music_box', 'spinning_top', 'tes_guitar', 'tes_microphone')


def advance(engine, seconds):
    for _ in range(round(seconds * 120)):
        engine.advance(1 / 120)


class QuietIncomeTests(unittest.TestCase):
    def setUp(self):
        self.c = PetApplication(APP, ART / (self._testMethodName + '.json'),
                                skins_root=ART / self._testMethodName, dev_mode=True)
        self.c.tick_timer.stop()
        self.c.window.timer.stop()
        self.c.dashboard.room._animation_timer.stop()
        self.c.model.rng = random.Random(1)
        self.c.model.set_muted(False)

    def tearDown(self):
        self.c.stop()
        self.c.dashboard.deleteLater()
        self.c.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_many_online_payments_are_silent_but_still_credit_coins_and_exp(self):
        m = self.c.model
        initial = m.data.coins
        with patch.object(self.c.audio, 'play') as play:
            m.advance(m.rules.gift_seconds * 4 + .01)
        self.assertEqual(m.data.stats['total_gifts'], 4)
        self.assertTrue(40 <= m.data.coins - initial <= 80)
        self.assertEqual(m.data.affection_exp, 20)
        self.assertEqual(play.call_count, 0)

    def test_automatic_level_up_and_passive_achievement_do_not_ring(self):
        m = self.c.model
        m.data.affection_exp = m.exp_required - 1
        m.data.stats['total_gifts'] = 2
        with patch.object(self.c.audio, 'play') as play:
            m.offer_collectible()
        self.assertEqual(m.data.affection_level, 2)
        self.assertEqual(m.data.stats['total_gifts'], 3)
        self.assertEqual(play.call_count, 0)

    def test_active_poke_and_claim_still_have_interactive_sound(self):
        with patch.object(self.c.audio, 'play') as play:
            self.c.model.poke()
            self.assertIn(('poke',), [call.args for call in play.call_args_list])
            self.assertIn(('coin',), [call.args for call in play.call_args_list])
            play.reset_mock()
            key = self.c.model.data.unlocked_achievements[0]
            self.assertTrue(self.c.model.claim_achievement(key))
            self.assertEqual([call.args for call in play.call_args_list], [('coin',)])


class RoomAnchorTests(unittest.TestCase):
    def setUp(self):
        self.e = PetEngine(WorkArea(0, 0, 1800, 1200))
        self.e.set_pinned(True)
        self.m = PetModel(PetData(coins=50000, affection_level=15))
        self.m.select_skin('team_s16_tes')
        self.p = DashboardWindow(self.m, self.e)
        self.p.show()
        APP.processEvents()
        self.r = self.p.room
        self.r._animation_timer.stop()
        self.r.life.wait = 1000
        self.r.life.x = .64

    def tearDown(self):
        self.p.stop()
        self.p.hide()
        self.p.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_shared_busy_states_never_snap_roaming_pet_to_room_center(self):
        x = self.r._render_foot().x()
        for state in ('held', 'dragging', 'starving', 'manual_flat'):
            with self.subTest(state=state):
                setattr(self.e, state, True)
                self.assertAlmostEqual(self.r._render_foot().x(), x)
                self.r.advance_scene(.05)
                self.assertAlmostEqual(self.r._render_foot().x(), x)
                setattr(self.e, state, False)
        self.e.get_dizzy()
        self.assertAlmostEqual(self.r._render_foot().x(), x)

    def test_each_gift_finishes_at_the_position_where_it_started(self):
        for key in GIFTS:
            with self.subTest(gift=key):
                self.r.life.x = .64
                self.r.performance = GiftPerformance(key, start_x=.64)
                self.r.advance_scene(7.01)
                self.assertIsNone(self.r.performance)
                self.assertAlmostEqual(self.r.life.x, .64)
                self.assertEqual(self.r.life.state, 'idle')
                self.r.advance_scene(1)
                self.assertAlmostEqual(self.r.life.x, .64)

    def test_gift_return_is_continuous_and_ends_at_exact_origin(self):
        for key in GIFTS:
            gift = GiftPerformance(key, start_x=.64)
            gift.age = gift.duration - .001
            self.assertAlmostEqual(gift.pet_x, .64, places=5, msg=key)
            gift.age = gift.duration
            self.assertEqual(gift.pet_x, .64, key)

    def test_busy_gift_keeps_position_and_cancels_instead_of_resuming_later(self):
        self.r.performance = GiftPerformance('flower_bouquet', age=2, start_x=.64)
        x = self.r.performance.pet_x
        self.e.get_dizzy()
        self.assertAlmostEqual(self.r._render_foot().x(), self.r._geometry()[1] * x)
        self.r.advance_scene(.1)
        self.assertIsNone(self.r.performance)
        self.assertAlmostEqual(self.r.life.x, x)

    def test_starting_trick_during_gift_freezes_current_position_and_does_not_resume_gift(self):
        self.r.performance = GiftPerformance('flower_bouquet', age=1.5, start_x=.64)
        x = self.r.performance.pet_x
        self.assertTrue(self.e.perform_trick('clone'))
        self.r.begin_trick('clone')
        self.assertIsNone(self.r.performance)
        self.e.advance(2.51)
        self.r.advance_scene(.01)
        self.assertEqual(self.r.life.state, 'idle')
        self.assertAlmostEqual(self.r.life.x, x)

    def test_rapid_poke_and_pet_interrupt_gift_at_current_room_position(self):
        for kind in ('poke', 'pet'):
            self.r.performance = GiftPerformance('flower_bouquet', age=1.7, start_x=.64)
            x = self.r.performance.pet_x
            self.m.interaction_started.emit(kind)
            self.assertIsNone(self.r.performance)
            self.assertAlmostEqual(self.r.life.x, x)

    def test_spicy_room_motion_survives_position_preservation(self):
        self.e.set_pinned(False)
        self.e.grounded = True
        self.e.elapsed = .3
        self.e.set_buff({'scale': 1, 'behavior_remaining': 10, 'remaining_seconds': 60})
        base_x = self.r._geometry()[1] * self.r.life.x
        self.assertGreater(abs(self.r._render_foot().x() - base_x), 1)

    def test_repeated_roll_and_gift_cycles_never_accumulate_a_new_origin(self):
        origin = self.r.life.x
        for _ in range(3):
            self.m.buy_item('music_box', True)
            self.r.advance_scene(7.01)
            self.assertAlmostEqual(self.r.life.x, origin)
            self.assertTrue(self.e.perform_trick('screen_roll'))
            self.r.begin_trick('screen_roll')
            self.e.advance(12.01)
            self.r.advance_scene(.01)
            self.assertAlmostEqual(self.r.life.x, origin)


class DesktopAnchorTests(unittest.TestCase):
    def test_stationary_click_and_landing_squash_restore_x_at_both_edges(self):
        for x in (83, 1517):
            e = PetEngine(WorkArea(0, 0, 1600, 1000))
            e.x = x
            for _ in range(3):
                e.click()
                advance(e, 3.2)
                self.assertAlmostEqual(e.x, x, places=5)
                self.assertEqual(e.y, 1000)

    def test_resting_breath_does_not_permanently_push_pet_inward(self):
        e = PetEngine(WorkArea(-1600, -100, 1600, 1000))
        e.x = -1534
        advance(e, 3.2)
        self.assertAlmostEqual(e.x, -1534, places=5)

    def test_dragging_replaces_old_rest_anchor_and_keeps_new_pinned_location(self):
        e = PetEngine(WorkArea(0, 0, 1600, 1000))
        e.x = 83
        e.click()
        advance(e, .1)
        e.begin_drag()
        e.drag_to(650, 420, 1000)
        e.set_pinned(True)
        e.release_drag(0, 0)
        advance(e, 4)
        self.assertEqual((e.x, e.y), (650, 420))

    def test_real_throws_keep_inertia_and_do_not_return_to_old_anchor(self):
        e = PetEngine(WorkArea(0, 0, 1600, 1000))
        e.x = 83
        advance(e, .05)
        e.begin_drag()
        e.drag_to(700, 400, 0)
        e.release_drag(900, 0)
        advance(e, 3)
        self.assertGreater(e.x, 800)
        self.assertTrue(e.grounded)

    def test_unpinned_location_restores_on_same_screen_instead_of_resetting_to_primary_corner(self):
        w = PetWindow(ROOT / 'assets/skins/default')
        w.timer.stop()
        try:
            area = w.engine.area
            w.engine.place(area.left + area.width * .42, area.top + area.height * .6)
            state = w.capture_position()
            expected = QPointF(w.engine.x, w.engine.y)
            w.reset_to_primary()
            w.restore_position(state)
            self.assertFalse(w.engine.pinned)
            self.assertLess((QPointF(w.engine.x, w.engine.y) - expected).manhattanLength(), 1e-6)
            w.engine.advance(1 / 60)
            self.assertGreater(w.engine.y, expected.y())
        finally:
            w.stop()
            w.hide()
            w.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
