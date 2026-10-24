"""Part 1 registries, safe compatibility, bounded local summaries and settlement."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_registry import (AccessoryDefinition, BUILTIN_REGISTRY, BUILTIN_TRICKS,
                              ContentRegistry, TrickDefinition)
from models import Catalog, PetData, PetModel
from save_manager import SaveDataError, SaveManager


def source():
    return json.loads((ROOT / "config" / "catalog.json").read_text(encoding="utf-8-sig"))


class RegistryTests(unittest.TestCase):
    def test_exact_current_content_not_future_designs(self):
        catalog = Catalog.load()
        self.assertEqual(set(catalog.trick_definitions), {"flip", "clone", "ball", "screen_roll", "disco", "reverse_flash"})
        self.assertEqual(set(catalog.items), set(catalog.registry.item_ids))
        self.assertEqual(len(catalog.items), 28)
        self.assertEqual(dict(catalog.registry.furniture_slots), {key: value["slot"] for key, value in catalog.furniture.items()})
        for future in ("recall_taunt", "prematch_flag", "tactical_monocle"):
            self.assertNotIn(future, catalog.content_ids)

    def test_definitions_and_mappings_cannot_be_mutated_in_place(self):
        with self.assertRaises(TypeError):
            BUILTIN_TRICKS["new"] = BUILTIN_TRICKS["flip"]
        with self.assertRaises((AttributeError, TypeError)):
            BUILTIN_TRICKS["flip"].duration = 100

    def test_duplicate_ids_and_shared_perk_references_rejected(self):
        row = BUILTIN_TRICKS["flip"]
        with self.assertRaises(ValueError):
            ContentRegistry(tricks=(row, row))
        with self.assertRaises(ValueError):
            BUILTIN_REGISTRY.with_accessories(AccessoryDefinition("second_face", "face", "sunglasses", "accessory_crown"))
        with self.assertRaises(ValueError):
            BUILTIN_REGISTRY.with_tricks(TrickDefinition("second_flip", "测试", "flip", 1, 5, "trick_flip"))

    def test_registry_rejects_paths_bad_slots_and_nonfinite_timing(self):
        for identifier in ("../escape", "C:/x", "a/b", "a\\b", "", True):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                AccessoryDefinition(identifier, "face", "sunglasses", "accessory_test")
        with self.assertRaises(ValueError):
            AccessoryDefinition("test", "feet", "sunglasses", "accessory_test")
        for duration in (0, -1, float("nan"), float("inf"), True, "1"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                TrickDefinition("test", "测试", "flip", duration, 5)
        with self.assertRaises(ValueError):
            TrickDefinition("test", "测试", "flip", 6, 5)

    def test_dynamic_face_and_effect_choices_use_explicit_registration(self):
        configured = source()
        registry = BUILTIN_REGISTRY
        for identifier, slot in (("test_goggles", "face"), ("test_glow", "effect")):
            definition = AccessoryDefinition(identifier, slot, "sunglasses", "wear_" + identifier, "测试收藏")
            registry = registry.with_accessories(definition)
            configured["perks"][definition.perk_id] = {"name": "测试收藏", "kind": "accessory", "slot": slot,
                                                      "item": identifier, "level": 1, "store_only": True}
            configured["accessory_products"][identifier] = {"name": "测试收藏", "icon": "sunglasses", "description": "测试专用",
                                                            "slot": slot, "cost": 10}
        model = PetModel(PetData(coins=100), catalog=Catalog(configured, registry=registry))
        for identifier, slot in (("test_goggles", "face"), ("test_glow", "effect")):
            self.assertFalse(model.equip_accessory(slot, identifier))
            self.assertTrue(model.buy_accessory(identifier))
            self.assertTrue(model.equip_accessory(slot, identifier))
            self.assertEqual(model.effective_accessories()[slot], identifier)
        restored = PetModel(PetData.from_dict(model.snapshot()), catalog=model.catalog)
        self.assertEqual(restored.effective_accessories(), model.effective_accessories())
        self.assertEqual(model.data.coins, 80)

    def test_unregistered_draft_products_cannot_be_smuggled_via_json(self):
        mutations = (
            ("items", "future_food", deepcopy(source()["items"]["sugar"])),
            ("trick_products", "recall_taunt", deepcopy(source()["trick_products"]["screen_roll"])),
            ("accessory_products", "tactical_monocle", deepcopy(source()["accessory_products"]["cooling_cap"])),
            ("furniture", "future_room", {**deepcopy(source()["furniture"]["sakura_room"]), "id": "future_room"}),
        )
        for category, key, value in mutations:
            configured = source()
            configured[category][key] = value
            with self.subTest(category=category), self.assertRaises(ValueError):
                Catalog(configured)

    def test_dynamic_trick_metadata_drives_permission_cooldown_and_zero_reward(self):
        configured = source()
        registry = BUILTIN_REGISTRY.with_tricks(TrickDefinition("test_performance", "测试动作", "flip", 2, 9))
        configured["trick_products"]["test_performance"] = {"name": "测试动作", "icon": "flip", "description": "测试注册",
                                                           "cost": 10}
        pet = PetModel(PetData(coins=100), catalog=Catalog(configured, registry=registry))
        self.assertFalse(pet.has_trick("test_performance"))
        self.assertTrue(pet.buy_trick("test_performance"))
        self.assertTrue(pet.record_trick("test_performance"))
        self.assertEqual((pet.trick_busy, pet.trick_cooldowns["test_performance"], pet.data.affection_exp), (2, 9, 0))
        self.assertEqual(pet.data.coins, 90)
        self.assertFalse(pet.buy_trick("test_performance"))
        self.assertEqual(pet.data.coins, 90)

    def test_icon_references_and_mismatched_registered_slots_rejected(self):
        configured = source()
        configured["items"]["sugar"]["icon"] = "../private"
        with self.assertRaises(ValueError):
            Catalog(configured)
        configured = source()
        configured["accessory_products"]["cooling_cap"]["slot"] = "back"
        with self.assertRaises(ValueError):
            Catalog(configured)
        configured = source()
        configured["perks"]["accessory_crown"]["item"] = "sunglasses"
        with self.assertRaises(ValueError):
            Catalog(configured)

    def test_explicit_generic_food_and_furniture_registration_can_extend_catalog(self):
        configured = source()
        configured["items"]["test_snack"] = deepcopy(configured["items"]["sugar"])
        configured["furniture"]["test_rug"] = {**deepcopy(configured["furniture"]["lotus_cushion"]),
                                               "id": "test_rug"}
        registry = BUILTIN_REGISTRY.with_items("test_snack").with_furniture("test_rug", "rug")
        pet = PetModel(PetData(coins=1000, hunger=1), catalog=Catalog(configured, registry=registry))
        self.assertTrue(pet.buy_item("test_snack", feed_now=True))
        self.assertEqual((pet.data.hunger, pet.data.affection_exp), (16, 0))
        self.assertTrue(pet.buy_furniture("test_rug"))
        self.assertTrue(pet.equip_furniture("rug", "test_rug"))
        restored = PetModel(PetData.from_dict(pet.snapshot()), catalog=pet.catalog)
        self.assertEqual(restored.data.equipped_furniture["rug"], "test_rug")

    def test_catalog_icon_allowlist_is_safe_and_covers_all_active_references(self):
        catalog = Catalog.load()
        for mapping in (catalog.items, catalog.furniture, catalog.trick_products, catalog.accessory_products):
            for key, product in mapping.items():
                self.assertIn(product.get("icon", product.get("emoji", key)), catalog.icon_ids)
        self.assertTrue(catalog.registry.icon_ids.issubset(catalog.icon_ids))
        self.assertNotIn("recall_taunt", catalog.icon_ids)
        self.assertTrue(all("/" not in key and "\\" not in key for key in catalog.icon_ids))


class CompatibilityAndHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = ROOT / "tests" / "artifacts" / ("part1-registry-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        cls.artifacts.mkdir(parents=True, exist_ok=False)

    def test_legacy_missing_history_and_boolean_face_migrate(self):
        for raw in ({"accessories": {"face": True}}, {"accessories": {"sunglasses": True}}):
            restored = PetData.from_dict(raw)
            self.assertEqual(restored.accessories["face"], "sunglasses")
            self.assertEqual(restored.interaction_history, [])
            self.assertEqual(PetData.from_dict(restored.to_dict()).accessories["face"], "sunglasses")
        self.assertEqual(PetData.from_dict({"accessories": {"face": False}}).accessories["face"], "")

    def test_safe_future_ids_and_ownership_roundtrip_but_are_not_effective(self):
        raw = {"accessories": {"head": "future_hat", "face": "future_glasses", "back": "future_pack", "effect": "future_glow"},
               "purchased_accessories": ["future_hat", "future_glasses"], "purchased_tricks": ["future_trick"],
               "inventory": {"future_food": 2}}
        data = PetData.from_dict(raw)
        manager = SaveManager(self.artifacts / "future-save.json")
        manager.update_game(data.to_dict())
        restored = PetModel(manager.load_game_state())
        for slot in ("head", "face", "back", "effect"):
            self.assertEqual(restored.data.accessories[slot], raw["accessories"][slot])
            self.assertEqual(restored.effective_accessories()[slot], "")
        self.assertEqual(restored.data.purchased_accessories, raw["purchased_accessories"])
        self.assertEqual(restored.data.inventory["future_food"], 2)
        self.assertFalse(restored.has_trick("future_trick"))
        self.assertFalse(restored.use_item("future_food"))

    def test_invalid_id_types_and_paths_still_fail_closed(self):
        cases = ({"accessories": {"face": "../x"}}, {"accessories": {"face": []}},
                 {"accessories": {"head": "sunglasses"}}, {"accessories": {"sunglasses": "yes"}},
                 {"purchased_accessories": ["../x"]}, {"purchased_tricks": ["../x"]},
                 {"inventory": {"../x": 1}})
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                PetData.from_dict(raw)

    def test_history_keeps_last_three_accepted_actions_only(self):
        pet = PetModel(PetData(coins=10000), rng=random.Random(1))
        pet.poke()
        pet.pet_head()
        self.assertFalse(pet.pet_head())
        self.assertTrue(pet.buy_item("sugar", feed_now=True))
        self.assertTrue(pet.buy_item("music_box", feed_now=True))
        self.assertEqual(pet.data.interaction_history, [{"event": "pet", "item_id": ""},
            {"event": "feed", "item_id": "sugar"}, {"event": "gift", "item_id": "music_box"}])
        self.assertEqual(pet.data.stats["total_feeds"], 1)
        self.assertEqual(pet.data.stats["total_presents"], 1)

    def test_purchase_without_use_and_rejected_actions_do_not_record(self):
        pet = PetModel(PetData(coins=10000))
        self.assertTrue(pet.buy_item("sugar"))
        self.assertFalse(pet.use_item("music_box"))
        self.assertFalse(pet.buy_item("tes_guitar", feed_now=True))
        self.assertFalse(pet.record_trick("flip"))
        self.assertEqual(pet.data.interaction_history, [])
        self.assertEqual(pet.data.inventory["sugar"], 1)
        self.assertTrue(pet.use_item("sugar"))
        self.assertFalse(pet.use_item("sugar"))
        self.assertEqual(pet.data.interaction_history, [{"event": "feed", "item_id": "sugar"}])

    def test_history_rejects_unbounded_or_free_text_payloads(self):
        invalid = ([{"event": "poke", "item_id": ""}] * 4,
                   [{"event": "poke", "item_id": "", "text": "secret"}],
                   [{"event": "clipboard", "item_id": ""}],
                   [{"event": ["poke"], "item_id": ""}], [{"event": "feed", "item_id": "../private"}], "text")
        for history in invalid:
            with self.subTest(history=history), self.assertRaises(ValueError):
                PetData.from_dict({"interaction_history": history})

    def test_history_replace_and_cross_process_restore(self):
        pet = PetModel(PetData(affection_level=6), rng=random.Random(1))
        pet.poke()
        pet.record_drop()
        pet.record_shake()
        manager = SaveManager(self.artifacts / "history-save.json")
        manager.update_game(pet.snapshot())
        code = "from pathlib import Path;from save_manager import SaveManager;import json,sys;print(json.dumps(SaveManager(Path(sys.argv[1])).load_game_state().interaction_history))"
        result = subprocess.run([sys.executable, "-c", code, str(manager.path)], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), pet.data.interaction_history)
        pet.replace_data(PetData(interaction_history=[{"event": "feed", "item_id": "sugar"}]))
        self.assertEqual(pet.data.interaction_history, [{"event": "feed", "item_id": "sugar"}])

    def test_duplicate_json_keys_are_rejected_without_rewriting(self):
        path = self.artifacts / "duplicate-save.json"
        before = b'{"schema_version":5,"coins":1,"coins":999}'
        path.write_bytes(before)
        with self.assertRaises(SaveDataError):
            SaveManager(path).load_game_state()
        self.assertEqual(path.read_bytes(), before)
        config = self.artifacts / "duplicate-catalog.json"
        config.write_text('{"items":{},"items":{}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            Catalog.load(config)


class TrickLifecycleTests(unittest.TestCase):
    def model(self):
        return PetModel(PetData(affection_level=30, purchased_tricks=["screen_roll"]))

    def test_lifecycle_started_and_finish_are_once_and_rejection_is_quiet(self):
        pet = self.model()
        events = []
        pet.trick_lifecycle.connect(events.append)
        self.assertFalse(pet.record_trick("not_registered"))
        self.assertTrue(pet.record_trick("clone"))
        self.assertFalse(pet.record_trick("ball"))
        self.assertTrue(pet.finish_trick("clone", "input"))
        self.assertFalse(pet.finish_trick("clone", "input"))
        self.assertEqual(events, [{"phase": "started", "trick_id": "clone", "reason": "accepted"},
                                  {"phase": "interrupted", "trick_id": "clone", "reason": "input"}])
        self.assertEqual(pet.data.interaction_history, [{"event": "trick", "item_id": "clone"}])

    def test_preflight_replacement_preserves_permissions_and_cooldown(self):
        pet = self.model()
        self.assertTrue(pet.record_trick("clone"))
        self.assertFalse(pet.can_perform_trick("ball"))
        self.assertTrue(pet.can_perform_trick("ball", replacing=True))
        self.assertFalse(pet.can_perform_trick("clone", replacing=True))
        self.assertFalse(pet.can_perform_trick("unknown", replacing=True))
        self.assertEqual(pet._active_trick_id, "clone")
        self.assertTrue(pet.finish_trick("clone", "replaced"))
        self.assertTrue(pet.record_trick("ball"))
        pet.data.hunger = 0
        self.assertFalse(pet.can_perform_trick("disco", replacing=True))

    def test_timer_standalone_and_managed_physics_completion(self):
        for managed in (False, True):
            pet = self.model()
            events = []
            pet.trick_lifecycle.connect(events.append)
            self.assertTrue(pet.set_presentation_managed(managed))
            self.assertTrue(pet.record_trick("clone"))
            pet.advance(3)
            if managed:
                self.assertEqual(pet._active_trick_id, "clone")
                self.assertGreater(pet.trick_busy, 0)
                self.assertFalse(pet.can_perform_trick("ball"))
                self.assertEqual(len(events), 1)
                self.assertTrue(pet.finish_trick("clone"))
            else:
                self.assertEqual(pet._active_trick_id, "")
            self.assertEqual(events[-1]["phase"], "finished")
            pet.advance(3)
            self.assertEqual(len(events), 2)
            self.assertNotIn("_presentation_managed", pet.snapshot())

    def test_restore_interrupts_once_keeps_process_currency_permission(self):
        pet = self.model()
        pet.set_unlimited_coins(True, authorized=True)
        pet.set_presentation_managed(True)
        events = []
        pet.trick_lifecycle.connect(events.append)
        pet.record_trick("ball")
        pet.replace_data(PetData(coins=0))
        self.assertEqual(events[-1], {"phase": "interrupted", "trick_id": "ball", "reason": "restore"})
        self.assertTrue(pet.unlimited_coins)
        self.assertTrue(pet._presentation_managed)
        self.assertEqual(pet.data.interaction_history, [])
        self.assertFalse(pet.finish_trick("ball"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
