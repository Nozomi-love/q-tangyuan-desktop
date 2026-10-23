"""Unified inventory and progression, retired custom UI, and shared live state."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import sys
import unittest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtTest import QTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from main import PetApplication
from models import PetData, PetModel
from save_manager import SaveManager, SkinManager
from dashboard import DashboardWindow

APP=QApplication.instance() or QApplication(['inventory-navigation'])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf8'))
ART=ROOT/'tests/artifacts'/datetime.now().strftime('inventory-navigation-%Y%m%d-%H%M%S-%f')
ART.mkdir(parents=True,exist_ok=False)

class InventoryNavigationTests(unittest.TestCase):
    def setUp(self):
        self.work=ART/self._testMethodName;self.work.mkdir()
        self.c=PetApplication(APP,save_path=self.work/'save_data.json',skins_root=self.work/'skins')
        self.c.window.timer.stop();self.c.tick_timer.stop();self.c.autosave_timer.stop()
        self.c.dashboard.room._animation_timer.stop()
        self.p=self.c.dashboard

    def tearDown(self):
        self.c.stop();self.p.deleteLater();self.c.window.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_inventory_contains_food_dress_furniture_and_tricks(self):
        p=self.p
        self.assertEqual([p.bag_tabs.tabText(i) for i in range(p.bag_tabs.count())],['投喂与赠礼','换装','装修','特技'])
        self.assertEqual([p.dress_tabs.tabText(i) for i in range(3)],['皮肤','挂件','称号'])
        for parent,child in ((p.bag_tabs.widget(0),p.inventory_widgets['sugar'][0]),
                             (p.bag_tabs.widget(1),p.dress_tabs),(p.bag_tabs.widget(2),p.furniture_buttons['air_conditioner']),
                             (p.bag_tabs.widget(3),p.trick_buttons['flip']),(p.dress_tabs.widget(2),p.title_combo)):
            self.assertTrue(parent.isAncestorOf(child))

    def test_achievements_and_levels_share_one_drawer(self):
        p=self.p;p.show_section('achievements',animate=False)
        self.assertEqual([p.progress_tabs.tabText(i) for i in range(2)],['成就图鉴','等级奖励'])
        self.assertTrue(p.progress_tabs.widget(0).isAncestorOf(p.achievement_summary))
        self.assertTrue(p.progress_tabs.widget(1).isAncestorOf(p.perk_summary))
        self.assertFalse(p.bag_tabs.isAncestorOf(p.perk_summary))
        p.progress_tabs.setCurrentIndex(1);APP.processEvents()
        self.assertTrue(p.room.isVisible());self.assertTrue(p.perk_summary.isVisible())

    def test_all_inventory_subpages_keep_room_visible_and_nav_correct(self):
        p=self.p;p.nav_buttons['bag'].click();p.drawer_animation.setCurrentTime(220)
        for index in range(p.bag_tabs.count()):
            p.bag_tabs.setCurrentIndex(index);APP.processEvents()
            self.assertTrue(p.room.isVisible());self.assertTrue(p.bag_tabs.widget(index).isVisible())
            self.assertEqual(p.current_section,'bag');self.assertTrue(p.nav_buttons['bag'].isChecked())
        for dest,bag,dress in [('dress',1,0),('furniture',2,None),('tricks',3,None),('titles',1,2)]:
            p.show_section(dest,animate=False);self.assertEqual(p.current_section,'bag')
            self.assertEqual(p.bag_tabs.currentIndex(),bag)
            if dress is not None:self.assertEqual(p.dress_tabs.currentIndex(),dress)

    def test_no_custom_import_copy_at_any_level_or_dev_context(self):
        p=self.p
        for level in (1,3,30):
            self.c.model.data.affection_level=level;self.c.model._publish(self.c.model.starving)
            p.set_phase4_context(self.c.skin_manager.list_skins(),dev_mode=True);p.refresh()
            for w in p.findChildren(QLabel)+p.findChildren(QPushButton):
                for word in ('自定义','导入PNG','导入ZIP','动作文件夹','皮肤模板','回收区','纯白背景','上单空调'):
                    self.assertNotIn(word,w.text(),(level,w.text()))
            self.assertNotIn('custom_import',{perk for row in self.c.model.catalog.milestones for perk in row['perks']})

    def test_historical_files_and_selection_survive_ui_context_refresh(self):
        image=self.work/'private.png';image.write_bytes((ROOT/'assets/skins/teams_s16/team_s16_al/idle.png').read_bytes())
        entry=self.c.skin_manager.import_image(image);directory=self.c.skin_manager.resolve(entry['id'])
        raw=(directory/'manifest.json').read_bytes()
        model=self.c.model;model.data.selected_skin_id=entry['id'];model.skin_config()['accessory_offset_y']=21
        before=model.snapshot();self.c._refresh_wardrobe()
        self.assertEqual(model.snapshot(),before)
        self.assertEqual((directory/'manifest.json').read_bytes(),raw)
        self.assertEqual(p_ids(self.p),{'default',*model.catalog.team_skins})
        self.assertFalse(self.c._select_skin(entry['id']))
        self.assertEqual(model.snapshot(),before)

    def test_feed_gift_and_dress_act_from_inventory(self):
        m=self.c.model;m.data.affection_level=6;m.data.coins=3000;m.set_hunger(0)
        self.assertTrue(m.buy_item('sugar'));self.assertTrue(m.buy_item('music_box'))
        self.p.show_section('bag',animate=False);self.p.refresh()
        self.p.inventory_widgets['sugar'][2].click();self.assertEqual(m.data.hunger,15)
        exp=m.data.affection_exp;self.p.inventory_widgets['music_box'][2].click()
        self.assertEqual(m.data.affection_exp,exp+240)
        self.p.show_section('dress',animate=False);self.p.dress_tabs.setCurrentIndex(1)
        self.p.head_combo.buttons[self.p.head_combo.findData('crown')].click()
        self.assertEqual(m.data.accessories['head'],'crown')
        self.p.dress_tabs.setCurrentIndex(2);self.p.title_combo.setCurrentText('阿一古')
        self.assertEqual(m.data.equipped_title,'阿一古')

    def test_air_conditioner_name_purchase_and_placement_persist(self):
        m=self.c.model;m.data.coins=1000
        self.assertEqual(m.catalog.furniture['air_conditioner']['name'],'空调')
        m.buy_furniture('air_conditioner');self.p.show_section('furniture',animate=False);self.p.refresh()
        tile=self.p.furniture_buttons['air_conditioner'];self.assertEqual(tile.text(),'空调');tile.click()
        self.assertEqual(m.data.equipped_furniture['wall'],'air_conditioner')
        self.c._save();data,_=SaveManager(self.work/'save_data.json').load_all()
        self.assertEqual(data.equipped_furniture['wall'],'air_conditioner')
        self.assertEqual(data.coins,640)

    def test_retired_privilege_is_not_announced_on_upgrade(self):
        m=PetModel(PetData(affection_level=2,affection_exp=999));names=[]
        m.perks_unlocked.connect(lambda items:names.extend(items));m.poke()
        self.assertEqual(m.data.affection_level,3)
        self.assertTrue(names);self.assertTrue(all('自定义' not in name for name in names))

    def test_reward_claim_keeps_single_settlement_and_opens_inventory_titles(self):
        m=self.c.model;m.data.affection_level=3;m._publish(m.starving)
        self.p.show_section('achievements',animate=False);self.p.refresh()
        aid='level_three';row=next(a for a in m.catalog.achievements if a['id']==aid)
        before=m.data.coins;claim=self.p.achievement_widgets[aid][2]
        claim.click();self.assertEqual(m.data.coins,before+row['coins']);claim.click()
        self.assertEqual(m.data.coins,before+row['coins'])
        self.p.achievement_widgets[aid][3].click();self.assertEqual(self.p.current_section,'bag')
        self.assertEqual(self.p.dress_tabs.currentIndex(),2)

def p_ids(panel):
    return {panel.skin_combo.itemData(i) for i in range(panel.skin_combo.count())}

if __name__=='__main__':unittest.main(verbosity=2)
