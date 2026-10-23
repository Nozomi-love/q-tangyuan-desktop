"""V2 release contracts; all saves/media stay in retained isolated artifacts."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor,QImage,QPainter
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from models import PetData,PetModel,Catalog
from save_manager import SaveManager,SkinManager,SkinImportError,SaveDataError
from release_support import BackupManager, SingleInstance,APP_VERSION
from pet_engine import PetEngine,SkinRenderer,WorkArea,PetState
from test_phase4_skins import gif_bytes

APP=QApplication.instance() or QApplication(["v2-final-tests"])
APP.setQuitOnLastWindowClosed(False)
ART=ROOT/"tests/artifacts"/("v2-final-tests-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
ART.mkdir(parents=True,exist_ok=False)

class FinalDataTests(unittest.TestCase):
    def setUp(self):
        self.work=ART/(self._testMethodName+"-"+uuid4().hex); self.work.mkdir()
        self.skins=SkinManager(self.work/"skins")
        self.png=self.work/"penguin.png"
        image=QImage(64,80,QImage.Format.Format_ARGB32); image.fill(QColor("#4b6c8d")); image.save(str(self.png))
        self.gif=self.work/"dance.gif"; self.gif.write_bytes(gif_bytes())

    def test_legacy_offset_migrates_only_to_selected_skin(self):
        sid="user_"+"a"*32
        data=PetData.from_dict({"selected_skin_id":sid,"accessories":{"offset_y":23}})
        model=PetModel(data); model.select_skin("default")
        self.assertEqual(model.skin_config()["accessory_offset_y"],0)
        model.data.custom_import_unlocked=True; model.select_skin(sid)
        self.assertEqual(model.skin_config()["accessory_offset_y"],23)

    def test_each_skin_recalls_independent_scale_and_offset(self):
        m=PetModel(PetData(custom_import_unlocked=True)); sid="user_"+"b"*32
        m.set_skin_scale(.6); m.set_accessory_offset(-30); m.select_skin(sid)
        m.set_skin_scale(1.5); m.set_accessory_offset(30); m.select_skin("default")
        self.assertEqual(m.skin_config(),{"scale_multiplier":.6,"accessory_offset_y":-30})
        m.select_skin(sid); self.assertEqual(m.data.accessories["offset_y"],30)
        self.assertEqual(PetData.from_dict(m.snapshot()).skin_configs,m.data.skin_configs)

    def test_invalid_scales_and_offsets_rejected(self):
        for value in (.59,1.51,float("nan"),True,"1.2"):
            with self.subTest(value=value): self.assertFalse(PetModel().set_skin_scale(value))
        for value in (-31,31,True,1.5):
            with self.subTest(offset=value): self.assertFalse(PetModel().set_accessory_offset(value))
        for raw in ({"default":{"scale_multiplier":2}}, {"../bad":{}}, {"default":{"accessory_offset_y":31}}):
            with self.subTest(raw=raw),self.assertRaises(ValueError): PetData.from_dict({"skin_configs":raw})

    def test_milestone_boundary_rewards_are_owned_once(self):
        catalog=Catalog.load()
        for level in (8,10,15,20,25,30):
            with self.subTest(level=level):
                m=PetModel(PetData(affection_level=level-1))
                row=next(r for r in catalog.milestones if r["level"]==level)
                for key in row["perks"]: self.assertFalse(m.has_perk(key))
                m.data.affection_level=level; m._publish(False)
                for key in row["perks"]:
                    self.assertTrue(m.has_perk(key)); perk=catalog.perks[key]
                    if perk["kind"]=="furniture":
                        self.assertIn(perk["item"],m.data.owned_furniture)
                        self.assertTrue(m.equip_furniture(perk["slot"],perk["item"]))
                    if perk["kind"]=="title": self.assertIn(perk["title"],m.data.titles)
                before=m.snapshot(); m._publish(False); self.assertEqual(m.snapshot(),before)

    def test_reward_furniture_cannot_be_bought_for_zero(self):
        m=PetModel()
        for key in ("sunny_chime","camp_room","sesame_friend","royal_rug"):
            self.assertFalse(m.buy_furniture(key)); self.assertNotIn(key,m.data.owned_furniture)

    def test_next_target_counts_all_intervening_levels(self):
        m=PetModel(PetData(affection_level=6,affection_exp=100))
        target=m.next_milestone()
        self.assertEqual(target["level"],8)
        self.assertEqual(target["remaining_exp"],6400)
        self.assertIn("听风时光",target["text"])
        m.data.affection_level=30; m.data.affection_exp=0
        self.assertEqual(m.next_milestone()["remaining_exp"],0)
        self.assertIn("满级",m.next_milestone()["text"])

    def test_original_sixth_level_title_is_retained(self):
        self.assertIn("阿一古",PetModel(PetData(affection_level=30)).data.titles)
        self.assertIn("汤圆守护仙",PetModel(PetData(affection_level=30)).data.titles)

    def test_archive_is_reversible_and_keeps_bytes(self):
        skin=self.skins.import_image(self.png); sid=skin["id"]
        original=(self.skins.root/sid/"manifest.json").read_bytes()
        m=PetModel(PetData(custom_import_unlocked=True)); m.select_skin(sid); m.set_skin_scale(1.27)
        self.assertTrue(m.archive_skin(sid)); self.assertEqual(m.data.selected_skin_id,"default")
        self.assertFalse(m.select_skin(sid)); self.assertTrue(m.archive_skin(sid,False)); self.assertTrue(m.select_skin(sid))
        self.assertEqual(m.skin_config()["scale_multiplier"],1.27)
        self.assertEqual((self.skins.root/sid/"manifest.json").read_bytes(),original)
        self.assertFalse(m.archive_skin("default"))

    def test_preview_does_not_enter_wardrobe_and_commit_uses_snapshot(self):
        preview=self.skins.prepare_preview(self.png)
        self.assertEqual(len(self.skins.list_skins()),1)
        self.png.write_bytes(b"original was changed after preview")
        accepted=self.skins.commit_preview(preview["id"])
        self.assertEqual(len(self.skins.list_skins()),2)
        self.assertTrue((self.skins.resolve(accepted["id"])/accepted["states"]["idle"]).is_file())
        with self.assertRaises(SkinImportError): self.skins.commit_preview(preview["id"])

    def test_preview_cancel_leaves_no_selected_skin(self):
        entry=self.skins.prepare_preview(self.gif); self.skins.cancel_preview(entry["id"])
        with self.assertRaises(SkinImportError): self.skins.commit_preview(entry["id"])
        self.assertEqual(len(self.skins.list_skins()),1)

    def test_gif_folder_and_zip_preview(self):
        folder=self.work/"package"; folder.mkdir()
        (folder/"dance.gif").write_bytes(self.gif.read_bytes())
        (folder/"manifest.json").write_text(json.dumps({"name":"企鹅","states":{"idle":"dance.gif"}}),encoding="utf-8")
        archive=self.work/"skin.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.write(folder/"manifest.json","manifest.json");z.write(self.gif,"dance.gif")
        for source,pack in ((self.gif,False),(folder,True),(archive,True)):
            with self.subTest(source=source):
                entry=self.skins.prepare_preview(source,pack=pack)
                renderer=SkinRenderer(Path(entry["directory"]))
                self.assertTrue(renderer.movies)
                renderer.stop()

    def test_rename_is_literal_and_original_manifest_is_backed_up(self):
        skin=self.skins.import_image(self.png); sid=skin["id"]
        old=(self.skins.root/sid/"manifest.json").read_bytes()
        entry=self.skins.rename(sid,"我的企鹅 <不解析>")
        self.assertEqual(entry["name"],"我的企鹅 <不解析>")
        backups=list((self.skins.root/sid).glob("manifest.json.bak.*"))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)
        with self.assertRaises(SkinImportError):self.skins.rename(sid,"")

    def backup_fixture(self):
        skin=self.skins.import_image(self.gif); sid=skin["id"]
        m=PetModel(PetData(affection_level=30,coins=1234,selected_skin_id=sid))
        m.set_skin_scale(1.4);m.set_accessory_offset(-19);m.equip_accessory("head","orange")
        m.equip_furniture("window","sunny_chime");m.equip_furniture("companion","sesame_friend")
        saves=SaveManager(self.work/"data/save_data.json");saves.load_all();saves.update_game(m.snapshot(),{"pinned":True,"x_ratio":.4,"y_ratio":.6})
        manager=BackupManager(saves,self.skins); archive=manager.export(self.work/"backup.zip")
        return manager,archive,sid,m

    def test_backup_restore_replaces_inventory_and_recovers_room(self):
        manager,archive,sid,m=self.backup_fixture()
        changed=m.snapshot();changed["coins"]=1;changed["inventory"]={"sugar":99};manager.saves.update_game(changed)
        data,window,rollback=manager.restore(archive)
        self.assertEqual(data.coins,1234);self.assertEqual(data.inventory,{})
        self.assertEqual(data.skin_configs[sid]["accessory_offset_y"],-19)
        self.assertEqual(data.equipped_furniture["companion"],"sesame_friend")
        self.assertTrue(window["pinned"]);self.assertTrue(rollback.is_file())
        actual,_=manager.saves.load_all();self.assertEqual(actual.to_dict(),data.to_dict())
        old=json.loads(zipfile.ZipFile(rollback).read("save_data.json"));self.assertEqual(old["coins"],1)

    def test_restore_to_new_directory_and_cross_process_memory(self):
        manager,archive,sid,m=self.backup_fixture()
        fresh=BackupManager(SaveManager(self.work/"new/save_data.json"),SkinManager(self.work/"new/skins"))
        data,window,rollback=fresh.restore(archive)
        self.assertIsNone(rollback)
        code="import sys,json;from pathlib import Path;from save_manager import SaveManager,SkinManager;d,_=SaveManager(Path(sys.argv[1])).load_all();s=SkinManager(Path(sys.argv[2]));print(json.dumps([d.skin_configs,d.selected_skin_id,s.resolve(d.selected_skin_id).name,d.equipped_furniture]))"
        result=subprocess.run([sys.executable,"-B","-X","utf8","-c",code,str(fresh.saves.path),str(fresh.skins.root)],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        values=json.loads(result.stdout);self.assertEqual(values[0][sid]["scale_multiplier"],1.4);self.assertEqual(values[1:3],[sid,sid])

    def test_restore_collision_remaps_without_overwriting_existing_skin(self):
        manager,archive,sid,m=self.backup_fixture()
        self.skins.rename(sid,"保留这个本地名字")
        before=(self.skins.root/sid/"manifest.json").read_bytes()
        data,_,_=manager.restore(archive)
        self.assertNotEqual(data.selected_skin_id,sid)
        self.assertIn(data.selected_skin_id,data.skin_configs)
        self.assertEqual((self.skins.root/sid/"manifest.json").read_bytes(),before)

    def test_bad_zip_paths_symlinks_duplicates_and_unknown_files_rejected(self):
        manager,archive,sid,m=self.backup_fixture();before=manager.saves.path.read_bytes()
        for kind,name in (("path","../escape.txt"),("absolute","C:/bad"),("link","skins/"+sid+"/link.png"),("extra","extra.py"),("duplicate","save_data.json")):
            with self.subTest(kind=kind):
                bad=self.work/(kind+".zip")
                with zipfile.ZipFile(archive) as src,zipfile.ZipFile(bad,"w") as dst:
                    for item in src.infolist():dst.writestr(item,src.read(item))
                    info=zipfile.ZipInfo(name)
                    if kind=="link": info.create_system=3;info.external_attr=(0o120777<<16)
                    dst.writestr(info,b"bad")
                with self.assertRaises((SaveDataError,SkinImportError)):manager.restore(bad)
                self.assertEqual(manager.saves.path.read_bytes(),before)

    def test_hash_tampering_rejected_without_save_changes(self):
        manager,archive,sid,m=self.backup_fixture();before=manager.saves.path.read_bytes()
        bad=self.work/"tampered.zip"
        with zipfile.ZipFile(archive) as src,zipfile.ZipFile(bad,"w") as dst:
            for item in src.infolist():dst.writestr(item,b"{}" if item.filename=="save_data.json" else src.read(item))
        with self.assertRaises(SaveDataError):manager.restore(bad)
        self.assertEqual(manager.saves.path.read_bytes(),before)

    def test_stale_writer_restore_and_export_are_rejected(self):
        manager,archive,sid,m=self.backup_fixture()
        external=SaveManager(manager.saves.path);external.load_all();state=m.snapshot();state["coins"]=777;external.update_game(state)
        before=manager.saves.path.read_bytes()
        with self.assertRaises(SaveDataError):manager.restore(archive)
        with self.assertRaises(SaveDataError):manager.export(self.work/"stale.zip")
        self.assertEqual(manager.saves.path.read_bytes(),before)

    def test_disco_cooldown_duration_and_fixed_position(self):
        m=PetModel(PetData(affection_level=10));self.assertTrue(m.record_trick("disco"));self.assertFalse(m.record_trick("disco"))
        engine=PetEngine(WorkArea(0,0,1280,900));engine.set_pinned(True);position=(engine.x,engine.y)
        self.assertTrue(engine.perform_trick("disco"));angles=[]
        for i in range(90):engine.advance(1/60);angles.append(engine.pose.angle)
        self.assertGreater(max(angles)-min(angles),20);self.assertEqual((engine.x,engine.y),position)
        engine.advance(6);m.advance(6);self.assertEqual(engine.active_trick,"");self.assertTrue(m.can_perform_trick("disco"))

    def test_scaled_png_gif_accessories_effects_render_and_bounds_contain_ink(self):
        for source in (self.png,self.gif):
            skin=self.skins.import_image(source);renderer=SkinRenderer(self.skins.resolve(skin["id"]))
            for effect in ("fireflies","rainbow"):
                renderer.set_accessories({"head":"orange","effect":effect,"offset_y":-30})
                e=PetEngine(WorkArea(0,0,1280,900));e.skin_scale=1.5;e.set_buff({"scale":1.2,"remaining_seconds":60})
                bounds=renderer.scene_bounds(e,QPointF(400,500))
                image=QImage(800,640,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
                painter=QPainter(image);renderer.paint(painter,e,QPointF(400,500));painter.end()
                for y in range(image.height()):
                    for x in range(image.width()):
                        if image.pixelColor(x,y).alpha()>20:
                            self.assertTrue(bounds.adjusted(-1,-1,1,1).contains(QPointF(x,y)),(source,effect,x,y,bounds))
            renderer.stop()

class ReleaseUiTests(unittest.TestCase):
    def setUp(self):
        from main import PetApplication
        self.work=ART/(self._testMethodName+"-"+uuid4().hex);self.work.mkdir()
        self.controller=PetApplication(APP,save_path=self.work/"save_data.json",skins_root=self.work/"skins",dev_mode=False)
        self.controller.tick_timer.stop();self.controller.window.timer.stop()
    def tearDown(self):
        c=self.controller;c.stop();c.dashboard.deleteLater();c.window.deleteLater();c.tray.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_release_hides_debug_menu_and_settings(self):
        c=self.controller
        self.assertFalse(c.debug_menu.menuAction().isVisible())
        self.assertTrue(all(w.isHidden() for w in c.dashboard.release_debug_widgets))
        c.dashboard.set_phase4_context(c.skin_manager.list_skins(),True)
        self.assertTrue(all(not w.isHidden() for w in c.dashboard.release_debug_widgets))
    def test_builtin_thumbnail_comes_from_actual_idle_asset(self):
        c=self.controller;c.model.data.affection_level=2;c.model._publish(c.model.starving)
        self.assertTrue(c._select_skin('team_s16_al'))
        card=c.dashboard.skin_combo.buttons[c.dashboard.skin_combo.findData('team_s16_al')]
        thumb=card.icon().pixmap(72,72).toImage()
        from PySide6.QtGui import QIcon
        expected=QIcon(c.window.renderer.pixmaps[PetState.IDLE]).pixmap(72,72).toImage()
        self.assertEqual(thumb,expected);self.assertFalse(hasattr(c.dashboard,'import_preview'))

    def test_removed_preview_has_no_timers_or_controls_to_leak(self):
        c=self.controller
        self.assertFalse(hasattr(c.dashboard,'preview_scroll_timer'))
        self.assertFalse(hasattr(c.dashboard,'preview_canvas'));c.dashboard.stop()

    def test_changing_skin_size_interrupts_old_trick_envelope(self):
        c=self.controller;c.dev_mode=True;c._dev_level(10)
        c.window.engine.grounded=True
        self.assertTrue(c._perform_trick("flip"));self.assertTrue(c.model.set_skin_scale(1.5))
        self.assertEqual(c.window.engine.active_trick,"")
        self.assertEqual(c.window.engine.skin_scale,1.5)

    def test_wake_shows_both_views(self):
        c=self.controller;c.dashboard.hide();c.model.set_overlay_visible(False)
        c.wake();self.assertTrue(c.dashboard.isVisible());self.assertTrue(c.window.isVisible());self.assertTrue(c.model.data.overlay_visible)
    def test_chime_click_emits_sound_and_companion_renders(self):
        c=self.controller;c._dev_level(30);self.assertEqual(c.model.data.affection_level,1)
        c.dev_mode=True;c._dev_level(30);c.model.equip_furniture("window","sunny_chime");c.model.equip_furniture("companion","sesame_friend")
        self.assertGreater(c.window.engine.fireworks_until,c.window.engine.elapsed)
        from PySide6.QtTest import QTest
        sounds=[];c.dashboard.room.sound_requested.connect(sounds.append)
        QTest.mouseClick(c.dashboard.room,Qt.MouseButton.LeftButton,pos=c.dashboard.room.chime_rect().center().toPoint())
        self.assertIn("chime",sounds)
        self.assertIn("满级",c.dashboard.hud_exp_bar.toolTip())
    def test_backup_restore_refreshes_controller_immediately(self):
        c=self.controller;file=self.work/"backup.zip";c._export_backup(str(file));self.assertTrue(file.is_file())
        c.model.rename_pet("新的名字");c._save();c._restore_backup(str(file))
        self.assertEqual(c.model.data.name,"白汤圆");self.assertEqual(c.dashboard.hud_name.text(),"白汤圆")
        self.assertIn("恢复完成",c.dashboard.backup_status.text())

class ReleasePathTests(unittest.TestCase):
    def test_frozen_updates_keep_one_data_directory(self):
        from release_support import player_paths
        stable=ART/"stable-profile"
        with patch("release_support.QStandardPaths.writableLocation",return_value=str(stable)):
            a=player_paths(ART/"version1",frozen=True)
            b=player_paths(ART/"version2",frozen=True)
        self.assertEqual(a,b);self.assertEqual(a,(stable/"save_data.json",stable/"skins"))
        self.assertFalse(stable.exists())

    def test_source_and_isolated_profiles_keep_legacy_project_path(self):
        from release_support import player_paths
        for frozen,isolated in ((False,False),(True,True)):
            self.assertEqual(player_paths(ART/"project",frozen=frozen,isolated=isolated),(ART/"project/data/save_data.json",None))

class InstanceTests(unittest.TestCase):
    def test_profile_identity_is_case_insensitive_and_isolated(self):
        a=SingleInstance(ART/"Alpha/save.json");b=SingleInstance(ART/"alpha/save.json");c=SingleInstance(ART/"Beta/save.json")
        self.assertEqual(a.name,b.name);self.assertNotEqual(a.name,c.name)
    def test_two_real_processes_wake_only_one_owner(self):
        result=subprocess.run([sys.executable,"-B","-X","utf8",str(ROOT/"tests/verify_v2_instance.py"),str(ART/("ipc-"+uuid4().hex))],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn("IPC_OK",result.stdout)

if __name__=="__main__":unittest.main()
