"""Food/gift separation, 8h hunger, harder affection and navigation revision."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import random
import sys
import unittest
from PySide6.QtCore import QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models import Catalog,GameRules,PetData,PetModel,EXP_PER_LEVEL
from dashboard import DashboardWindow
from main import PetApplication
from save_manager import SaveManager,SaveDataError
APP=QApplication.instance() or QApplication(['balance-revision'])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
ARTIFACTS=ROOT/'tests/artifacts'/datetime.now().strftime('balance-%Y%m%d-%H%M%S-%f')
ARTIFACTS.mkdir(parents=True,exist_ok=False)

def rich(**kw):return PetModel(PetData(coins=10000,**kw),rng=random.Random(0))

class BalanceModelTests(unittest.TestCase):
    def test_normal_full_hunger_lasts_exactly_eight_online_hours(self):
        pet=rich(hunger=100)
        pet.advance(8*3600-.1)
        self.assertEqual(pet.data.hunger,1)
        self.assertFalse(pet.starving)
        pet.advance(.1)
        self.assertTrue(pet.starving)
        self.assertEqual(pet.data.hunger,0)
        self.assertAlmostEqual(pet.data.stats['total_idle_seconds'],28800)
    def test_rules_and_catalog_both_use_288_seconds(self):
        self.assertEqual(GameRules().hunger_seconds,288)
        self.assertEqual(GameRules.from_catalog(ROOT/'config/catalog.json').hunger_seconds,288)
        self.assertEqual(GameRules.from_catalog(ROOT/'config/catalog.json',True).hunger_seconds,2)
    def test_each_level_requires_ten_times_the_old_experience(self):
        self.assertEqual(EXP_PER_LEVEL,500)
        for level in range(1,31):
            self.assertEqual(rich(affection_level=level).exp_required,level*500)
    def test_food_never_levels_up_even_at_threshold(self):
        for key,item in Catalog.load().items.items():
            if item['category']!='food':continue
            with self.subTest(key=key):
                pet=rich(hunger=0,affection_exp=499)
                levels=[];pet.upgraded.connect(levels.append)
                pet.buy_item(key,True)
                self.assertEqual((pet.data.affection_level,pet.data.affection_exp),(1,499))
                self.assertEqual(pet.data.hunger,item['hunger'])
                self.assertEqual(levels,[])
                self.assertEqual(pet.data.stats['total_feeds'],1)
    def test_food_tiers_have_distinct_recovery_and_zero_exp(self):
        items=[item for item in Catalog.load().items.values() if item['category']=='food']
        self.assertEqual(len(items),7)
        for tier,hunger in ((1,15),(2,35),(3,65)):
            same=[i for i in items if i['tier']==tier]
            self.assertTrue(same)
            self.assertTrue(all(i['hunger']==hunger and i['exp']==0 for i in same))
    def test_gift_tiers_gain_distinct_exp_without_hunger(self):
        for key,amount in (('paper_star',20),('flower_bouquet',80),('music_box',240)):
            with self.subTest(key=key):
                pet=rich(hunger=13)
                item=pet.item(key)
                self.assertTrue(pet.buy_item(key,True))
                self.assertEqual(pet.data.hunger,13)
                self.assertEqual(pet.data.affection_exp,amount)
                self.assertEqual(pet.data.coins,10000-item['cost'])
                self.assertEqual(pet.data.stats['total_presents'],1)
                self.assertEqual(pet.data.stats['total_feeds'],0)
                self.assertEqual(pet.data.stats['total_gifts'],0)
    def test_storing_then_giving_gift_charges_only_at_purchase(self):
        pet=rich(hunger=60)
        pet.buy_item('music_box')
        self.assertEqual((pet.data.affection_exp,pet.data.stats['total_presents']),(0,0))
        coins=pet.data.coins
        self.assertTrue(pet.use_item('music_box'))
        self.assertEqual(pet.data.coins,coins)
        self.assertEqual((pet.data.hunger,pet.data.affection_exp),(60,240))
        self.assertEqual(pet.data.inventory['music_box'],0)
        self.assertFalse(pet.use_item('music_box'))
        self.assertEqual(pet.data.affection_exp,240)
    def test_giving_gift_does_not_rescue_starvation_or_trigger_fed(self):
        pet=rich(hunger=0)
        fed=[];gifted=[]
        pet.fed.connect(lambda:fed.append(True));pet.gifted.connect(lambda:gifted.append(True))
        pet.buy_item('paper_star',True)
        self.assertTrue(pet.starving)
        self.assertEqual(fed,[])
        self.assertEqual(gifted,[True])
        self.assertNotIn('rescue',pet.data.unlocked_achievements)
        self.assertNotIn('first_feed',pet.data.unlocked_achievements)
    def test_food_rescue_remains_but_does_not_gain_affection(self):
        pet=rich(hunger=0)
        pet.buy_item('sugar',True)
        self.assertFalse(pet.starving)
        self.assertIn('rescue',pet.data.unlocked_achievements)
        self.assertEqual(pet.data.affection_exp,0)
    def test_gift_crosses_level_boundary_and_awards_once(self):
        pet=rich(affection_exp=490)
        levels=[];pet.upgraded.connect(levels.append)
        pet.buy_item('paper_star',True)
        self.assertEqual((pet.data.affection_level,pet.data.affection_exp),(2,10))
        self.assertEqual(pet.data.coins,10000-20+30)
        self.assertEqual(levels,[2])
    def test_unaffordable_gift_changes_nothing(self):
        pet=PetModel(PetData(coins=19))
        before=pet.snapshot()
        self.assertFalse(pet.buy_item('paper_star',True))
        self.assertEqual(pet.snapshot(),before)
    def test_earned_guardian_title_is_now_aiyigu(self):
        pet=rich(affection_level=6)
        self.assertIn('阿一古',pet.data.titles)
        self.assertTrue(pet.equip_title('阿一古'))
        self.assertNotIn('✨ 汤圆守护神',pet.data.titles)
    def test_legacy_title_aliases_rename_and_deduplicate(self):
        data=PetData.from_dict({'titles':['糯米团子','✨ 汤圆守护神','汤圆守护神','阿一古'],'equipped_title':'✨ 汤圆守护神'})
        self.assertEqual(data.titles,['糯米团子','阿一古'])
        self.assertEqual(data.equipped_title,'阿一古')
    def test_existing_level_and_raw_experience_are_retained(self):
        data=PetData.from_dict({'affection_level':8,'affection_exp':287})
        pet=PetModel(data)
        self.assertEqual((pet.data.affection_level,pet.data.affection_exp),(8,287))
        self.assertEqual(pet.exp_required,4000)
    def test_food_exp_and_gift_hunger_cannot_be_injected_in_catalog(self):
        original=json.loads((ROOT/'config/catalog.json').read_text(encoding='utf-8'))
        for key,field,value in [('sugar','exp',10),('paper_star','hunger',5),('water','tier',4)]:
            bad=deepcopy(original);bad['items'][key][field]=value
            with self.subTest(key=key),self.assertRaises(ValueError):Catalog(bad)
        with self.assertRaises(ValueError):GameRules(sugar_exp=1)
    def test_gifts_do_not_replace_active_flavor(self):
        pet=rich()
        pet.buy_item('sesame',True);pet.advance(5)
        buff=deepcopy(pet.data.active_buff)
        pet.buy_item('flower_bouquet',True)
        self.assertEqual(pet.data.active_buff,buff)
        self.assertEqual(pet.data.flavors_seen,['sesame'])

class BalanceSaveTests(unittest.TestCase):
    def test_schema_four_migrates_title_and_gift_stats_with_exact_backup(self):
        folder=ARTIFACTS/'migration';folder.mkdir()
        file=folder/'save_data.json'
        raw={'schema_version':4,'coins':234,'hunger':63,'affection_level':6,'affection_exp':287,
             'titles':['糯米团子','✨ 汤圆守护神'],'equipped_title':'✨ 汤圆守护神',
             'selected_skin_id':'user_'+'a'*32,'inventory':{'sugar':2},
             'accessories':{'head':'crown','offset_y':-14},'future':{'keep':True},
             'stats':{'total_gifts':3,'total_feeds':7},
             'window':{'pinned':True,'x_ratio':.4,'y_ratio':.3}}
        original=json.dumps(raw,ensure_ascii=False).encode();file.write_bytes(original)
        save=SaveManager(file);data,window=save.load_all();save.update_game(data.to_dict(),window)
        now=json.loads(file.read_bytes())
        self.assertEqual(now['schema_version'],5)
        self.assertEqual((now['coins'],now['hunger'],now['affection_level'],now['affection_exp']),(234,63,6,287))
        self.assertEqual(now['equipped_title'],'阿一古')
        self.assertEqual(now['stats']['total_presents'],0)
        self.assertEqual(now['stats']['total_gifts'],3)
        self.assertEqual(now['accessories']['offset_y'],-14)
        self.assertEqual(now['future'],{'keep':True})
        backups=list(folder.glob('save_data.json.bak.*'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),original)
        save.update_game(data.to_dict(),window)
        self.assertEqual(len(list(folder.glob('save_data.json.bak.*'))),1)
    def test_present_inventory_and_stats_round_trip_without_refilling_rewards(self):
        file=ARTIFACTS/'presents-save.json';save=SaveManager(file)
        pet=rich();pet.buy_item('flower_bouquet');pet.buy_item('paper_star',True)
        save.update_game(pet.snapshot())
        data=SaveManager(file).load_game_state();restored=PetModel(data)
        self.assertEqual(restored.snapshot(),pet.snapshot())
        self.assertTrue(restored.use_item('flower_bouquet'))
        self.assertEqual(restored.data.affection_exp,100)
        self.assertEqual(restored.data.stats['total_presents'],2)
    def test_new_high_exp_under_threshold_round_trips(self):
        file=ARTIFACTS/'high-exp.json';save=SaveManager(file)
        save.update_game(PetData(affection_exp=499).to_dict())
        self.assertEqual(SaveManager(file).load_game_state().affection_exp,499)
        with self.assertRaises(SaveDataError):save.update_game(PetData(affection_exp=500).to_dict())

class NavigationAndCommerceTests(unittest.TestCase):
    def setUp(self):
        self.model=rich(affection_level=6)
        self.window=DashboardWindow(self.model);self.window.summon();QTest.qWait(40)
    def tearDown(self):
        self.window.close();self.window.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_five_main_pages_and_three_independent_dressing_subpages(self):
        self.assertEqual([self.window.tabs.tabText(i) for i in range(5)],['状态与背包','免费商城','成就图鉴','装扮','设置'])
        self.assertEqual([self.window.dress_tabs.tabText(i) for i in range(3)],['皮肤衣橱','挂件装扮','特技与等级奖励'])
        self.assertTrue(self.window.dress_tabs.widget(0).isAncestorOf(self.window.skin_combo))
        self.assertTrue(self.window.dress_tabs.widget(1).isAncestorOf(self.window.head_combo))
        self.assertTrue(self.window.dress_tabs.widget(2).isAncestorOf(self.window.trick_buttons['flip']))
        self.assertTrue(self.window.tabs.widget(4).isAncestorOf(self.window.pin_check))
    def test_navigation_spans_divider_and_has_no_native_overlap(self):
        self.assertTrue(self.window.tabs.tabBar().isHidden())
        self.assertEqual(list(self.window.nav_buttons), ['home','furniture','shop','dress','achievements'])
        for width in (700,900,1100):
            self.window.resize(width,760);QTest.qWait(25)
            buttons=list(self.window.nav_buttons.values())
            for left,right in zip(buttons,buttons[1:]):
                a=left.mapTo(self.window,left.rect().topRight()).x()
                b=right.mapTo(self.window,right.rect().topLeft()).x()
                self.assertLess(a,b)
            for section,button in self.window.nav_buttons.items():
                button.click();QTest.qWait(20)
                self.assertEqual(self.window.current_section,section)
                self.assertTrue(self.window.room.isVisible())
    def test_food_cards_have_no_affection_and_gifts_have_no_hunger(self):
        self.window.refresh()
        for key,item in self.model.catalog.items.items():
            text=self.window.shop_details[key].text()
            if item['category']=='food':
                self.assertIn('饱食度',text);self.assertNotIn('好感',text)
                self.assertEqual(self.window.shop_buttons[key][1].text(),'购买并投喂')
            else:
                self.assertIn('好感',text);self.assertNotIn('饱食度',text)
                self.assertEqual(self.window.shop_buttons[key][1].text(),'购买并赠送')
    def test_shop_subtabs_show_food_and_gifts_separately(self):
        self.window.show_section("shop", animate=False)
        self.window.shop_tabs.setCurrentIndex(1)
        self.assertFalse(self.window.shop_groups['food'].isVisible())
        self.assertTrue(self.window.shop_groups['gift'].isVisible())
        self.window.shop_tabs.setCurrentIndex(0)
        self.assertTrue(self.window.shop_groups['food'].isVisible())
        self.assertFalse(self.window.shop_groups['gift'].isVisible())
    def test_buy_give_and_backpack_buttons_share_live_model(self):
        self.window.show_section("shop", animate=False);self.window.shop_tabs.setCurrentIndex(1)
        self.window.shop_buttons['paper_star'][0].click()
        self.assertEqual(self.model.data.inventory['paper_star'],1)
        self.assertEqual(self.model.data.affection_exp,0)
        self.window.show_section("bag", animate=False)
        self.assertEqual(self.window.inventory_widgets['paper_star'][2].text(),'赠送')
        self.window.inventory_widgets['paper_star'][2].click()
        self.assertEqual(self.model.data.affection_exp,20)
        self.assertIn('赠礼 1 次',self.window.stats_label.text())
        self.window.shop_buttons['flower_bouquet'][1].click()
        self.assertEqual(self.model.data.affection_exp,100)
    def test_status_explains_satiation_and_new_harder_progress(self):
        self.assertIn('饱食度',self.window.hunger_bar.format())
        self.assertIn('/3000',self.window.level_label.text())
        self.assertIn('阿一古',self.window.milestone_widgets[6].text())

if __name__=='__main__':unittest.main(verbosity=2)
