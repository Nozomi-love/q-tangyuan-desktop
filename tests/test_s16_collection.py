"""S16 ownership, built-in assets, commerce, performance and save compatibility."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import subprocess
import sys
import unittest
import zipfile

from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import Catalog, PetData, PetModel, TEAM_SKIN_IDS
from save_manager import SaveManager, SkinManager, SkinImportError
from release_support import BackupManager
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea
from home_scene import IllustratedRoomCanvas, RoomLife
from illustrated_assets import IconAtlas

APP = QApplication.instance() or QApplication(['s16-tests'])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT/'tests/artifacts'/datetime.now().strftime('s16-%Y%m%d-%H%M%S-%f')
ART.mkdir(parents=True, exist_ok=False)
BUILTINS = ROOT/'assets/skins/teams_s16'


class CollectionTests(unittest.TestCase):
    def work(self):
        p=ART/(self._testMethodName+'-'+uuid4().hex); p.mkdir(); return p

    def test_roster_contains_four_teams_per_region(self):
        c=Catalog.load()
        self.assertEqual(set(c.team_skins),TEAM_SKIN_IDS)
        self.assertEqual({p['team'] for p in c.team_skins.values() if p['region']=='LPL'},{'AL','BLG','TES','iG'})
        self.assertEqual({p['team'] for p in c.team_skins.values() if p['region']=='LCK'},{'GEN','HLE','T1','DK'})

    def test_levels_grant_once_without_spending_or_extra_coins(self):
        c=Catalog.load()
        for sid,p in c.team_skins.items():
            with self.subTest(skin=sid):
                m=PetModel(PetData(affection_level=p['level']-1,coins=17))
                self.assertNotIn(sid,m.data.owned_team_skins)
                m.data.affection_level=p['level']; m._publish(m.starving)
                self.assertIn(sid,m.data.owned_team_skins)
                m._publish(m.starving)
                self.assertEqual(m.data.owned_team_skins.count(sid),1)
                self.assertEqual(m.data.coins,17)

    def test_buy_low_level_and_equip_without_import_privilege(self):
        m=PetModel(PetData(coins=2000)); sid='team_s16_tes'
        self.assertFalse(m.has_perk('custom_import'))
        self.assertTrue(m.buy_team_skin(sid)); self.assertTrue(m.select_skin(sid))
        self.assertEqual(m.data.coins,1100)
        self.assertTrue(m.buy_team_skin(sid)); self.assertEqual(m.data.coins,1100)
        self.assertFalse(m.select_skin('team_s16_t1'))

    def test_insufficient_and_invalid_purchase_are_noops(self):
        m=PetModel(PetData(coins=899)); before=m.snapshot()
        self.assertFalse(m.buy_team_skin('team_s16_tes'))
        self.assertFalse(m.buy_team_skin('../default'))
        self.assertEqual(m.snapshot(),before)

    def test_later_level_does_not_recharge_early_purchase(self):
        m=PetModel(PetData(coins=900)); m.buy_team_skin('team_s16_dk')
        m.data.affection_level=15; m._publish(m.starving)
        self.assertEqual(m.data.coins,0)
        self.assertEqual(m.data.owned_team_skins.count('team_s16_dk'),1)

    def test_developer_trial_does_not_permanently_grant_team_skins(self):
        m=PetModel(); m.set_debug_unlock(True,authorized=True)
        self.assertTrue(all(m.has_team_skin(sid) for sid in TEAM_SKIN_IDS))
        self.assertEqual(m.data.owned_team_skins,[])
        self.assertTrue(m.select_skin('team_s16_tes'))
        m.set_accessory_offset(17)
        m.set_debug_unlock(False,authorized=True)
        self.assertFalse(any(m.has_team_skin(sid) for sid in TEAM_SKIN_IDS))
        self.assertEqual(m.data.selected_skin_id,'default')
        self.assertEqual(m.effective_accessories()['offset_y'],0)

    def test_old_save_and_invalid_ownership(self):
        old=PetData.from_dict({'affection_level':1,'coins':123})
        self.assertEqual(old.owned_team_skins,[]); self.assertEqual(old.coins,123)
        for values in (['team_s16_fake'],['team_s16_tes']*2,'team_s16_tes'):
            with self.assertRaises(ValueError): PetData.from_dict({'owned_team_skins':values})

    def test_each_skin_keeps_its_own_size_and_offset(self):
        m=PetModel(PetData(affection_level=30))
        m.select_skin('team_s16_tes'); m.set_skin_scale(.7); m.set_accessory_offset(-21)
        m.select_skin('team_s16_ig'); m.set_skin_scale(1.4); m.set_accessory_offset(16)
        m.select_skin('team_s16_tes')
        self.assertEqual(m.skin_config(),{'scale_multiplier':.7,'accessory_offset_y':-21})
        restored=PetModel(PetData.from_dict(m.snapshot()))
        self.assertEqual(restored.data.selected_skin_id,'team_s16_tes')
        self.assertTrue(restored.has_team_skin('team_s16_ig'))

    def test_builtin_list_resolve_and_no_renaming_or_archive(self):
        manager=SkinManager(self.work()/'skins',builtin_root=BUILTINS)
        self.assertEqual({x['id'] for x in manager.list_skins()[1:]},TEAM_SKIN_IDS)
        self.assertEqual(manager.resolve('team_s16_tes'),BUILTINS/'team_s16_tes')
        with self.assertRaises(SkinImportError): manager.rename('team_s16_tes','私人名字')
        self.assertFalse(PetModel(PetData(affection_level=30)).archive_skin('team_s16_tes'))

    def test_all_assets_are_transparent_and_fallback_states_render(self):
        manager=SkinManager(self.work()/'skins',builtin_root=BUILTINS)
        for sid in TEAM_SKIN_IDS:
            manager.builtin_metadata(sid,validate=True)
            source=QImage(str(BUILTINS/sid/'idle.png'))
            self.assertTrue(source.hasAlphaChannel())
            self.assertEqual(source.pixelColor(0,0).alpha(),0)
            renderer=SkinRenderer(BUILTINS/sid)
            for state in PetState: self.assertEqual(renderer.source_state(state),PetState.IDLE)
            self.assertLessEqual(max(renderer.images[PetState.IDLE].size().toTuple()),512)
            self.assertAlmostEqual(renderer.anchor_rect(PetState.IDLE).bottom(),0)
            renderer.stop()

    def test_builtin_backup_has_no_bundled_copy_and_restores_cross_process(self):
        work=self.work(); saves=SaveManager(work/'save_data.json')
        m=PetModel(PetData(coins=2000));m.buy_team_skin('team_s16_tes');m.select_skin('team_s16_tes')
        m.set_skin_scale(1.3);m.set_accessory_offset(18)
        saves.load_all();saves.update_game(m.snapshot(),{'pinned':True,'x_ratio':.4,'y_ratio':.6})
        skins=SkinManager(work/'skins',builtin_root=BUILTINS)
        archive=BackupManager(saves,skins).export(work/'backup.zip')
        with zipfile.ZipFile(archive) as z:self.assertFalse(any(n.startswith('skins/') for n in z.namelist()))
        fresh=SaveManager(work/'fresh/save_data.json')
        data,window,_=BackupManager(fresh,SkinManager(work/'fresh/skins',builtin_root=BUILTINS)).restore(archive)
        self.assertEqual(data.selected_skin_id,'team_s16_tes');self.assertTrue(window['pinned'])
        code="import json,sys;from pathlib import Path;from save_manager import SaveManager,SkinManager;from models import PetModel;d,_=SaveManager(Path(sys.argv[1])).load_all();m=PetModel(d);s=SkinManager(Path(sys.argv[2]),Path(sys.argv[3]));print(json.dumps([m.can_use_skin(d.selected_skin_id),s.resolve(d.selected_skin_id).name,d.skin_configs[d.selected_skin_id]]))"
        result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(fresh.path),str(work/'fresh/skins'),str(BUILTINS)],cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout);self.assertEqual(values[:2],[True,'team_s16_tes'])
        self.assertEqual(values[2],{'scale_multiplier':1.3,'accessory_offset_y':18})

    def test_egg_and_barrel_only_feed_and_barrel_sets_buff(self):
        for key,hunger in (('egg',15),('gragas_barrel',65)):
            m=PetModel(PetData(coins=1000,hunger=0));self.assertTrue(m.buy_item(key,True))
            self.assertEqual(m.data.hunger,hunger);self.assertEqual(m.data.affection_exp,0)
            if key=='gragas_barrel':self.assertEqual(m.buff_view()['scale'],1.08)

    def test_tes_props_reject_before_charge_or_consumption(self):
        for key in ('tes_guitar','tes_microphone'):
            m=PetModel(PetData(coins=5000))
            before=m.snapshot();self.assertFalse(m.buy_item(key,True));self.assertEqual(m.snapshot(),before)
            self.assertTrue(m.buy_item(key));amount=m.data.inventory[key];coins=m.data.coins
            self.assertFalse(m.use_item(key));self.assertEqual(m.data.inventory[key],amount);self.assertEqual(m.data.coins,coins)
            self.assertTrue(m.buy_team_skin('team_s16_tes'));m.select_skin('team_s16_tes')
            events=[];m.presentation_requested.connect(events.append)
            self.assertTrue(m.use_item(key));self.assertEqual(m.data.inventory[key],0)
            self.assertEqual(events[-1]['effect'],key)

    def test_phoenix_purchase_equip_and_existing_slots_survive(self):
        m=PetModel(PetData(coins=2000));self.assertTrue(m.buy_accessory('phoenix_wings'))
        self.assertEqual(m.data.coins,800);self.assertTrue(m.buy_accessory('phoenix_wings'))
        self.assertEqual(m.data.coins,800);self.assertTrue(m.equip_accessory('back','phoenix_wings'))
        self.assertEqual(m.effective_accessories()['back'],'phoenix_wings')
        restored=PetModel(PetData.from_dict(m.snapshot()))
        self.assertEqual(restored.effective_accessories()['back'],'phoenix_wings')
        self.assertTrue(PetModel(PetData(affection_level=15)).has_perk('accessory_phoenix_wings'))

    def test_phoenix_extents_contain_rendered_pixels_at_maximum_scale(self):
        for sid in ('team_s16_tes','team_s16_t1'):
            renderer=SkinRenderer(BUILTINS/sid)
            for offset in (-30,30):
                engine=PetEngine(WorkArea(0,0,1200,900));engine.skin_scale=1.5
                engine.set_buff({'scale':1.2});engine.angle=18
                renderer.set_accessories({'head':'crown','back':'phoenix_wings','offset_y':offset})
                foot=QPointF(420,650);bounds=renderer.scene_bounds(engine,foot)
                image=QImage(840,820,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.transparent)
                p=QPainter(image);renderer.paint(p,engine,foot);p.end()
                pixels=bytes(image.constBits());stride=image.bytesPerLine()
                points=[(x,y) for y in range(image.height()) for x in range(image.width()) if pixels[y*stride+x*4+3]>20]
                self.assertTrue(points)
                for point in ((min(x for x,y in points),min(y for x,y in points)),
                              (max(x for x,y in points),max(y for x,y in points))):
                    self.assertTrue(bounds.adjusted(-1,-1,1,1).contains(QPointF(*point)),(sid,offset,point,bounds))
            renderer.stop()

    def test_ac_buy_place_switch_and_persist(self):
        m=PetModel(PetData(coins=1000));self.assertFalse(m.set_air_conditioner_on(False))
        self.assertTrue(m.buy_furniture('air_conditioner'));self.assertTrue(m.equip_furniture('wall','air_conditioner'))
        self.assertTrue(m.set_air_conditioner_on(False))
        restored=PetModel(PetData.from_dict(m.snapshot()))
        self.assertFalse(restored.data.air_conditioner_on)
        self.assertEqual(restored.data.equipped_furniture['wall'],'air_conditioner')

    def test_titles_and_exact_bubbles(self):
        m=PetModel(PetData(affection_level=20));self.assertIn('世一汤',m.data.titles);self.assertIn('金汤良圆',m.data.titles)
        self.assertTrue(m.equip_title('金汤良圆'))
        events=[];m.feedback.connect(lambda text,tone:events.append(text));m.select_skin('team_s16_tes')
        self.assertIn('我们会创造新的历史',events)
        self.assertEqual(RoomLife.daily_line(8,80,1),'太阳升起了，大脑空空')

    def test_new_icon_files_are_real_distinct_pngs(self):
        names=('air_conditioner','egg','gragas_barrel','phoenix_wings','tes_guitar','tes_microphone')
        hashes=[]
        for key in names:
            p=ROOT/'assets/item_icons'/(key+'.png');image=QImage(str(p))
            self.assertFalse(image.isNull());self.assertEqual(image.size().toTuple(),(80,80));self.assertTrue(image.hasAlphaChannel())
            hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(len(set(hashes)),6)

    def test_room_instrument_performances_and_ac_click(self):
        from dashboard import DashboardWindow
        m=PetModel(PetData(affection_level=30,coins=3000))
        panel=DashboardWindow(m);panel.resize(1240,760);panel.show();APP.processEvents()
        try:
            panel.room._animation_timer.stop();panel.preview_timer.stop()
            for key in ('tes_guitar','tes_microphone'):
                panel.room.performance=None
                panel.room.present_item({'item_id':key,'effect':key,'category':'gift','duration':7})
                self.assertEqual(panel.room.performance.item_id,key)
                panel.room.performance.age=2;panel.room.grab().save(str(self.work()/(key+'.png')))
            m.buy_furniture('air_conditioner');m.equip_furniture('wall','air_conditioner');APP.processEvents()
            before=m.data.air_conditioner_on
            QTest.mouseClick(panel.room,Qt.MouseButton.LeftButton,pos=panel.room.air_conditioner_rect().center().toPoint())
            self.assertNotEqual(m.data.air_conditioner_on,before)
        finally:
            panel.hide();panel.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_tes_instrument_is_visible_in_front_of_the_pet(self):
        from unittest.mock import patch
        engine=PetEngine(WorkArea(0,0,1200,900));renderer=SkinRenderer(BUILTINS/'team_s16_tes')
        room=IllustratedRoomCanvas(engine,lambda:renderer);room.resize(1100,620)
        room._animation_timer.stop();marker=QPixmap(80,80);marker.fill(QColor('#ff00ff'))
        try:
            for key in ('tes_guitar','tes_microphone'):
                room.performance=None;room.present_item({'item_id':key,'category':'gift','duration':7,'effect':key})
                room.performance.age=2
                with patch.object(room.atlas,'pixmap',return_value=marker):image=room.grab().toImage()
                count=sum(image.pixelColor(x,y).red()>210 and image.pixelColor(x,y).blue()>210 and image.pixelColor(x,y).green()<80
                          for y in range(250,620,2) for x in range(300,900,2))
                self.assertGreater(count,100,key)
        finally:
            room.deleteLater();renderer.stop();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_build_resource_allowlist_contains_formal_not_personal_skins(self):
        from tools.build_windows import resource_files
        files=resource_files(ROOT)
        for sid in TEAM_SKIN_IDS:self.assertIn('assets/skins/teams_s16/'+sid+'/idle.png',files)
        self.assertFalse(any('/user_' in p for p in files))

    def test_controller_shop_purchase_and_real_renderer_switch(self):
        from main import PetApplication
        c=PetApplication(APP,save_path=self.work()/'save_data.json',skins_root=self.work()/'skins',dev_mode=False)
        c.dashboard.hide();c.window.timer.stop();c.tick_timer.stop();c.autosave_timer.stop()
        try:
            c.model.data.coins=2000;c.model._publish(c.model.starving);c.dashboard.refresh()
            buy,equip,_=c.dashboard.team_skin_buttons['team_s16_tes']
            buy.click();self.assertIn('team_s16_tes',c.model.data.owned_team_skins);c.dashboard.refresh()
            equip.click();self.assertEqual(c.model.data.selected_skin_id,'team_s16_tes')
            self.assertEqual(c.window.renderer.skin_directory.name,'team_s16_tes')
            self.assertFalse(hasattr(c.dashboard,"rename_skin_button"))
            self.assertFalse(hasattr(c.dashboard,"delete_skin_button"))
            self.assertTrue(c.dashboard.shop_buttons['tes_guitar'][1].isEnabled())
        finally:
            c.stop();c.dashboard.deleteLater();c.window.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_controller_ends_trial_skin_and_keeps_purchased_skin(self):
        from main import PetApplication
        c=PetApplication(APP,save_path=self.work()/'save_data.json',skins_root=self.work()/'skins',dev_mode=True)
        c.window.timer.stop();c.tick_timer.stop();c.autosave_timer.stop()
        try:
            c._set_debug_unlock(True);self.assertTrue(c._select_skin('team_s16_t1'))
            c._set_debug_unlock(False)
            self.assertEqual(c.model.data.selected_skin_id,'default')
            self.assertEqual(c.window.renderer.skin_directory.name,'default')
            c.model.data.coins=2000;c.model.buy_team_skin('team_s16_tes')
            self.assertTrue(c._select_skin('team_s16_tes'))
            c._set_debug_unlock(True);c._set_debug_unlock(False)
            self.assertEqual(c.model.data.selected_skin_id,'team_s16_tes')
            self.assertEqual(c.window.renderer.skin_directory.name,'team_s16_tes')
        finally:
            c.stop();c.dashboard.deleteLater();c.window.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main(verbosity=2)
