"""Phase 4 wardrobe UI contracts with real shared models and mocked file pickers."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import DashboardWindow
from models import PetData, PetModel

APP = QApplication.instance() or QApplication(["phase4-dashboard-tests"])
APP.setQuitOnLastWindowClosed(False)
APP.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))


class WardrobeDashboardTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel()
        self.window = DashboardWindow(self.model)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def level(self, value):
        self.model.data.affection_level = value
        self.model._publish(self.model.starving)
        self.window.refresh()

    def test_inventory_groups_and_retired_import_controls_absent(self):
        self.assertEqual(self.window.tabs.count(),4)
        self.assertTrue(self.window.tabs.tabBar().isHidden())
        self.assertEqual([self.window.bag_tabs.tabText(i) for i in range(4)],['投喂与赠礼','换装','装修','特技'])
        self.assertFalse(hasattr(self.window,'skin_disclaimer'))
        self.assertFalse(hasattr(self.window,'import_buttons'))

    def test_level_one_import_and_accessories_are_gated(self):
        self.assertFalse(self.window.face_check.isEnabled())
        self.assertFalse(self.window.effect_check.isEnabled())
        self.assertFalse(self.window.head_combo.model().item(1).isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in self.window.trick_buttons.values()))

    def test_level_two_flip_without_retired_sprout(self):
        self.level(2)
        self.assertEqual(self.window.head_combo.findData("sprout"), -1)
        self.assertFalse(self.window.head_combo.model().item(1).isEnabled())
        self.assertTrue(self.window.trick_buttons["flip"].isEnabled())
        self.assertFalse(self.window.trick_buttons["clone"].isEnabled())

    def test_level_three_unlocks_crown_and_import_free(self):
        self.level(3)
        self.assertTrue(self.window.head_combo.model().item(self.window.head_combo.findData("crown")).isEnabled())
        self.assertEqual(self.model.data.coins, 100)

    def test_no_early_import_purchase_entry(self):
        self.assertFalse(hasattr(self.window,'import_unlock_button'))
        self.assertFalse(hasattr(self.window,'import_unlock_requested'))
        self.window.refresh();self.assertEqual(self.model.data.coins,100)

    def test_low_balance_does_not_add_retired_unlock_entry(self):
        self.model.data.coins=49;self.window.refresh()
        self.assertFalse(hasattr(self.window,'import_unlock_button'))

    def test_accessory_selection_uses_model_signal_contract(self):
        self.level(6)
        self.window.accessory_requested.connect(self.model.equip_accessory)
        self.window.head_combo.setCurrentIndex(self.window.head_combo.findData("crown"))
        self.window.face_check.setChecked(True)
        self.window.effect_check.setChecked(True)
        self.assertEqual(self.model.data.accessories, {"head": "crown", "face": "sunglasses", "effect": "steam", "offset_y": 0})
        self.window.head_combo.setCurrentIndex(0)
        self.assertEqual(self.model.data.accessories["head"], "")
        self.window.face_check.setChecked(False)
        self.window.effect_check.setChecked(False)
        self.assertEqual(self.model.data.accessories["face"], "")
        self.assertEqual(self.model.data.accessories["effect"], "")

    def test_offset_slider_bounds_and_immediate_value_display(self):
        self.window.offset_requested.connect(self.model.set_accessory_offset)
        self.assertEqual((self.window.offset_slider.minimum(), self.window.offset_slider.maximum()), (-30, 30))
        self.window.offset_slider.setValue(-30)
        self.assertEqual(self.model.data.accessories["offset_y"], -30)
        self.assertEqual(self.window.offset_value.text(), "-30 px")
        self.window.offset_slider.setValue(100)
        self.assertEqual(self.model.data.accessories["offset_y"], 30)
        self.assertEqual(self.window.offset_value.text(), "+30 px")

    def test_refresh_never_emits_selection_or_offset_requests(self):
        signals = []
        self.window.accessory_requested.connect(lambda *args: signals.append(args))
        self.window.offset_requested.connect(lambda value: signals.append(value))
        self.window.skin_requested.connect(lambda value: signals.append(value))
        self.model.data.accessories["offset_y"] = 20
        self.model.data.accessories["head"] = "sprout"
        self.window.refresh()
        self.window.set_phase4_context([])
        self.assertEqual(signals, [])
        self.assertEqual(self.window.offset_slider.value(), 20)

    def test_builtin_metadata_is_plain_text_and_selection_emits_id(self):
        self.level(3);skin_id='team_s16_blg';name='<b>战队皮肤</b>'
        self.window.set_phase4_context([{'id':skin_id,'name':name,'author':'local'}])
        chosen=[];self.window.skin_requested.connect(chosen.append)
        self.window.skin_combo.setCurrentIndex(1)
        self.assertEqual(chosen,[skin_id]);self.assertEqual(self.window.skin_combo.currentText(),name)

    def test_wardrobe_filters_personal_ids_without_changing_saved_choice(self):
        skin_id='user_'+'b'*32;self.model.data.selected_skin_id=skin_id
        self.window.set_phase4_context([{'id':'default','name':'duplicate'},{'id':skin_id,'name':'local'}, {}, {'id':7}])
        self.assertEqual(self.window.skin_combo.count(),1)
        self.assertEqual(self.model.data.selected_skin_id,skin_id)
        self.assertIsNone(self.window.skin_combo.currentData())

    def test_image_picker_and_white_background_controls_removed(self):
        self.assertFalse(hasattr(self.window,'_pick_image'))
        self.assertFalse(hasattr(self.window,'white_background_check'))

    def test_pack_pickers_and_template_export_removed(self):
        for name in ('_pick_folder','_pick_zip','_export_template','export_template_button'):
            self.assertFalse(hasattr(self.window,name),name)

    def test_import_preview_and_recycle_controls_removed(self):
        for name in ('import_preview','preview_canvas','recycled_skins','rename_skin_button','delete_skin_button'):
            self.assertFalse(hasattr(self.window,name),name)

    def test_debug_override_is_only_visible_with_dev_context(self):
        outputs = []
        self.window.debug_unlock_requested.connect(outputs.append)
        self.assertTrue(self.window.debug_unlock_check.isHidden())
        self.window.set_phase4_context([], dev_mode=True)
        self.assertFalse(self.window.debug_unlock_check.isHidden())
        self.window.debug_unlock_check.setChecked(True)
        self.assertEqual(outputs, [True])
        self.window.set_phase4_context([], dev_mode=False)
        self.assertTrue(self.window.debug_unlock_check.isHidden())

    def test_debug_override_refresh_unlocks_controls_without_changing_level(self):
        self.window.set_phase4_context([], dev_mode=True)
        self.window.debug_unlock_requested.connect(lambda enabled: self.model.set_debug_unlock(enabled, authorized=True))
        self.window.debug_unlock_check.setChecked(True)
        self.window.refresh()
        self.assertEqual(self.model.data.affection_level, 1)
        self.assertTrue(all(self.window.trick_buttons[key].isEnabled() for key in ("flip", "clone", "ball")))
        self.assertFalse(self.window.trick_buttons["screen_roll"].isEnabled())
        self.assertNotIn("screen_roll", self.model.data.purchased_tricks)
        self.assertTrue(self.window.head_combo.model().item(3).isEnabled())
        self.window.debug_unlock_check.setChecked(False)
        self.window.refresh()
        self.assertFalse(self.window.trick_buttons["ball"].isEnabled())

    def test_tricks_dispatch_via_signal_and_show_busy_cooldown(self):
        self.level(6)
        outputs = []
        self.window.trick_requested.connect(outputs.append)
        self.window.trick_buttons["flip"].click()
        self.assertEqual(outputs, ["flip"])
        self.assertTrue(self.model.record_trick("flip"))
        self.window.refresh()
        self.assertFalse(self.window.trick_buttons["flip"].isEnabled())
        self.assertIn("秒", self.window.trick_buttons["flip"].text())
        # Other learned tricks may request replacement; this UI signal itself
        # must not end the old performance or charge/grant another action.
        self.assertTrue(self.window.trick_buttons["clone"].isEnabled())
        self.window.trick_buttons["clone"].click()
        self.assertEqual(outputs, ["flip", "clone"])
        self.assertEqual(self.model._active_trick_id, "flip")
        self.assertEqual(self.model.trick_cooldowns["clone"], 0)
        self.model.advance(5)
        self.window.refresh()
        self.assertTrue(self.window.trick_buttons["flip"].isEnabled())

    def test_starving_temporarily_disables_performances(self):
        self.level(6)
        self.model.set_hunger(0)
        self.window.refresh()
        self.assertTrue(all(not button.isEnabled() for button in self.window.trick_buttons.values()))
        self.assertIn("投喂", self.window.trick_status.text())

    def test_milestones_reflect_current_level_and_guardian_title(self):
        self.level(6)
        self.assertEqual(set(self.window.milestone_widgets), {1,2,3,4,5,6,8,10,15,20,25,30})
        self.assertTrue(all(widget.property("unlocked") == (level <= 6) for level, widget in self.window.milestone_widgets.items()))
        self.assertIn("阿一古", self.window.milestone_widgets[6].text())
        self.assertIn("阿一古", self.model.data.titles)

    def test_original_settings_refresh_is_signal_silent(self):
        outputs = []
        self.window.pin_requested.connect(outputs.append)
        self.window.dev_requested.connect(outputs.append)
        self.window.flat_requested.connect(outputs.append)
        self.window.set_settings(True, True, False)
        self.assertEqual(outputs, [])
        self.window.pin_check.setChecked(False)
        self.assertEqual(outputs, [False])

    def test_close_hides_without_deleting_or_quitting(self):
        self.window.show()
        APP.processEvents()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        self.assertFalse(self.window.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose))
        self.window.show()
        self.assertTrue(self.window.isVisible())


if __name__ == "__main__":
    unittest.main(verbosity=2)
