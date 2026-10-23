"""Controller integration: import failures, UI synchronization and reward ordering."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QColor,QImage,QPainter
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from main import PetApplication
from pet_window import PetWindow
APP=QApplication.instance() or QApplication(['phase4-controller-tests'])
APP.setQuitOnLastWindowClosed(False)
ARTIFACTS=ROOT/'tests/artifacts'/datetime.now().strftime('phase4-controller-%Y%m%d-%H%M%S-%f')
ARTIFACTS.mkdir(parents=True,exist_ok=False)

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.work=ARTIFACTS/self._testMethodName
        self.work.mkdir()
        self.file=self.work/'save_data.json'
        self.file.write_text(json.dumps({'schema_version':3,'affection_level':3}),encoding='utf-8')
        self.controller=self.create()
    def create(self,accelerated=False):
        with patch('main.PetWindow',side_effect=lambda _:PetWindow(self.work/'no-default-art')):
            controller=PetApplication(APP,save_path=self.file,skins_root=self.work/'skins',accelerated=accelerated,dev_mode=False)
        controller.model.set_overlay_visible(True);controller.dashboard.hide()
        controller.window.timer.stop();controller.tick_timer.stop();controller.autosave_timer.stop()
        controller.window.set_pinned(True)
        return controller
    def tearDown(self):
        self.controller.stop()
        self.controller.dashboard.deleteLater();self.controller.window.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def png(self,transparent=False):
        file=self.work/('blank.png' if transparent else 'pet.png')
        image=QImage(80,80,QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        if not transparent:
            painter=QPainter(image);painter.setBrush(QColor('#e8a6bc'));painter.drawEllipse(5,5,70,70);painter.end()
        self.assertTrue(image.save(str(file),'PNG'))
        return file
    def test_builtin_selection_updates_wardrobe_renderer_model_and_save(self):
        c=self.controller;skin_id='team_s16_blg';self.assertTrue(c._select_skin(skin_id))
        self.assertEqual(c.dashboard.skin_combo.currentData(),skin_id)
        self.assertEqual(c.window.renderer.skin_directory.name,skin_id)
        c._save();self.assertEqual(json.loads(self.file.read_text(encoding='utf8'))['selected_skin_id'],skin_id)

    def test_import_controller_entrypoints_removed(self):
        c=self.controller
        for name in ('_import_image','_import_pack','_prepare_preview','_confirm_preview','_export_template','_rename_skin','_archive_skin'):
            self.assertFalse(hasattr(c,name),name)

    def test_unsupported_personal_selection_keeps_entire_model(self):
        c=self.controller;before=c.model.snapshot();directory=c.window.renderer.skin_directory
        self.assertFalse(c._select_skin('user_'+'f'*32))
        self.assertEqual(c.model.snapshot(),before)
        self.assertEqual(c.dashboard.skin_combo.currentData(),'default')
        self.assertEqual(c.window.renderer.skin_directory,directory)

    def test_acceleration_toggle_cannot_authorize_full_perks_debug(self):
        c=self.controller
        c.dev_action.setChecked(True)
        c.dashboard.debug_unlock_requested.emit(True)
        self.assertFalse(c.model.debug_unlock_all)
        self.assertTrue(c.dashboard.debug_unlock_check.isHidden())
        self.assertFalse(c.model.has_perk('trick_ball'))
    def test_engine_refused_performance_never_grants_exp_or_cooldown(self):
        c=self.controller
        c.flat_action.setChecked(True)
        before=c.model.data.affection_exp
        self.assertFalse(c._perform_trick('flip'))
        self.assertEqual(c.model.data.affection_exp,before)
        self.assertEqual(c.model.trick_cooldowns['flip'],0)
        c.flat_action.setChecked(False)
        self.assertTrue(c._perform_trick('flip'))
        self.assertEqual(c.model.data.affection_exp,before+5)
        self.assertFalse(c._perform_trick('flip'))
        self.assertEqual(c.model.data.affection_exp,before+5)
    def test_missing_skin_warning_survives_accelerated_startup(self):
        c=self.controller;c.stop()
        missing='user_'+'e'*32
        self.file.write_text(json.dumps({'schema_version':4,'affection_level':3,'selected_skin_id':missing}),encoding='utf-8')
        self.controller=self.create(accelerated=True)
        c=self.controller
        self.assertEqual(c.model.data.selected_skin_id,missing)
        c.dashboard.summon()
        self.assertIn('旧外观',c.dashboard.room._message)
        self.assertIsNone(c.dashboard.skin_combo.currentData())
    def test_empty_accessory_slot_does_not_resurrect_on_save(self):
        c=self.controller
        c.model.equip_accessory('head','crown');c.model.set_accessory_offset(17);c._save()
        c.model.equip_accessory('head','');c._save()
        data=json.loads(self.file.read_text(encoding='utf-8'))
        self.assertEqual(data['accessories']['head'],'')
        self.assertEqual(data['accessories']['offset_y'],17)

if __name__=='__main__':unittest.main(verbosity=2)
