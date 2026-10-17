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

    def test_five_tabs_and_wardrobe_disclaimer(self):
        self.assertEqual(self.window.tabs.count(), 6)
        self.assertTrue(self.window.tabs.tabBar().isHidden())
        self.assertEqual(self.window.tabs.tabText(3), "装扮")
        self.assertEqual(self.window.skin_disclaimer.text(), "免责声明：本软件为纯本地渲染工具，自定义导入的图片/GIF仅保存在您的电脑本地，不会上传至任何服务器。请确保所导入素材仅供个人学习欣赏或已取得合法授权。")
        self.assertEqual(self.window.skin_disclaimer.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.window.skin_disclaimer.wordWrap())

    def test_level_one_import_and_accessories_are_gated(self):
        self.assertTrue(all(not button.isEnabled() for button in self.window.import_buttons.values()))
        self.assertTrue(self.window.import_unlock_button.isEnabled())
        self.assertFalse(self.window.face_check.isEnabled())
        self.assertFalse(self.window.effect_check.isEnabled())
        self.assertFalse(self.window.head_combo.model().item(1).isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in self.window.trick_buttons.values()))

    def test_level_two_sprout_flip_only(self):
        self.level(2)
        self.assertTrue(self.window.head_combo.model().item(1).isEnabled())
        self.assertFalse(self.window.head_combo.model().item(2).isEnabled())
        self.assertTrue(self.window.trick_buttons["flip"].isEnabled())
        self.assertFalse(self.window.trick_buttons["clone"].isEnabled())
        self.assertFalse(self.window.import_buttons["image"].isEnabled())

    def test_level_three_unlocks_crown_and_import_free(self):
        self.level(3)
        self.assertTrue(self.window.head_combo.model().item(2).isEnabled())
        self.assertTrue(self.window.import_buttons["image"].isEnabled())
        self.assertTrue(self.window.import_unlock_button.isHidden())
        self.assertEqual(self.model.data.coins, 100)

    def test_early_unlock_button_spends_once_and_refreshes(self):
        self.window.import_unlock_requested.connect(self.model.unlock_custom_import)
        self.window.import_unlock_button.click()
        self.window.refresh()
        self.assertEqual(self.model.data.coins, 50)
        self.assertTrue(self.window.import_unlock_button.isHidden())
        self.assertTrue(all(button.isEnabled() for button in self.window.import_buttons.values()))
        self.model.unlock_custom_import()
        self.assertEqual(self.model.data.coins, 50)

    def test_insufficient_coins_disables_early_unlock(self):
        self.model.data.coins = 49
        self.window.refresh()
        self.assertFalse(self.window.import_unlock_button.isEnabled())
        self.assertFalse(self.window.import_buttons["zip"].isEnabled())

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

    def test_skins_metadata_is_plain_text_and_selection_emits_id(self):
        self.level(3)
        skin_id = "user_" + "a" * 32
        name = '<img src="https://example.invalid/a.png">'
        self.window.set_phase4_context([{"id": skin_id, "name": name, "author": "<b>local</b>"}])
        chosen = []
        self.window.skin_requested.connect(chosen.append)
        self.window.skin_combo.setCurrentIndex(1)
        self.assertEqual(chosen, [skin_id])
        self.assertEqual(self.window.skin_combo.currentText(), name)
        self.model.select_skin(skin_id)
        self.window.refresh()
        self.assertIn("<b>local</b>", self.window.skin_details.text())
        self.assertEqual(self.window.skin_details.textFormat(), Qt.TextFormat.PlainText)

    def test_wardrobe_deduplicates_default_and_keeps_current_missing_skin_visible(self):
        skin_id = "user_" + "b" * 32
        self.model.data.selected_skin_id = skin_id
        self.window.set_phase4_context([{"id": "default", "name": "duplicate"}, {}, {"id": 7}])
        self.assertEqual(self.window.skin_combo.count(), 2)
        self.assertEqual(self.window.skin_combo.currentData(), skin_id)
        self.assertIn("暂不可用", self.window.skin_combo.currentText())
        self.assertTrue(self.window.skin_combo.isEnabled())

    def test_image_picker_reports_filename_and_white_background_option(self):
        self.level(3)
        outputs = []
        self.window.import_image_requested.connect(lambda *args: outputs.append(args))
        with patch("dashboard.QFileDialog.getOpenFileName", return_value=("D:/pictures/friend.gif", "")):
            self.window.import_buttons["image"].click()
        self.window.white_background_check.setChecked(False)
        with patch("dashboard.QFileDialog.getOpenFileName", return_value=("D:/pictures/pet.png", "")):
            self.window.import_buttons["image"].click()
        self.assertEqual(outputs, [("D:/pictures/friend.gif", True), ("D:/pictures/pet.png", False)])

    def test_pack_pickers_and_template_export_send_paths_only(self):
        self.level(3)
        packs, exports = [], []
        self.window.import_pack_requested.connect(packs.append)
        self.window.export_template_requested.connect(exports.append)
        with patch("dashboard.QFileDialog.getExistingDirectory", return_value="D:/packs/local"):
            self.window.import_buttons["folder"].click()
        with patch("dashboard.QFileDialog.getOpenFileName", return_value=("D:/packs/safe.zip", "")):
            self.window.import_buttons["zip"].click()
        with patch("dashboard.QFileDialog.getExistingDirectory", return_value="D:/exports/template"):
            self.window.export_template_button.click()
        self.assertEqual(packs, ["D:/packs/local", "D:/packs/safe.zip"])
        self.assertEqual(exports, ["D:/exports/template"])

    def test_cancelled_file_pickers_emit_nothing(self):
        outputs = []
        self.window.import_image_requested.connect(lambda *args: outputs.append(args))
        self.window.import_pack_requested.connect(outputs.append)
        self.window.export_template_requested.connect(outputs.append)
        with patch("dashboard.QFileDialog.getOpenFileName", return_value=("", "")), patch("dashboard.QFileDialog.getExistingDirectory", return_value=""):
            self.window._pick_image()
            self.window._pick_folder()
            self.window._pick_zip()
            self.window._export_template()
        self.assertEqual(outputs, [])

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
        self.assertFalse(self.window.trick_buttons["clone"].isEnabled())
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
        self.assertEqual(set(self.window.milestone_widgets), set(range(1, 7)))
        self.assertTrue(all(widget.property("unlocked") for widget in self.window.milestone_widgets.values()))
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
