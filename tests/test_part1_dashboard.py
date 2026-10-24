"""Registered wardrobe slots and foreground lifecycle UI contracts."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_registry import AccessoryDefinition, BUILTIN_REGISTRY
from dashboard import DashboardWindow, IconChoice, IconTile
from models import Catalog, PetData, PetModel

APP = QApplication.instance() or QApplication(["part1-dashboard"])
APP.setQuitOnLastWindowClosed(False)


def extended_catalog() -> Catalog:
    """Explicit test-only registration: no fixture content reaches shipped JSON."""
    source = json.loads((ROOT / "config/catalog.json").read_text(encoding="utf-8"))
    rows = (
        AccessoryDefinition("fixture_visor", "face", "sunglasses", "accessory_fixture_visor", "测试面罩"),
        AccessoryDefinition("fixture_glow", "effect", "red_steam", "effect_fixture_glow", "测试微光"),
        AccessoryDefinition("fixture_shelved", "face", "sunglasses", "accessory_fixture_shelved", "旧藏面罩", False),
    )
    for row in rows:
        source["perks"][row.perk_id] = {
            "name": row.name, "level": 6, "kind": "accessory", "slot": row.slot, "item": row.id,
        }
    return Catalog(source, registry=BUILTIN_REGISTRY.with_accessories(*rows))


class RegisteredWardrobeUiTests(unittest.TestCase):
    def setUp(self):
        self.model = PetModel(PetData(affection_level=30, coins=0, muted=True), catalog=extended_catalog())
        self.window = DashboardWindow(self.model)
        self.window.accessory_requested.connect(self.model.equip_accessory)
        self.window.preview_timer.stop()
        self.window.room._animation_timer.stop()
        self.window.resize(1240, 800)
        self.window.show()
        self.window.refresh()
        APP.processEvents()

    def tearDown(self):
        self.window.stop()
        self.window.close()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def choose(self, slot, item_id):
        choice = self.window.accessory_choices[slot]
        index = choice.findData(item_id)
        self.assertGreaterEqual(index, 0, item_id)
        button = choice.buttons[index]
        self.assertTrue(button.isEnabled(), item_id)
        button.click()
        self.window.refresh()

    def test_each_slot_has_one_grid_and_an_empty_choice(self):
        self.window.show_section("dress", animate=False)
        self.window.dress_tabs.setCurrentIndex(1)
        for slot in ("head", "face", "back", "effect"):
            choice = self.window.accessory_choices[slot]
            self.assertIsInstance(choice, IconChoice)
            self.assertEqual(choice.itemData(0), "")
        self.assertIs(self.window.head_combo, self.window.head_choices)
        self.assertIs(self.window.aura_choices, self.window.effect_choices)
        for adapter in (self.window.face_check, self.window.effect_check):
            self.assertIsInstance(adapter, IconTile)
            self.assertTrue(adapter.isHidden())
        self.assertFalse(self.window.findChildren(QComboBox))
        self.assertFalse(self.window.findChildren(QCheckBox))

    def test_face_slot_selects_multiple_registered_ids_and_none(self):
        self.choose("head", "crown")
        for item_id in ("sunglasses", "fixture_visor", "sunglasses", ""):
            self.choose("face", item_id)
            self.assertEqual(self.model.data.accessories["face"], item_id)
            self.assertEqual(self.window.face_choices.currentData(), item_id)
            self.assertEqual(self.model.data.accessories["head"], "crown")

    def test_effect_slot_selects_multiple_registered_ids_and_none(self):
        for item_id in ("steam", "fixture_glow", "rainbow", ""):
            self.choose("effect", item_id)
            self.assertEqual(self.model.data.accessories["effect"], item_id)
            self.assertEqual(self.window.effect_choices.currentData(), item_id)

    def test_builtin_face_and_effect_reach_live_room_renderer(self):
        self.window.show_section("dress", animate=False)
        self.window.dress_tabs.setCurrentIndex(1)
        self.choose("face", "sunglasses")
        self.choose("effect", "rainbow")
        self.choose("head", "crown")
        renderer = self.window._renderer_provider()
        self.assertEqual(renderer.accessories["face"], "sunglasses")
        self.assertEqual(renderer.accessories["effect"], "rainbow")
        self.assertEqual(renderer.accessories["head"], "crown")
        self.assertTrue(self.window.room.isVisible())
        before = self.window.room.grab().toImage()
        self.choose("face", "")
        self.choose("effect", "")
        self.assertEqual(renderer.accessories["face"], "")
        self.assertEqual(renderer.accessories["effect"], "")
        after = self.window.room.grab().toImage()
        self.assertNotEqual(before, after)

    def test_permissions_disable_registered_face_and_effect_tiles(self):
        self.model.data.affection_level = 1
        self.window.refresh()
        for slot, item_id in (("face", "sunglasses"), ("face", "fixture_visor"),
                              ("effect", "steam"), ("effect", "fixture_glow")):
            choice = self.window.accessory_choices[slot]
            button = choice.buttons[choice.findData(item_id)]
            self.assertFalse(button.isEnabled())
            button.click()
            self.assertEqual(self.model.data.accessories.get(slot, ""), "")
        self.assertFalse(self.window.face_check.isEnabled())
        self.assertFalse(self.window.effect_check.isEnabled())

    def test_unregistered_and_unreleased_ids_never_create_entries(self):
        for choice in self.window.accessory_choices.values():
            self.assertEqual(choice.findData("unknown_future_hat"), -1)
            self.assertEqual(choice.findData("tactical_monocle"), -1)
        self.assertEqual(self.window.face_choices.findData("fixture_shelved"), -1)
        self.assertEqual(self.window.head_combo.findData("sprout"), -1)
        self.assertEqual(self.window.effect_choices.findData("fireflies"), -1)

    def test_legacy_worn_retired_item_remains_until_removed(self):
        self.model.data.accessories["head"] = "sprout"
        self.window.refresh()
        self.assertEqual(self.window.head_combo.currentData(), "sprout")
        self.assertEqual(self.model.data.accessories["head"], "sprout")
        self.choose("head", "")
        self.assertEqual(self.window.head_combo.findData("sprout"), -1)
        self.assertEqual(self.model.data.accessories["head"], "")

    def test_safe_unknown_saved_id_uses_empty_ui_without_mutating_save(self):
        self.model.data.accessories["face"] = "unknown_future_mask"
        saved = deepcopy(self.model.data.accessories)
        requests = []
        self.window.accessory_requested.connect(lambda *args: requests.append(args))
        self.window.refresh()
        self.assertEqual(self.window.face_choices.currentData(), "")
        self.assertEqual(self.model.effective_accessories()["face"], "")
        self.assertEqual(self.model.data.accessories, saved)
        self.assertEqual(requests, [])

    def test_old_boolean_face_switch_migrates_into_grid(self):
        for old, expected in ((True, "sunglasses"), (False, "")):
            raw = self.model.data.to_dict()
            raw["accessories"]["face"] = old
            self.model.replace_data(PetData.from_dict(raw))
            self.window.refresh()
            self.assertEqual(self.window.face_choices.currentData(), expected)
            self.assertEqual(self.window.face_check.isChecked(), bool(old))

    def test_refresh_is_silent_and_keeps_one_choice_per_slot(self):
        self.choose("face", "fixture_visor")
        self.choose("effect", "fixture_glow")
        requests = []
        self.window.accessory_requested.connect(lambda *args: requests.append(args))
        for _ in range(3):
            self.window.refresh()
        self.assertEqual(requests, [])
        for slot, choice in self.window.accessory_choices.items():
            self.assertEqual(sum(button.isChecked() for button in choice.buttons), 1, slot)

    def test_trick_grid_uses_only_registered_implemented_definitions(self):
        self.assertEqual(set(self.window.trick_buttons), set(self.model.catalog.trick_definitions))
        self.assertEqual(set(self.window.trick_buttons), {"flip", "clone", "ball", "screen_roll", "disco", "reverse_flash"})
        self.assertEqual(set(self.window.shop_trick_buttons), {"screen_roll", "reverse_flash"})
        self.assertNotIn("recall_taunt", self.window.trick_buttons)
        for item_id, button in self.window.trick_buttons.items():
            definition = self.model.catalog.trick_definitions[item_id]
            self.assertEqual(button.property("icon_id"), definition.icon)

    def test_hide_requests_foreground_cancel_but_drawer_navigation_does_not(self):
        requests = []
        self.window.foreground_cancel_requested.connect(requests.append)
        self.window.show_section("shop", animate=False)
        self.window.show_section("bag", animate=False)
        self.window.show_section("home", animate=False)
        self.assertEqual(requests, [])
        self.window.hide()
        self.assertEqual(requests, ["dashboard_hidden"])
        self.window.show()
        self.assertTrue(self.window.room.isVisible())


if __name__ == "__main__":
    unittest.main()
