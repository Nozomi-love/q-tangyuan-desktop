"""Gift body rotation, exact music dialogue and threefold store prices."""
from datetime import datetime
from pathlib import Path
import json, math, random, sys, unittest
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models import Catalog,GameRules,PetModel,PetData
from home_scene import GiftPerformance,RoomPetView
from dashboard import DashboardWindow
from pet_engine import PetEngine,WorkArea,SkinRenderer
from save_manager import SaveManager
APP=QApplication.instance() or QApplication(['gift-economy-tests'])
APP.setQuitOnLastWindowClosed(False)
ART=ROOT/'tests/artifacts'/datetime.now().strftime('gift-economy-unit-%Y%m%d-%H%M%S-%f');ART.mkdir(parents=True)

class GiftEconomyTests(unittest.TestCase):
    def test_every_store_price_is_tripled_but_free_furniture_stays_free(self):
        c=Catalog.load()
        self.assertEqual({k:v['cost'] for k,v in c.food_tiers.items()},{'1':30,'2':75,'3':135})
        self.assertEqual({k:v['cost'] for k,v in c.gift_tiers.items()},{'1':60,'2':210,'3':540})
        for item in c.items.values():
            tiers=c.food_tiers if item['category']=='food' else c.gift_tiers
            self.assertEqual(item['cost'],tiers[str(item['tier'])]['cost'])
        self.assertEqual(c.trick_products['screen_roll']['cost'],360)
        self.assertEqual(c.furniture['lotus_cushion']['price'],120)
        self.assertEqual(c.furniture['warm_lamp']['price'],270)
        self.assertEqual(c.furniture['sakura_room']['price'],300)
        self.assertEqual([v['price'] for v in c.furniture.values() if v['default']],[0,0,0])

    def test_sugar_model_config_and_menu_rule_have_same_new_price(self):
        self.assertEqual(GameRules().sugar_cost,30)
        for accelerated in (False,True):
            rule=GameRules.from_catalog(ROOT/'config/catalog.json',accelerated)
            self.assertEqual(rule.sugar_cost,30)
            model=PetModel(rules=rule);model.feed_sugar()
            self.assertEqual((model.data.coins,model.data.hunger,model.data.affection_exp),(70,95,0))

    def test_exact_gift_budget_debits_once_and_use_does_not_charge_again(self):
        m=PetModel(PetData(coins=539));before=m.snapshot()
        self.assertFalse(m.buy_item('spinning_top'));self.assertEqual(m.snapshot(),before)
        m.data.coins=540;self.assertTrue(m.buy_item('spinning_top'))
        self.assertEqual((m.data.coins,m.data.inventory['spinning_top']),(0,1))
        self.assertTrue(m.use_item('spinning_top'));self.assertEqual(m.data.coins,0)
        self.assertEqual(m.data.affection_exp,240);self.assertFalse(m.use_item('spinning_top'))

    def test_old_balance_inventory_and_owned_goods_are_not_rescaled(self):
        file=ART/'legacy.json'
        raw={'schema_version':5,'coins':8819,'inventory':{'spinning_top':1},
             'owned_furniture':['cheese_room','cloud_cushion','wood_bowl','lotus_cushion'],
             'purchased_tricks':['screen_roll'],'future':{'kept':True}}
        file.write_text(json.dumps(raw),encoding='utf8');save=SaveManager(file);data,pos=save.load_all()
        model=PetModel(data);self.assertEqual(model.data.coins,8819)
        self.assertTrue(model.use_item('spinning_top'));self.assertEqual(model.data.coins,8819)
        self.assertTrue(model.has_trick('screen_roll'));self.assertTrue(model.equip_furniture('rug','lotus_cushion'))
        save.update_game(model.snapshot(),pos)
        self.assertEqual(SaveManager(file).load_game_state().coins,8819)
        self.assertTrue(json.loads(file.read_text(encoding='utf8'))['future']['kept'])

    def test_online_income_is_unchanged_under_the_price_plan(self):
        m=PetModel(PetData(),rng=random.Random(2));m.advance(89.9)
        self.assertEqual(m.data.coins,100);m.advance(.1)
        self.assertTrue(110<=m.data.coins<=120);self.assertEqual(m.data.affection_exp,5)

    def test_music_gift_uses_exact_caption_and_event_includes_it(self):
        m=PetModel(PetData(coins=2000));lines=[];events=[]
        m.feedback.connect(lambda text,tone:lines.append(text));m.presentation_requested.connect(events.append)
        m.buy_item('music_box',True);m.buy_item('music_box');m.use_item('music_box')
        self.assertEqual([e['dialogue'] for e in events],['听见你说~','听见你说~'])
        self.assertEqual(lines.count('听见你说~'),2)

    def test_top_performs_eight_turns_with_smooth_acceleration_and_finish(self):
        top=GiftPerformance('spinning_top');top.age=.6;self.assertAlmostEqual(top.spin_angle,0)
        middle=top.duration/2;top.age=middle;angle=top.spin_angle;top.age=middle+.01
        self.assertGreater((top.spin_angle-angle)/.01,720)
        angles=[]
        for i in range(701):top.age=i*.01;angles.append(top.spin_angle)
        self.assertTrue(all(b>=a-1e-7 for a,b in zip(angles,angles[1:])))
        self.assertAlmostEqual(angles[-1],2880);self.assertAlmostEqual(angles[-1]%360,0)

    def test_other_gifts_do_not_acquire_top_rotation(self):
        for key in ('music_box','paper_star','flower_bouquet'):
            self.assertEqual(GiftPerformance(key,age=3).spin_angle,0)

class GiftSceneTests(unittest.TestCase):
    def setUp(self):
        self.m=PetModel(PetData(coins=5000,affection_level=6));self.e=PetEngine(WorkArea(0,0,1600,900));self.e.set_pinned(True)
        self.p=DashboardWindow(self.m,self.e);self.p.show();APP.processEvents();self.p.room._animation_timer.stop()
    def tearDown(self):
        self.p.stop();self.p.hide();self.p.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_actual_room_rotation_changes_body_transform_but_keeps_desktop_and_center(self):
        room=self.p.room;renderer=room.renderer_provider();self.m.buy_item('spinning_top',True)
        room.advance_scene(3.4);before=(self.e.x,self.e.y,self.e.elapsed,self.e.visual_angle,self.e.pinned)
        view=room._view();self.assertGreater(view.visual_angle,360)
        center=QPointF(0,-self.e.BODY_HEIGHT/2);foot=room._render_foot()
        a=renderer.body_transform(view,foot).map(center)
        b=renderer.body_transform(RoomPetView(self.e,view.local_pose),foot).map(center)
        self.assertLess(math.hypot(a.x()-b.x(),a.y()-b.y()),1e-6)
        self.assertNotEqual(renderer.body_transform(view,foot),renderer.body_transform(RoomPetView(self.e,view.local_pose),foot))
        room.grab();self.assertEqual(before,(self.e.x,self.e.y,self.e.elapsed,self.e.visual_angle,self.e.pinned))
    def test_spin_with_crown_and_sesame_stays_inside_room_and_queued_music_keeps_caption(self):
        self.m.equip_accessory('head','crown');self.m.buy_item('sesame',True)
        room=self.p.room;room._food_age=100;self.e.set_buff(self.m.buff_view())
        room.renderer_provider().set_accessories(self.m.effective_accessories())
        self.m.buy_item('spinning_top',True);self.m.buy_item('music_box',True)
        self.p.resize(820,650);self.p.show_section('shop',animate=False);APP.processEvents()
        for i in range(1,65):
            room.performance.age=i/10;bounds=room.pet_bounds()
            self.assertGreaterEqual(bounds.top(),147);self.assertLessEqual(bounds.bottom(),room.height()-10)
            self.assertGreaterEqual(bounds.left(),5);self.assertLessEqual(bounds.right(),room.width()-5)
            room.grab()
        room.advance_scene(1);self.assertEqual(room.performance.item_id,'music_box')
        self.assertEqual(room._message,'听见你说~')

if __name__=='__main__':unittest.main()
