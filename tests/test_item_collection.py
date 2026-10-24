"""First collection: commerce, legacy saves and isolated scene performances."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import subprocess
import sys
import unittest

from PySide6.QtCore import QPointF, QRectF, Qt, QEvent
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models import Catalog, PetData, PetModel
from pet_engine import PetEngine, SkinRenderer, WorkArea, PetState
from home_scene import GiftPerformance, IllustratedRoomCanvas
from item_expansion import NEW_GIFTS, NEW_FOODS, paint_food_extra
from illustrated_assets import IconAtlas, ICON_IDS, plain_text
from dashboard import DashboardWindow
from save_manager import SaveManager

APP=QApplication.instance() or QApplication(['item-collection-tests'])
APP.setQuitOnLastWindowClosed(False)
ART=ROOT/'tests/artifacts'/datetime.now().strftime('collection-%Y%m%d-%H%M%S-%f')
ART.mkdir(parents=True)
NEW_ACCESSORIES=('cooling_cap','demon_hood','summit_backpack','mini_gnar_hat')
NEW_FURNITURE=('esports_chair','training_dummy','tactics_screen','postmatch_studio')


class CollectionTests(unittest.TestCase):
    def test_exact_first_collection_and_prices(self):
        c=Catalog.load()
        self.assertEqual(len(c.items),28); self.assertEqual(len(c.furniture),23)
        self.assertEqual(len(c.accessory_products),7)
        for key in NEW_GIFTS|NEW_FOODS:
            item=c.items[key]; tier=(c.food_tiers if key in NEW_FOODS else c.gift_tiers)[str(item['tier'])]
            self.assertEqual(item['cost'],tier['cost'])
            self.assertEqual(item['exp'],0 if key in NEW_FOODS else tier['exp'])
            self.assertEqual(item['hunger'],tier['hunger'] if key in NEW_FOODS else 0)

    def test_retired_not_in_future_rewards(self):
        c=Catalog.load(); retired={'accessory_sprout','accessory_bow','effect_fireflies'}
        self.assertTrue(all(c.perks[k]['retired'] for k in retired))
        self.assertFalse(retired & {p for m in c.milestones for p in m['perks']})
        m=PetModel(PetData(affection_level=30))
        for key,slot in [('sprout','head'),('bow','head'),('fireflies','effect')]:
            self.assertFalse(m.equip_accessory(slot,key))

    def test_retired_already_worn_survives_until_changed(self):
        for head in ('sprout','bow'):
            m=PetModel(PetData.from_dict({'affection_level':30,'accessories':{'head':head,'effect':'fireflies'}}))
            self.assertEqual(m.effective_accessories()['head'],head)
            self.assertEqual(m.effective_accessories()['effect'],'fireflies')
            self.assertTrue(m.equip_accessory('head',head))
            self.assertTrue(m.equip_accessory('head','crown'))
            self.assertFalse(m.equip_accessory('head',head))

    def test_reworked_ids_levels_and_ownership_unchanged(self):
        m=PetModel(PetData(affection_level=30,coins=11))
        for slot,key,name in [('head','orange','解控橘子帽'),('effect','steam','红温热气'),('effect','rainbow','冠军聚光灯')]:
            perk=('effect_' if slot=='effect' else 'accessory_')+key
            self.assertEqual(m.catalog.perks[perk]['name'],name)
            self.assertTrue(m.equip_accessory(slot,key))
            self.assertEqual(m.data.coins,11)

    def test_new_accessories_require_purchase_even_at_level_30(self):
        m=PetModel(PetData(affection_level=30,coins=10000))
        for key in NEW_ACCESSORIES:
            slot=m.catalog.accessory_products[key]['slot']
            self.assertFalse(m.has_perk('accessory_'+key))
            self.assertFalse(m.equip_accessory(slot,key))
            before=m.data.coins
            self.assertTrue(m.buy_accessory(key)); self.assertTrue(m.equip_accessory(slot,key))
            self.assertEqual(m.data.coins,before-m.catalog.accessory_products[key]['cost'])
            self.assertTrue(m.buy_accessory(key)); self.assertEqual(m.data.coins,before-m.catalog.accessory_products[key]['cost'])

    def test_trial_does_not_give_permanent_store_accessories(self):
        m=PetModel(); m.set_debug_unlock(True,authorized=True)
        self.assertTrue(m.equip_accessory('head','cooling_cap'))
        m.set_debug_unlock(False,authorized=True)
        self.assertEqual(m.effective_accessories()['head'],'')
        self.assertEqual(m.data.purchased_accessories,[])

    def test_foods_restore_only_actual_hunger_once(self):
        for key in NEW_FOODS:
            m=PetModel(PetData(coins=10000,hunger=98)); events=[]
            m.presentation_requested.connect(events.append); xp=m._lifetime_exp()
            self.assertTrue(m.buy_item(key,feed_now=True))
            self.assertEqual(m.data.hunger,100); self.assertEqual(m._lifetime_exp(),xp)
            self.assertEqual(len(events),1); self.assertEqual(events[0]['hunger_gain'],2)
            self.assertFalse(m.use_item(key)); self.assertEqual(len(events),1)

    def test_gifts_settle_once_and_supply_dedicated_dialogue(self):
        for key in NEW_GIFTS:
            m=PetModel(PetData(coins=10000,hunger=42)); events=[]
            m.presentation_requested.connect(events.append)
            self.assertTrue(m.buy_item(key)); self.assertEqual(events,[])
            xp=m._lifetime_exp(); self.assertTrue(m.use_item(key))
            self.assertEqual(m._lifetime_exp()-xp,m.catalog.items[key]['exp'])
            self.assertEqual(m.data.hunger,42); self.assertEqual(len(events),1)
            self.assertEqual(events[0]['effect'],key); self.assertTrue(events[0]['dialogue'])

    def test_cola_cools_chili_without_clearing_other_flavors(self):
        m=PetModel(PetData(coins=10000))
        m.buy_item('chili',True); self.assertTrue(m.buff_view())
        m.buy_item('iced_cola',True); self.assertEqual(m.buff_view(),{})
        m.buy_item('strawberry',True); m.buy_item('iced_cola',True)
        self.assertEqual(m.buff_view()['item_id'],'strawberry')

    def test_store_insufficient_funds_changes_nothing(self):
        for key in NEW_GIFTS|NEW_FOODS:
            m=PetModel(PetData(coins=0)); before=m.snapshot()
            self.assertFalse(m.buy_item(key,True)); self.assertEqual(m.snapshot(),before)
        for key in NEW_ACCESSORIES:
            m=PetModel(PetData(coins=0)); before=m.snapshot()
            self.assertFalse(m.buy_accessory(key)); self.assertEqual(m.snapshot(),before)

    def test_furniture_purchase_slot_and_repeated_purchase(self):
        m=PetModel(PetData(coins=10000))
        for key in NEW_FURNITURE:
            product=m.catalog.furniture[key]; old=m.data.coins
            self.assertTrue(m.buy_furniture(key)); self.assertTrue(m.equip_furniture(product['slot'],key))
            self.assertEqual(m.data.coins,old-product['price'])
            m.buy_furniture(key); self.assertEqual(m.data.coins,old-product['price'])
        self.assertFalse(m.equip_furniture('wall','esports_chair'))

    def test_new_ids_restart_restore_without_touching_player_save(self):
        m=PetModel(PetData(coins=20000,affection_level=30))
        for key in NEW_ACCESSORIES: m.buy_accessory(key)
        m.equip_accessory('head','cooling_cap'); m.equip_accessory('back','summit_backpack')
        for key in NEW_FURNITURE:
            m.buy_furniture(key); m.equip_furniture(m.catalog.furniture[key]['slot'],key)
        m.buy_item('form_dice'); m.set_accessory_offset(-17)
        file=ART/'restart-save.json'; manager=SaveManager(file); manager.load_game_state(); manager.update_game(m.snapshot())
        code="from save_manager import SaveManager; import sys,json; m=SaveManager(sys.argv[1]); print(json.dumps(m.load_game_state().to_dict(),ensure_ascii=True))"
        child=subprocess.run([sys.executable,'-c',code,str(file)],cwd=ROOT,capture_output=True,text=True,check=True)
        restored=json.loads(child.stdout)
        for field in ('purchased_accessories','accessories','equipped_furniture','owned_furniture','inventory','coins'):
            self.assertEqual(restored[field],m.snapshot()[field])


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.engine=PetEngine(WorkArea(0,0,1200,800)); self.engine.set_pinned(True)
        self.renderer=SkinRenderer(ROOT/'assets/skins/default')
        self.room=IllustratedRoomCanvas(self.engine,lambda:self.renderer)
        self.room.resize(750,660); self.room._animation_timer.stop()
        self.room.set_home_state(PetData().to_dict()); self.room.life.x=.56
        self.origin=(self.engine.x,self.engine.y)
    def tearDown(self):
        self.room.stop(); self.room.deleteLater(); self.renderer.stop()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_all_gifts_restore_own_origin_and_leave_no_prop(self):
        for key in NEW_GIFTS:
            self.room.life.x=.56
            self.room.present_item({'item_id':key,'category':'gift','duration':7})
            self.room.advance_scene(3.5); self.assertIsNotNone(self.room.performance)
            self.room.advance_scene(3.6)
            self.assertIsNone(self.room.performance); self.assertEqual(self.room.life.x,.56)
            self.assertEqual(self.room._last_toy,''); self.assertEqual((self.engine.x,self.engine.y),self.origin)
            image=QImage(200,200,QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
            p=QPainter(image); self.room._paint_gift(p,200,200); p.end()
            self.assertFalse(any(bytes(image.constBits())))

    def test_gift_interruption_keeps_actual_room_position(self):
        self.room.present_item({'item_id':'kiting_rope','category':'gift'})
        self.room.advance_scene(2.1); actual=self.room.performance.pet_x
        self.room.record_interaction('poke')
        self.assertIsNone(self.room.performance); self.assertEqual(self.room.life.x,actual)
        self.assertEqual((self.engine.x,self.engine.y),self.origin)

    def test_gift_poses_differ_and_end_neutral(self):
        poses=[]
        for key in NEW_GIFTS:
            perf=GiftPerformance(key,age=2.1); poses.append(perf.pose)
            perf.age=7; self.assertEqual(perf.pose,(1.,1.,0.,0.))
        self.assertEqual(len(set(poses)),4)

    def test_real_scene_gifts_render_unique_frames(self):
        hashes=[]
        for key in sorted(NEW_GIFTS):
            self.room.present_item({'item_id':key,'category':'gift'}); self.room.advance_scene(2)
            pix=self.room.grab(); file=ART/(key+'.png'); self.assertTrue(pix.save(str(file)))
            hashes.append(hashlib.sha256(file.read_bytes()).hexdigest()); self.room.interact(cancel_gift=True)
        self.assertEqual(len(set(hashes)),4)

    def test_food_extras_are_different_and_expire(self):
        hashes=[]
        for key in sorted(NEW_FOODS):
            image=QImage(400,400,QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
            p=QPainter(image); paint_food_extra(p,self.room.atlas,key,1.4,QRectF(100,100,150,150)); p.end()
            hashes.append(hashlib.sha256(bytes(image.constBits())).hexdigest())
            image.fill(Qt.GlobalColor.transparent); p=QPainter(image)
            paint_food_extra(p,self.room.atlas,key,3.1,self.room.pet_bounds()); p.end()
            self.assertFalse(any(bytes(image.constBits())))
        self.assertEqual(len(set(hashes)),4)

    def test_all_new_accessories_render_and_keep_bounds(self):
        for key in NEW_ACCESSORIES:
            slot='back' if key=='summit_backpack' else 'head'
            self.renderer.set_accessories({slot:key,'offset_y':-30})
            self.assertEqual(self.renderer.accessories[slot],key)
            self.room.grab()
            bounds=self.renderer.accessory_bounds(self.engine.state)
            self.assertTrue(bounds.contains(self.renderer.anchor_rect(self.engine.state)))

    def test_orange_visual_does_not_clear_dizziness(self):
        self.renderer.set_accessories({'head':'orange'})
        self.engine.dizzy_until=self.engine.elapsed+3
        self.room.grab(); self.assertEqual(self.engine.state,PetState.DIZZY)

    def test_click_furniture_does_not_change_currency_or_desktop(self):
        data=PetData(); original=data.coins
        for key in ('esports_chair','training_dummy','tactics_screen'):
            slot='wall' if key=='tactics_screen' else 'corner'
            data.equipped_furniture[slot]=key
            self.room.set_home_state(data.to_dict()); self.assertTrue(self.room.activate_furniture(key))
            self.room.advance_scene(1.1); self.room.grab()
            self.room.advance_scene(3.1); self.assertIsNone(self.room.performance)
            self.assertEqual(data.coins,original); self.assertEqual((self.engine.x,self.engine.y),self.origin)
            # Chair/dummy restore their exact performance origin first. Screen
            # viewing has no performance lock, so its quiet return has finished.
            self.assertEqual(self.room.life.x,.48 if key=='tactics_screen' else .56)

    def test_tactics_screen_retains_only_last_three_local_events(self):
        model=PetModel(PetData(coins=10000,affection_level=30))
        model.poke(); model.pet_head()
        model.buy_item('sugar',True); model.buy_item('form_dice',True)
        self.room.set_home_state(model.snapshot())
        self.assertEqual(self.room.recent_interactions,['crown','sugar','form_dice'])
        history=model.snapshot()['interaction_history']
        self.room.record_interaction('poke')
        self.room.present_item({'item_id':'sugar','category':'food'})
        self.assertEqual(self.room.recent_interactions,['crown','sugar','form_dice'])
        self.assertEqual(model.snapshot()['interaction_history'],history)

    def test_ac_cools_room_visual_view_only(self):
        data=PetData(); data.equipped_furniture['wall']='air_conditioner'; data.air_conditioner_on=True
        self.room.set_home_state(data.to_dict()); self.assertTrue(self.room._view().cooling)
        data.air_conditioner_on=False; self.room.set_home_state(data.to_dict()); self.assertFalse(self.room._view().cooling)

    def test_training_dummy_approaches_hits_and_returns(self):
        perf=GiftPerformance('training_dummy',duration=3,start_x=.56)
        perf.advance(1.1)
        self.assertLess(perf.pet_x,.33)
        perf.advance(1.9)
        self.assertAlmostEqual(perf.pet_x,.56)
        self.assertEqual((self.engine.x,self.engine.y),self.origin)

    def test_dice_order_is_stable_inside_one_performance(self):
        perf=GiftPerformance('form_dice')
        self.assertEqual(set(perf.dice_faces),{3,6,9})
        order=perf.dice_faces
        for i in range(20): perf.advance(.2); self.assertEqual(perf.dice_faces,order)

    def test_new_gifts_interrupted_by_trick_do_not_restore_old_origin(self):
        self.room.present_item({'item_id':'kiting_rope','category':'gift'})
        self.room.advance_scene(2.1); actual=self.room.performance.pet_x
        self.assertTrue(self.engine.perform_trick('flip'))
        self.room.advance_scene(.05)
        self.assertIsNone(self.room.performance)
        self.assertEqual(self.room._room_trick_origin,actual)
        self.engine.cancel_trick(); self.room.advance_scene(.05)
        self.assertEqual(self.room.life.x,actual)


class UiAndArtTests(unittest.TestCase):
    def test_new_art_is_individual_and_cached(self):
        atlas=IconAtlas(); hashes=set()
        for key in NEW_GIFTS|NEW_FOODS|set(NEW_ACCESSORIES)|set(NEW_FURNITURE)|{'red_steam','cleanse_orange','champion_spotlight'}:
            pix=atlas.pixmap(key); file=ROOT/'assets/item_icons'/f'{key}.png'; before=file.read_bytes()
            self.assertEqual((pix.width(),pix.height()),(80,80))
            self.assertEqual(pix.toImage().pixelColor(0,0).alpha(),0)
            hashes.add(hashlib.sha256(before).hexdigest()); atlas.pixmap(key); self.assertEqual(file.read_bytes(),before)
        self.assertEqual(len(hashes),19); self.assertEqual(len(ICON_IDS),116)

    def test_ui_hides_retired_and_routes_new_slot(self):
        model=PetModel(PetData(coins=10000)); w=DashboardWindow(model)
        w.accessory_requested.connect(model.equip_accessory)
        try:
            self.assertEqual(w.head_combo.findData('sprout'),-1); self.assertEqual(w.head_combo.findData('bow'),-1)
            self.assertEqual(w.aura_choices.findData('fireflies'),-1)
            for key in NEW_ACCESSORIES:
                buy,equip=w.accessory_shop_buttons[key]; buy.click(); w.refresh(); equip.click()
                slot=model.catalog.accessory_products[key]['slot']
                self.assertEqual(model.data.accessories[slot],key)
            self.assertEqual(w.head_combo.itemText(w.head_combo.findData('orange')),'解控橘子帽')
        finally:
            w.stop(); w.deleteLater(); APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_new_names_and_dialogues_have_no_emoji(self):
        c=Catalog.load()
        for key in NEW_GIFTS|NEW_FOODS:
            self.assertEqual(plain_text(c.items[key]['name']),c.items[key]['name'])
            for line in c.dialogues[c.items[key]['dialogue']]: self.assertEqual(plain_text(line),line)


if __name__=='__main__': unittest.main()
