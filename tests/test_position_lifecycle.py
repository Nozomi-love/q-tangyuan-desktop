"""Positions must settle, not merely match a logical coordinate on one frame."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pet_engine import PetEngine,WorkArea,SkinRenderer
from home_scene import RoomLife,IllustratedRoomCanvas,GiftPerformance
from item_expansion import NEW_GIFTS
from pet_window import PetWindow

APP=QApplication.instance() or QApplication(['position-lifecycle'])
APP.setQuitOnLastWindowClosed(False)
GIFTS=('spinning_top','music_box','paper_star','flower_bouquet','tes_guitar','tes_microphone',*sorted(NEW_GIFTS))
TRICKS=('flip','clone','ball','screen_roll','disco')

def tick(room,seconds):
    for _ in range(round(seconds*60)): room.advance_scene(1/60)


class LifeReturnTests(unittest.TestCase):
    def test_interrupted_walk_eventually_returns_to_rug(self):
        life=RoomLife(random.Random(4));life.start_activity('bowl');life.advance(3)
        x=life.x;life.interact();self.assertEqual(life.x,x)
        life.advance(5)
        self.assertAlmostEqual(life.x,.48)
        self.assertEqual(life.state,'idle')

    def test_stale_idle_position_recovers_before_starting_new_activity(self):
        life=RoomLife(random.Random(4));life.x=.70;life.wait=1000
        life.advance(6)
        self.assertAlmostEqual(life.x,.48)

    def test_passive_blocked_state_does_not_hold_pet_off_rug_forever(self):
        life=RoomLife(random.Random(4));life.x=.68;life.interact()
        life.advance(8,blocked=True)
        self.assertAlmostEqual(life.x,.48)
        self.assertEqual(life.state,'idle')

    def test_return_never_overshoots_at_different_frame_rates(self):
        for fps in (30,60,144):
            life=RoomLife(random.Random(4));life.x=.30;life.interact()
            positions=[]
            for _ in range(fps*6): life.advance(1/fps);positions.append(life.x)
            self.assertAlmostEqual(life.x,.48)
            self.assertTrue(all(.30-1e-8<=x<=.48+1e-8 for x in positions))


class SceneReturnTests(unittest.TestCase):
    def setUp(self):
        self.e=PetEngine(WorkArea(0,0,1600,1000));self.e.set_pinned(True)
        self.renderer=SkinRenderer(ROOT/'assets/skins/default')
        self.r=IllustratedRoomCanvas(self.e,lambda:self.renderer)
        self.r.resize(1200,800);self.r._animation_timer.stop();self.r.life.wait=1000
        self.desktop=(self.e.x,self.e.y)
    def tearDown(self):
        self.r.stop();self.r.deleteLater();self.renderer.stop()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def assertHome(self):
        self.assertAlmostEqual(self.r.life.x,.48,places=6)
        point=self.r._pet_transform().map(self.r._render_foot()+self.r._view().visual_offset)
        self.assertAlmostEqual(point.x(),self.r._base_foot().x(),places=5)
        self.assertAlmostEqual(point.y(),self.r._base_foot().y(),places=5)
        self.assertEqual((self.e.x,self.e.y),self.desktop)

    def test_happy_expression_does_not_cancel_autonomous_walk(self):
        self.r.life.start_activity('bowl');self.r.advance_scene(1)
        with patch('home_scene.monotonic',return_value=20):
            self.r.show();self.r._last_scene_tick=19.98
            self.e.enjoy_interaction(2);self.r._repaint_if_visible()
        self.assertEqual(self.r.life.state,'walk_bowl')

    def test_autonomous_nap_survives_its_own_expression_signal(self):
        self.r.life.rng.choice=lambda choices:'nap';self.r.life.wait=0;self.r.life.quiet=7
        self.r.mood_requested.connect(self.e.enjoy_interaction)
        self.r.show()
        with patch('home_scene.monotonic',return_value=20):
            self.r._last_scene_tick=19.98;self.r._repaint_if_visible()
        self.assertEqual(self.r.life.state,'nap')
        with patch('home_scene.monotonic',return_value=20.02):self.r._repaint_if_visible()
        self.assertEqual(self.r.life.state,'nap')

    def test_zoom_does_not_multiply_room_walking_distance(self):
        for ratio in (.40,.55,.60):
            self.r.life.x=ratio
            foot=self.r._render_foot()
            self.assertAlmostEqual(self.r._pet_transform().map(foot).x(),foot.x(),places=5)

    def test_room_does_not_inherit_desktop_drop_height(self):
        self.e.set_pinned(False);self.e.place(600,300)
        foot=self.r._render_foot()
        self.assertAlmostEqual(foot.y(),self.r._base_foot().y())

    def test_all_gifts_finish_then_return_to_rug(self):
        for gift in GIFTS:
            with self.subTest(gift=gift):
                self.r.life.x=.66;self.r.performance=GiftPerformance(gift,start_x=.66)
                tick(self.r,7.1)
                self.assertIsNone(self.r.performance)
                self.assertAlmostEqual(self.r.life.x,.66)
                tick(self.r,6);self.assertHome()

    def test_user_interrupt_cancels_stale_queued_gifts_then_returns_home(self):
        self.r.life.x=.67
        self.r.present_item({'item_id':'flower_bouquet','category':'gift'})
        self.r.present_item({'item_id':'music_box','category':'gift'})
        self.r.advance_scene(2);actual=self.r.performance.pet_x
        self.r.record_interaction('poke')
        self.assertAlmostEqual(self.r.life.x,actual)
        self.assertEqual(self.r._gift_queue,[])
        tick(self.r,6);self.assertIsNone(self.r.performance);self.assertHome()

    def test_all_tricks_restore_their_start_then_settle_home(self):
        for trick in TRICKS:
            with self.subTest(trick=trick):
                self.r.life.x=.62;self.e.perform_trick(trick);self.r.begin_trick(trick)
                self.e.advance(13);self.r.advance_scene(.01)
                self.assertAlmostEqual(self.r.life.x,.62)
                tick(self.r,6);self.assertHome()

    def test_all_trick_interrupts_return_home_without_old_offsets(self):
        for trick in TRICKS:
            with self.subTest(trick=trick):
                self.r.life.x=.60;self.e.perform_trick(trick);self.r.begin_trick(trick)
                self.e.elapsed+=.6;self.r.advance_scene(.01)
                self.e.cancel_trick();self.r.record_interaction('pet')
                tick(self.r,6);self.assertHome()

    def test_starving_and_dizzy_can_recover_room_location(self):
        for state in ('starving','manual_flat','dizzy'):
            self.r.life.x=.67
            if state=='dizzy':self.e.dizzy_until=self.e.elapsed+20
            else:setattr(self.e,state,True)
            tick(self.r,6);self.assertAlmostEqual(self.r.life.x,.48)
            self.e.dizzy_until=0;self.e.starving=self.e.manual_flat=False

    def test_gift_position_is_frozen_while_hidden_and_settles_on_return(self):
        self.r.life.x=.64;self.r.performance=GiftPerformance('kiting_rope',age=2,start_x=.64)
        self.r.interact(cancel_gift=True)
        x=self.r.life.x;self.r.hide();self.r._repaint_if_visible()
        self.assertEqual(self.r.life.x,x)
        self.r.show();tick(self.r,6);self.assertHome()

    def test_repeated_walk_interrupt_feed_and_trick_cycles_do_not_drift(self):
        for _ in range(4):
            self.r.start_activity('bowl');tick(self.r,2)
            self.r.record_interaction('poke');self.r.show_food('sugar',15)
            tick(self.r,2);self.e.perform_trick('flip');self.r.begin_trick('flip')
            self.e.advance(1.2);self.r.advance_scene(.02);tick(self.r,6)
            self.assertHome()

    def test_spicy_motion_reduces_to_zero_before_ending(self):
        self.e.set_pinned(False);self.e.grounded=True;self.e.elapsed=.3
        self.e.set_buff({'behavior_remaining':.001,'remaining_seconds':10})
        self.assertLess(abs(self.r._render_foot().x()-self.r._base_foot().x()),.01)
        self.e.set_buff({})
        self.assertEqual(self.r._render_foot(),self.r._base_foot())

    def test_spicy_motion_does_not_start_unrelated_autonomy(self):
        self.r.life.x=.65;self.e.set_buff({'behavior_remaining':10,'remaining_seconds':60})
        tick(self.r,6);self.assertEqual(self.r.life.state,'idle')
        self.e.set_buff({});tick(self.r,6);self.assertHome()

    def test_camera_returns_after_resize_skin_and_buff_changes(self):
        self.r.life.x=.68;self.r.record_interaction('pet');tick(self.r,6)
        for width,height in ((760,420),(1100,650),(1200,800)):
            self.r.resize(width,height)
            self.e.skin_scale=1.5
            self.e.set_buff({'scale':1.2,'remaining_seconds':60})
            self.renderer.set_accessories({'head':'crown','effect':'steam','offset_y':-30})
            self.r.grab()
            self.e.skin_scale=1;self.e.set_buff({});self.renderer.set_accessories({})
            self.assertHome()


class DesktopReturnTests(unittest.TestCase):
    def test_place_ends_transient_tricks_and_squash(self):
        for trick in TRICKS:
            e=PetEngine(WorkArea(0,0,1600,1000));e.set_pinned(True);e.perform_trick(trick)
            e.elapsed+=.5;e.rebound();e.place(700,500)
            self.assertEqual(e.active_trick,'');self.assertEqual(e.visual_offset,QPointF())
            self.assertEqual(e.spring,0);self.assertEqual((e.x,e.y),(700,500))

    def test_pin_change_ends_all_transient_tricks(self):
        for trick in TRICKS:
            e=PetEngine(WorkArea(0,0,1600,1000));e.set_pinned(True);e.perform_trick(trick)
            e.elapsed+=.4;origin=(e.x,e.y);e.set_pinned(False)
            self.assertEqual(e.active_trick,'');self.assertEqual((e.x,e.y),origin)

    def test_saving_during_edge_squash_keeps_resting_x(self):
        w=PetWindow(ROOT/'assets/skins/default');w.timer.stop()
        try:
            e=w.engine;e.set_pinned(False)
            e.x=e.area.left+e.BODY_WIDTH/2+1;e.y=e.area.bottom;e.grounded=True
            before=w.capture_position();e.click();e.advance(.02)
            self.assertNotEqual(e.x,e._rest_x)
            self.assertAlmostEqual(w.capture_position()['x_ratio'],before['x_ratio'])
        finally:
            w.stop();w.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main()
