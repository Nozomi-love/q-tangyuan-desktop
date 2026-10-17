"""Shop subpages, spinning-top gift, silent income and contextual dialogue."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent,QPointF,QRectF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models import Catalog,GameRules,PetData,PetModel
from main import PetApplication
from dashboard import DashboardWindow
from save_manager import SaveManager
APP=QApplication.instance() or QApplication(['dialogue-tests']);APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
ARTIFACTS=ROOT/'tests/artifacts'/datetime.now().strftime('shop-dialogue-%Y%m%d-%H%M%S-%f')
ARTIFACTS.mkdir(parents=True,exist_ok=False)

class IncomeAndDialogueTests(unittest.TestCase):
    def model(self,**kw):return PetModel(PetData(coins=1000,**kw),rng=random.Random(1))
    def feedback(self,model):
        result=[];model.feedback.connect(lambda text,tone:result.append((text,tone)));return result
    def test_ninety_second_income_is_silent_immediate_and_once(self):
        model=self.model();messages=self.feedback(model);changes=[];model.collectible_changed.connect(changes.append)
        model.advance(89.9);self.assertEqual(model.data.coins,1000)
        model.advance(.1);self.assertTrue(1010<=model.data.coins<=1020)
        self.assertEqual(model.data.affection_exp,5);self.assertEqual(model.data.stats['total_gifts'],1)
        self.assertEqual(messages,[]);self.assertNotIn(True,changes);self.assertFalse(model.has_collectible)
        coins=model.data.coins;self.assertFalse(model.claim_collectible());model.advance(30)
        self.assertEqual(model.data.coins,coins)
    def test_every_interval_pays_without_waiting_for_clicks(self):
        model=self.model();model.advance(270)
        self.assertEqual(model.data.stats['total_gifts'],3)
        self.assertTrue(1030<=model.data.coins<=1060);self.assertEqual(model.data.affection_exp,15)
    def test_debug_income_also_never_offers_a_collectible(self):
        model=self.model();messages=self.feedback(model)
        self.assertTrue(model.offer_collectible());self.assertFalse(model.has_collectible)
        self.assertEqual(messages,[]);self.assertEqual(model.data.stats['total_gifts'],1)
    def test_legacy_pending_income_settles_original_amount_and_upgrade_once(self):
        data=PetData(coins=100,affection_exp=499,pending_reward={'coins':19,'remaining_seconds':17.5})
        model=PetModel(data)
        self.assertEqual((model.data.coins,model.data.affection_level,model.data.affection_exp),(149,2,4))
        self.assertEqual(model.data.stats['total_gifts'],1);self.assertEqual(model.restored_income_levels,[2])
        restored=PetModel(PetData.from_dict(model.snapshot()))
        self.assertEqual(restored.snapshot(),model.snapshot());self.assertFalse(restored.claim_collectible())
    def test_save_round_trip_keeps_timer_without_repeating_auto_income(self):
        file=ARTIFACTS/'income.json';model=self.model();model.advance(95)
        save=SaveManager(file);save.update_game(model.snapshot())
        restored=PetModel(SaveManager(file).load_game_state());before=restored.data.coins
        restored.advance(84.9);self.assertEqual(restored.data.coins,before)
        restored.advance(.1);self.assertEqual(restored.data.stats['total_gifts'],2)
    def test_automatic_income_keeps_level_and_achievement_signals(self):
        model=self.model(affection_exp=499,stats={'total_gifts':2})
        levels=[];achievements=[];model.upgraded.connect(levels.append);model.achievement_unlocked.connect(achievements.append)
        model.advance(90);self.assertEqual(levels,[2])
        self.assertTrue(any(row['id']=='gifts_three' for row in achievements))
    def test_poke_quote_survives_daily_coin_drop(self):
        model=self.model();messages=self.feedback(model);model.poke()
        self.assertEqual(model.data.coins,1002);self.assertEqual(model.data.affection_exp,2)
        self.assertEqual(messages,[('急咯急咯','interaction')])
    def test_poke_hungry_quote_still_uses_low_hunger_exp(self):
        model=self.model(hunger=20);messages=self.feedback(model);model.poke()
        self.assertEqual(model.data.affection_exp,1);self.assertEqual(messages[-1][0],'急咯急咯')
    def test_full_hunger_food_quote_does_not_grant_exp(self):
        model=self.model(hunger=100);messages=self.feedback(model);model.buy_item('sugar',True)
        self.assertEqual(messages[-1],('别吃，别吃，饿吗，饿死了吗。','interaction'))
        self.assertEqual((model.data.hunger,model.data.affection_exp,model.data.coins),(100,0,990))
    def test_food_reaching_full_is_not_an_already_full_feed(self):
        model=self.model(hunger=95);messages=self.feedback(model);model.buy_item('sugar',True)
        self.assertEqual(model.data.hunger,100);self.assertNotEqual(messages[-1][0],'别吃，别吃，饿吗，饿死了吗。')
    def test_starving_recovery_has_its_own_line(self):
        model=self.model(hunger=0);messages=self.feedback(model);model.buy_item('water',True)
        self.assertEqual(messages[-1][0],'这波有救了，我又能弹了！');self.assertFalse(model.starving)
    def test_dialogue_rotation_does_not_change_coin_randomness(self):
        model=self.model();state=model.rng.getstate()
        self.assertEqual([model.dialogue('pet_head') for _ in range(3)],['太舒服了！','这个摸摸头，可以的。','太舒服了！'])
        self.assertEqual(model.rng.getstate(),state)
    def test_dialogue_config_rejects_invalid_or_oversize_values(self):
        source=json.loads((ROOT/'config/catalog.json').read_text(encoding='utf-8'))
        for lines in ('text',[],[3],['x'*81]):
            bad=deepcopy(source);bad['dialogues']['poke']=lines
            with self.subTest(lines=lines),self.assertRaises(ValueError):Catalog(bad)
    def test_spinning_top_is_third_tier_gift_with_no_hunger_or_buff(self):
        model=self.model(hunger=0);messages=self.feedback(model);item=model.item('spinning_top')
        self.assertEqual((item['tier'],item['cost'],item['exp'],item['hunger']),(3,180,240,0))
        self.assertTrue(model.buy_item('spinning_top',True));self.assertTrue(model.starving)
        self.assertEqual((model.data.coins,model.data.affection_exp),(820,240))
        self.assertEqual(model.data.stats['total_presents'],1);self.assertEqual(model.data.stats['total_feeds'],0)
        self.assertEqual(messages[-1][0],'陀螺收到，突然就想转起来了！')
    def test_spinning_top_inventory_save_and_give_charges_once(self):
        file=ARTIFACTS/'top.json';model=self.model();model.buy_item('spinning_top')
        save=SaveManager(file);save.update_game(model.snapshot());restored=PetModel(SaveManager(file).load_game_state())
        self.assertEqual(restored.data.inventory['spinning_top'],1);restored.use_item('spinning_top')
        self.assertEqual((restored.data.coins,restored.data.affection_exp),(820,240))

class ShopAndBubbleTests(unittest.TestCase):
    def setUp(self):
        file=ARTIFACTS/(self._testMethodName+'.json')
        SaveManager(file).update_game(PetData(coins=1000).to_dict(),{'pinned':True,'screen':APP.primaryScreen().name(),'x_ratio':.6,'y_ratio':.6})
        self.controller=PetApplication(APP,save_path=file,skins_root=file.parent/(self._testMethodName+'-skins'))
        self.model=self.controller.model;self.panel=self.controller.dashboard;self.pet=self.controller.window
        self.model.set_overlay_visible(True);self.panel.hide()
    def tearDown(self):
        self.controller.stop();self.pet.deleteLater();self.panel.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_food_and_gift_are_exactly_two_independent_subtabs(self):
        self.panel.summon();self.panel.show_section("shop", animate=False)
        self.assertEqual([self.panel.shop_tabs.tabText(i) for i in range(2)],['食物','礼物'])
        for key,item in self.model.catalog.items.items():
            index=0 if item['category']=='food' else 1
            self.assertTrue(self.panel.shop_tabs.widget(index).isAncestorOf(self.panel.shop_buttons[key][0]))
        self.assertFalse(self.panel.shop_tabs.isAncestorOf(self.panel.shop_trick_buttons['screen_roll'][0]))
        self.assertTrue(self.panel.shop_trick_buttons['screen_roll'][0].isVisible())
    def test_nested_tab_edges_stay_aligned_and_scroll_areas_are_independent(self):
        self.panel.summon();self.panel.show_section("shop", animate=False)
        for width in (700,900,1100):
            self.panel.resize(width,760);QTest.qWait(20)
            bar=self.panel.shop_tabs.tabBar()
            self.assertEqual(bar.tabRect(0).left(),0)
            self.assertLessEqual(abs(bar.tabRect(1).right()-self.panel.shop_tabs.width()+1),2)
        food,gift=(self.panel.shop_tabs.widget(i) for i in (0,1))
        food.verticalScrollBar().setValue(100);self.panel.shop_tabs.setCurrentIndex(1)
        self.assertEqual(gift.verticalScrollBar().value(),0)
    def test_income_does_not_clear_or_replace_current_poke_message(self):
        self.model.poke();text=self.pet.bubble._text;queued=list(self.pet.bubble._notifications)
        self.model.advance(90)
        self.assertEqual(self.pet.bubble._text,text);self.assertEqual(list(self.pet.bubble._notifications),queued)
        self.assertFalse(self.pet.bubble._showing_gift)
    def test_repeated_pokes_never_queue_the_same_interaction(self):
        for _ in range(10):self.model.poke()
        self.assertEqual(self.pet.bubble._text,'急咯急咯')
        self.assertFalse(any(row[1]=='interaction' for row in self.pet.bubble._notifications))
    def test_no_currency_bubble_can_be_reenabled_by_legacy_callback(self):
        self.pet.show_message('急咯急咯','interaction');self.pet.show_collectible(True)
        self.assertFalse(self.pet.bubble._gift);self.assertFalse(self.pet.bubble._showing_gift)
        self.assertEqual(self.pet.bubble._text,'急咯急咯')
        self.assertTrue(self.pet.bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    def test_drag_and_dizzy_use_contextual_lines(self):
        self.pet.drag_started.emit();self.assertEqual(self.pet.bubble._text,'你们是来抓我的吗？')
        self.controller._dizzy();self.assertEqual(self.pet.bubble._text,'阿一古，头都转晕啦！')
    def test_spinning_top_buttons_and_full_feed_quote_are_live(self):
        self.panel.summon()
        self.panel.shop_buttons['spinning_top'][0].click();self.assertEqual(self.model.data.inventory['spinning_top'],1)
        self.panel.inventory_widgets['spinning_top'][2].click();self.assertEqual(self.model.data.affection_exp,240)
        self.assertIn('陀螺收到',self.pet.bubble._text)
        self.model.set_hunger(100);self.controller.feed_action.trigger()
        self.assertEqual(self.pet.bubble._text,'别吃，别吃，饿吗，饿死了吗。')
        self.assertEqual(self.model.data.affection_exp,240)

if __name__=='__main__':unittest.main(verbosity=2)
