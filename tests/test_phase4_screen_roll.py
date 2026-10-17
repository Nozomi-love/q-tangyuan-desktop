"""Permanent screen-roll purchase, route, universal drawing and cancellation."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import unittest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models import Catalog,PetData,PetModel
from pet_engine import PetEngine,SkinRenderer,WorkArea
from pet_window import PetWindow
from dashboard import DashboardWindow
from save_manager import SaveManager
from main import PetApplication
from verify_phase4_native import make_gif
APP=QApplication.instance() or QApplication(['screen-roll-tests'])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
ARTIFACTS=ROOT/'tests/artifacts'/datetime.now().strftime('screen-roll-%Y%m%d-%H%M%S-%f')
ARTIFACTS.mkdir(parents=True,exist_ok=False)

class RollModelTests(unittest.TestCase):
    def test_purchase_is_permanent_and_charged_exactly_once(self):
        model=PetModel(PetData(coins=200))
        before=model.snapshot()
        self.assertFalse(model.has_trick('screen_roll'))
        self.assertTrue(model.buy_trick('screen_roll'))
        self.assertEqual(model.data.coins,80)
        self.assertEqual(model.data.purchased_tricks,['screen_roll'])
        self.assertTrue(model.has_trick('screen_roll'))
        self.assertFalse(model.buy_trick('screen_roll'))
        self.assertEqual(model.data.coins,80)
        for key in ('inventory','stats','hunger','affection_exp','affection_level'):
            self.assertEqual(model.snapshot()[key],before[key])
    def test_unknown_and_unaffordable_purchases_are_noops(self):
        for key in ('screen_roll','missing'):
            model=PetModel(PetData(coins=119));before=model.snapshot()
            self.assertFalse(model.buy_trick(key));self.assertEqual(model.snapshot(),before)
    def test_debug_level_override_does_not_purchase_shop_tricks(self):
        model=PetModel();model.set_debug_unlock(True,authorized=True)
        self.assertTrue(model.has_trick('ball'))
        self.assertFalse(model.has_trick('screen_roll'))
        self.assertFalse(model.record_trick('screen_roll'))
    def test_twelve_second_show_twenty_second_cooldown_no_exp(self):
        model=PetModel(PetData(coins=120));model.buy_trick('screen_roll')
        self.assertTrue(model.record_trick('screen_roll'))
        self.assertEqual(model.trick_busy,12)
        self.assertEqual(model.trick_cooldowns['screen_roll'],20)
        self.assertEqual(model.data.affection_exp,0)
        self.assertFalse(model.record_trick('screen_roll'))
        model.advance(12);self.assertFalse(model.can_perform_trick('screen_roll'))
        model.advance(8);self.assertTrue(model.can_perform_trick('screen_roll'))
    def test_cancellation_clears_busy_but_keeps_cooldown(self):
        model=PetModel(PetData(purchased_tricks=['screen_roll']))
        model.record_trick('screen_roll');model.finish_trick('flip')
        self.assertEqual(model.trick_busy,12)
        model.finish_trick('screen_roll')
        self.assertEqual(model.trick_busy,0)
        self.assertEqual(model.trick_cooldowns['screen_roll'],20)
    def test_starving_owner_cannot_perform(self):
        model=PetModel(PetData(hunger=0,purchased_tricks=['screen_roll']))
        self.assertFalse(model.can_perform_trick('screen_roll'))
    def test_old_save_defaults_empty_and_purchase_round_trips(self):
        folder=ARTIFACTS/'save';folder.mkdir();file=folder/'save.json'
        file.write_text(json.dumps({'schema_version':5,'coins':200,'future':{'keep':1},'window':{'pinned':True,'x_ratio':.55,'y_ratio':.5}}),encoding='utf-8')
        save=SaveManager(file);data,position=save.load_all()
        self.assertEqual(data.purchased_tricks,[])
        model=PetModel(data);model.buy_trick('screen_roll');save.update_game(model.snapshot(),position)
        restored=PetModel(SaveManager(file).load_game_state())
        self.assertTrue(restored.has_trick('screen_roll'));self.assertEqual(restored.data.coins,80)
        self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['future'],{'keep':1})
        self.assertFalse(restored.buy_trick('screen_roll'))
    def test_invalid_ownership_and_catalog_are_rejected(self):
        for owned in ('screen_roll',['screen_roll','screen_roll'],[7],['../screen_roll']):
            with self.subTest(owned=owned),self.assertRaises(ValueError):PetData.from_dict({'purchased_tricks':owned})
        source=json.loads((ROOT/'config/catalog.json').read_text(encoding='utf-8'))
        for value in (0,-1,True):
            bad=deepcopy(source);bad['trick_products']['screen_roll']['cost']=value
            with self.assertRaises(ValueError):Catalog(bad)

class RollEngineTests(unittest.TestCase):
    def engine(self,pinned=True,area=None):
        engine=PetEngine(area or WorkArea(-1920,-200,1920,1080))
        engine.set_pinned(pinned)
        if pinned:engine.place(engine.area.left+engine.area.width*.55,engine.area.top+engine.area.height*.55)
        else:engine.grounded=True
        return engine
    def center(self,engine):
        return SkinRenderer.body_transform(engine,QPointF(engine.x,engine.y)).map(QPointF(0,-PetEngine.BODY_HEIGHT/2))
    def test_lap_visits_four_edges_once_clockwise_and_returns_home(self):
        engine=self.engine();home=(engine.x,engine.y)
        self.assertTrue(engine.perform_trick('screen_roll'))
        rect=engine._roll_rect
        points=[]
        for index in range(1201):
            engine.elapsed=engine._trick_started+1+index/120
            p=self.center(engine);points.append(p)
            self.assertLessEqual(min(abs(p.x()-rect.left()),abs(p.x()-rect.right()),abs(p.y()-rect.top()),abs(p.y()-rect.bottom())),1e-6)
            self.assertEqual((engine.x,engine.y),home)
        for p in (rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight()):
            self.assertLess(min(math.hypot(q.x()-p.x(),q.y()-p.y()) for q in points),4)
        self.assertLess((points[-1]-points[0]).manhattanLength(),1e-6)
        traveled=sum(math.hypot((b-a).x(),(b-a).y()) for a,b in zip(points,points[1:]))
        self.assertAlmostEqual(traveled,2*(rect.width()+rect.height()),delta=12)
        self.assertGreater(engine.visual_angle,360)
        engine.advance(1.01)
        self.assertEqual(engine.active_trick,'');self.assertEqual(engine.visual_offset,QPointF())
        self.assertEqual((engine.x,engine.y),home);self.assertTrue(engine.pinned)
    def test_free_grounded_pet_also_returns_without_fake_landing(self):
        engine=self.engine(False);home=(engine.x,engine.y);lands=engine.landing_count
        self.assertTrue(engine.perform_trick('screen_roll'))
        for _ in range(720):engine.advance(1/60)
        engine.advance(.001)
        self.assertEqual(engine.active_trick,'');self.assertEqual(engine.landing_count,lands)
        self.assertEqual((engine.x,engine.y),home);self.assertFalse(engine.pinned)
    def test_normal_tiny_and_negative_coordinate_screens(self):
        for area in (WorkArea(0,0,1707,1067),WorkArea(-2560,-1200,2560,1440),WorkArea(0,0,800,600)):
            engine=self.engine(area=area)
            self.assertTrue(engine.perform_trick('screen_roll'))
            for t in (1,2.5,5,7.5,10.9):
                engine.elapsed=engine._trick_started+t
                self.assertTrue(QRectF(area.left,area.top,area.width,area.height).contains(self.center(engine)))
        self.assertFalse(self.engine(area=WorkArea(0,0,260,240)).perform_trick('screen_roll'))
    def test_bad_padding_does_not_start_or_change_coordinates(self):
        for padding in (float('nan'),float('inf'),-1,5000):
            engine=self.engine();home=(engine.x,engine.y)
            self.assertFalse(engine.perform_trick('screen_roll',roll_padding=padding))
            self.assertEqual(engine.active_trick,'');self.assertEqual((engine.x,engine.y),home)
    def test_mutual_exclusion_and_flat_air_drag_rejection(self):
        for state in ('starving','manual_flat','held','dragging'):
            engine=self.engine();setattr(engine,state,True)
            self.assertFalse(engine.perform_trick('screen_roll'))
        engine=self.engine(False);engine.grounded=False
        self.assertFalse(engine.perform_trick('screen_roll'))
        engine=self.engine();engine.perform_trick('screen_roll')
        self.assertFalse(engine.perform_trick('flip'))
    def test_resize_pin_change_reset_and_starvation_cancel(self):
        for operation in ('resize','pin','reset','hunger'):
            engine=self.engine();home=(engine.x,engine.y)
            engine.perform_trick('screen_roll');engine.advance(3)
            if operation=='resize':engine.set_work_area(WorkArea(-1920,-200,1800,1000))
            elif operation=='pin':engine.set_pinned(False)
            elif operation=='reset':engine.reset()
            else:engine.set_starving(True)
            self.assertEqual(engine.active_trick,'');self.assertEqual(engine.visual_offset,QPointF())
            if operation=='hunger':self.assertEqual((engine.x,engine.y),home)
    def test_chili_does_not_move_the_saved_anchor_during_roll(self):
        engine=self.engine(False);engine.set_buff({'item_id':'chili','scale':1,'behavior_remaining':12,'remaining_seconds':60})
        home=(engine.x,engine.y);engine.perform_trick('screen_roll')
        for _ in range(300):engine.advance(1/60)
        self.assertEqual((engine.x,engine.y),home)
    def test_approach_and_return_are_upright_and_continuous(self):
        engine=self.engine();engine.perform_trick('screen_roll')
        self.assertEqual(engine.visual_offset,QPointF());self.assertEqual(engine.visual_angle,0)
        engine.elapsed=.5;self.assertEqual(engine.visual_angle,0)
        engine.elapsed=11.5
        self.assertAlmostEqual(engine.visual_angle%360,0)
        engine.elapsed=12;self.assertLess(engine.visual_offset.manhattanLength(),1e-6)

class RollWindowAndDashboardTests(unittest.TestCase):
    def setUp(self):
        self.window=PetWindow(ROOT/'assets/skins/default');self.window.timer.stop()
        self.window.set_pinned(True);area=self.window.engine.area
        self.window.engine.place(area.left+area.width*.55,area.top+area.height*.55)
        self.window._sync_window()
    def tearDown(self):
        self.window.stop();self.window.hide();self.window.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_window_follows_drawing_capture_position_stays_home(self):
        saved=self.window.capture_position();home=self.window.pos()
        finished=[];self.window.trick_finished.connect(finished.append)
        self.assertTrue(self.window.perform_trick('screen_roll'))
        self.window.engine.advance(4);self.window._sync_window()
        self.assertNotEqual(self.window.pos(),home)
        self.assertEqual(self.window.capture_position(),saved)
        canvas=QRectF(self.window.rect())
        self.assertTrue(canvas.contains(self.window.renderer.scene_bounds(self.window.engine,self.window.local_foot())))
        self.window.engine.advance(8.01);self.window._sync_window();self.window._sync_window()
        self.assertEqual(self.window.pos(),home);self.assertEqual(finished,['screen_roll'])
    def test_click_running_pet_returns_home_without_poke_or_drag(self):
        clicks=[];self.window.clicked.connect(lambda:clicks.append(1))
        home=self.window.capture_position();self.window.perform_trick('screen_roll')
        self.window.engine.advance(4);self.window._sync_window()
        point=self.window.renderer.body_transform(self.window.engine,self.window.local_foot()).map(QPointF(0,-58)).toPoint()
        self.assertTrue(self.window._inside_body(QPointF(point)))
        QTest.mouseClick(self.window,Qt.MouseButton.LeftButton,pos=point)
        self.assertEqual(self.window.engine.active_trick,'');self.assertEqual(self.window.capture_position(),home)
        self.assertFalse(self.window._pressed);self.assertEqual(clicks,[])
    def test_default_png_and_gif_crown_buff_fit_every_edge_and_canvas(self):
        gif=ARTIFACTS/'gif';gif.mkdir();(gif/'idle.gif').write_bytes(make_gif())
        (gif/'manifest.json').write_text(json.dumps({'schema_version':1,'name':'roll gif','author':'tests','states':{'idle':'idle.gif'}}),encoding='utf-8')
        for folder in (ROOT/'assets/skins/default',gif):
            self.assertTrue(self.window.set_skin(folder))
            self.window.set_accessories({'head':'crown','face':'sunglasses','effect':'steam','offset_y':-30})
            self.window.set_buff({'item_id':'sesame','scale':1.2,'color':'#45424a','remaining_seconds':60})
            self.assertTrue(self.window.perform_trick('screen_roll'))
            engine=self.window.engine
            canvas=QRectF(self.window.rect());area=QRectF(engine.area.left,engine.area.top,engine.area.width,engine.area.height)
            started=engine._trick_started
            for index in range(41):
                engine.elapsed=started+1+index*.25;self.window._sync_window()
                local=self.window.renderer.scene_bounds(engine,self.window.local_foot())
                self.assertTrue(canvas.contains(local),(folder,index,local))
                world=self.window.renderer.scene_bounds(engine,QPointF(engine.x,engine.y))
                self.assertTrue(area.contains(world),(folder,index,world,area))
            engine.cancel_trick();self.window._sync_window()
    def test_appearance_changes_return_home_without_changing_pin(self):
        home=self.window.capture_position()
        for change in ('accessories','skin'):
            self.window.perform_trick('screen_roll');self.window.engine.advance(4);self.window._sync_window()
            if change=='accessories':self.window.set_accessories({'head':'crown','offset_y':-30})
            else:self.assertTrue(self.window.set_skin(ROOT/'assets/skins/default'))
            self.assertEqual(self.window.engine.active_trick,'')
            self.assertEqual(self.window.capture_position(),home)
    def test_strawberry_particles_stay_with_rolling_body(self):
        self.window.set_buff({'item_id':'strawberry','scale':1,'color':'#f58fb1','remaining_seconds':60})
        self.window.perform_trick('screen_roll')
        engine=self.window.engine;area=QRectF(engine.area.left,engine.area.top,engine.area.width,engine.area.height)
        for t in (1,3.5,6,8.5,10.9):
            engine.elapsed=engine._trick_started+t;self.window._sync_window()
            self.assertTrue(area.contains(self.window.renderer.scene_bounds(engine,QPointF(engine.x,engine.y))))
            self.assertTrue(QRectF(self.window.rect()).contains(self.window.renderer.scene_bounds(engine,self.window.local_foot())))
    def test_shop_filter_purchase_and_buttons_update_live(self):
        model=PetModel(PetData(coins=120));panel=DashboardWindow(model)
        try:
            panel.show();panel.tabs.setCurrentIndex(1);panel.shop_tabs.setCurrentIndex(0)
            self.assertFalse(panel.shop_groups['trick'].isHidden())
            self.assertTrue(panel.shop_groups['food'].isVisible());self.assertFalse(panel.shop_groups['gift'].isVisible())
            buy,perform,status=panel.shop_trick_buttons['screen_roll']
            self.assertTrue(buy.isEnabled());self.assertFalse(perform.isEnabled())
            buy.click();self.assertEqual(model.data.coins,0)
            self.assertFalse(buy.isEnabled());self.assertTrue(perform.isEnabled())
            self.assertTrue(panel.trick_buttons['screen_roll'].isEnabled())
            events=[];panel.trick_requested.connect(events.append)
            perform.click();panel.trick_buttons['screen_roll'].click()
            self.assertEqual(events,['screen_roll','screen_roll'])
        finally:panel.close();panel.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_controller_menu_purchase_run_cancel_and_reset(self):
        folder=ARTIFACTS/'controller';folder.mkdir();file=folder/'save.json'
        save=SaveManager(file);save.update_game(PetData(coins=120).to_dict(),{'pinned':True,'screen':APP.primaryScreen().name(),'x_ratio':.55,'y_ratio':.5})
        controller=PetApplication(APP,save_path=file,skins_root=folder/'skins')
        try:
            controller.window.timer.stop();model=controller.model;pet=controller.window
            self.assertFalse(controller.trick_actions['screen_roll'].isEnabled())
            model.buy_trick('screen_roll');self.assertTrue(controller.trick_actions['screen_roll'].isEnabled())
            controller.trick_actions['screen_roll'].trigger()
            self.assertEqual(pet.engine.active_trick,'screen_roll');self.assertEqual(model.trick_busy,12)
            pet.engine.advance(4);pet._sync_window();controller._save()
            self.assertAlmostEqual(json.loads(file.read_text(encoding='utf-8'))['window']['x_ratio'],.55)
            controller.reset_action.trigger()
            self.assertEqual(pet.engine.active_trick,'');self.assertEqual(model.trick_busy,0)
            self.assertGreater(model.trick_cooldowns['screen_roll'],0)
        finally:controller.stop()

if __name__=='__main__':unittest.main(verbosity=2)
