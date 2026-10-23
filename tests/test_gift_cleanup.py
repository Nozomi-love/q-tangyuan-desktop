"""All transient gift props clear; neutral HUD and built-in names stay concise."""
from pathlib import Path
from datetime import datetime
import hashlib,json,sys,unittest

from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication,QLabel

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dashboard import DashboardWindow
from models import PetData,PetModel
from save_manager import SkinManager,SaveManager
from home_scene import GiftPerformance

APP=QApplication.instance() or QApplication(['gift-cleanup-tests'])
APP.setQuitOnLastWindowClosed(False)
ART=ROOT/'tests/artifacts'/datetime.now().strftime('gift-cleanup-%Y%m%d-%H%M%S-%f')
ART.mkdir(parents=True,exist_ok=False)
GIFTS=('paper_star','flower_bouquet','music_box','spinning_top','tes_guitar','tes_microphone')

class GiftCleanupTests(unittest.TestCase):
    def setUp(self):
        self.m=PetModel(PetData(affection_level=15,coins=30000))
        self.m.select_skin('team_s16_tes')
        self.p=DashboardWindow(self.m);self.p.resize(1240,760);self.p.show();APP.processEvents()
        self.r=self.p.room;self.r._animation_timer.stop();self.p.preview_timer.stop()
        self.r.life.wait=1000

    def tearDown(self):
        self.p.stop();self.p.hide();self.p.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def prop_image(self):
        image=QImage(1400,850,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image);self.r._paint_gift(painter,1400,850);painter.end()
        return image

    def has_prop(self):
        image=self.prop_image()
        return any(bytes(image.constBits())[3::4])

    def start(self,key):
        self.r.interact(cancel_gift=True);self.r._gift_queue.clear()
        self.assertTrue(self.m.buy_item(key,True));self.r.advance_scene(1.5)
        self.assertIsNotNone(self.r.performance);self.assertTrue(self.has_prop(),key)

    def test_every_gift_draws_during_performance_and_clears_on_completion(self):
        for key in GIFTS:
            with self.subTest(gift=key):
                self.start(key);self.r.advance_scene(7)
                self.assertIsNone(self.r.performance);self.assertEqual(self.r._last_toy,'')
                self.assertFalse(self.has_prop())

    def test_every_gift_clears_immediately_when_interrupted(self):
        for key in GIFTS:
            with self.subTest(gift=key):
                self.start(key);self.r.interact(cancel_gift=True)
                self.assertIsNone(self.r.performance);self.assertFalse(self.has_prop())
                self.assertEqual(self.r._last_toy,'')

    def test_stale_marker_for_any_gift_never_draws(self):
        for key in GIFTS:
            with self.subTest(gift=key):
                self.r._last_toy=key;self.assertFalse(self.has_prop())
                self.r.interact(cancel_gift=True);self.assertEqual(self.r._last_toy,'')

    def test_expired_performance_cannot_render_while_waiting_for_tick(self):
        for key in GIFTS:
            self.r.performance=GiftPerformance(key,7);self.r.performance.age=7.01
            self.assertFalse(self.has_prop(),key)

    def test_food_interrupts_every_gift_without_a_floor_icon(self):
        for key in GIFTS:
            with self.subTest(gift=key):
                self.start(key);self.r.show_food('sugar',15)
                self.assertIsNone(self.r.performance);self.assertFalse(self.has_prop())
                self.r._food_age=100;self.r._food_queue.clear()

    def test_gift_queue_plays_once_then_clears_every_prop(self):
        gains=self.m.data.affection_exp
        self.assertTrue(self.m.buy_item('tes_guitar',True));self.assertTrue(self.m.buy_item('tes_microphone',True))
        self.assertEqual(len(self.r._gift_queue),1)
        self.r.advance_scene(7.1);self.assertEqual(self.r.performance.item_id,'tes_microphone')
        self.r.advance_scene(1);self.assertTrue(self.has_prop());self.r.advance_scene(7.1)
        self.assertIsNone(self.r.performance);self.assertEqual(self.r._gift_queue,[]);self.assertFalse(self.has_prop())
        self.assertEqual(self.m.data.affection_exp,gains+320)

    def test_stop_clears_active_queued_and_legacy_props(self):
        self.m.buy_item('tes_guitar',True);self.m.buy_item('tes_microphone',True)
        self.r._last_toy='music_box';self.r.stop()
        self.assertIsNone(self.r.performance);self.assertEqual(self.r._gift_queue,[])
        self.assertEqual(self.r._last_toy,'');self.assertFalse(self.has_prop())

    def test_neutral_hud_is_empty_but_real_buff_keeps_countdown(self):
        self.p.refresh();self.assertTrue(self.p.hud_buff.isHidden());self.assertEqual(self.p.hud_buff.text(),'')
        self.assertFalse(any(w.text()=='原味汤圆' for w in self.p.findChildren(QLabel)))
        self.m.buy_item('sesame',True);self.p.refresh()
        self.assertTrue(self.p.hud_buff.isVisible());self.assertIn('芝麻胖团',self.p.hud_buff.text())
        self.m.advance(61);self.p.refresh();self.assertTrue(self.p.hud_buff.isHidden())
        self.assertEqual(self.p.hud_buff.text(),'')

    def test_names_match_catalog_manifest_shop_and_wardrobe(self):
        manager=SkinManager(ART/'name-test-skins',builtin_root=ROOT/'assets/skins/teams_s16')
        self.p.set_phase4_context(manager.list_skins())
        for sid,row in self.m.catalog.team_skins.items():
            with self.subTest(skin=sid):
                self.assertNotIn(' · ',row['name']);self.assertFalse(row['name'].startswith(row['team']))
                self.assertEqual(manager.builtin_metadata(sid)['name'],row['name'])
                self.assertEqual(self.p.skin_combo.itemText(self.p.skin_combo.findData(sid)),row['name'])
                self.assertEqual(self.m.catalog.perks['skin_s16_'+sid.removeprefix('team_s16_')]['name'],row['name'])
                buy,_,_=self.p.team_skin_buttons[sid]
                self.assertEqual(buy.parentWidget().findChild(QLabel,'itemName').text(),row['name'])

    def test_shortened_names_keep_asset_bytes_ownership_and_saved_ids(self):
        index=json.loads((ROOT/'assets/skins/teams_s16/asset_index.json').read_text(encoding='utf8'))
        for row in index:
            png=ROOT/'assets/skins/teams_s16'/row['id']/'idle.png'
            self.assertEqual(hashlib.sha256(png.read_bytes()).hexdigest(),row['sha256'])
            self.assertEqual(row['name'],self.m.catalog.team_skins[row['id']]['name'])
        self.m.set_skin_scale(1.3);self.m.set_accessory_offset(15)
        path=ART/'name-roundtrip.json';save=SaveManager(path);save.load_all();save.update_game(self.m.snapshot())
        data,_=SaveManager(path).load_all()
        self.assertEqual(data.selected_skin_id,'team_s16_tes');self.assertEqual(data.owned_team_skins,self.m.data.owned_team_skins)
        self.assertEqual(data.skin_configs['team_s16_tes'],{'scale_multiplier':1.3,'accessory_offset_y':15})

if __name__=='__main__':unittest.main(verbosity=2)
