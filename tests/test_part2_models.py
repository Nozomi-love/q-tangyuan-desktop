"""Part 2: real commerce, permanent ownership and bounded practice progress."""
from __future__ import annotations

from datetime import datetime
from itertools import permutations
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_registry import BUILTIN_REGISTRY
from models import Catalog, PetData, PetModel
from save_manager import SaveManager

GIFTS = ("gnar_workbook", "practice_hourglass", "fist_bump_glove")
FOODS = ("postmatch_noodles", "late_practice_snack")
ACCESSORIES = {"seven_goggles": ("face", 540), "kiting_scarf": ("back", 480)}
FURNITURE = {"practice_room": ("theme", 720), "summit_wall": ("wall", 480)}
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part2-models-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def model(**kwargs):
    return PetModel(PetData(coins=10000, **kwargs))


class PracticeCollectionCommerceTests(unittest.TestCase):
    def test_batch_exact_ids_prices_slots_and_future_content_absent(self):
        catalog = Catalog.load()
        self.assertEqual((len(catalog.items), len(catalog.furniture), len(catalog.accessory_products)), (28, 23, 7))
        self.assertTrue(set(GIFTS + FOODS).issubset(catalog.items))
        for key in GIFTS:
            self.assertEqual({k: catalog.items[key][k] for k in ("cost", "exp", "hunger", "tier", "category", "performance_seconds")},
                             {"cost": 60, "exp": 20, "hunger": 0, "tier": 1, "category": "gift", "performance_seconds": 7})
        for key, (slot, price) in ACCESSORIES.items():
            self.assertEqual(catalog.accessory_products[key]["slot"], slot)
            self.assertEqual(catalog.accessory_products[key]["cost"], price)
            self.assertEqual(catalog.accessory_definitions[key].slot, slot)
        for key, (slot, price) in FURNITURE.items():
            self.assertEqual((catalog.furniture[key]["slot"], catalog.furniture[key]["price"]), (slot, price))
        self.assertEqual(catalog.trick_products["reverse_flash"]["cost"], 360)
        self.assertEqual((BUILTIN_REGISTRY.tricks["reverse_flash"].duration,
                          BUILTIN_REGISTRY.tricks["reverse_flash"].cooldown,
                          BUILTIN_REGISTRY.tricks["reverse_flash"].exp), (2.6, 12, 0))
        for key in ("recall_taunt", "golden_stasis", "prematch_flag", "tactical_monocle"):
            self.assertNotIn(key, catalog.content_ids)

    def test_gift_purchase_then_use_settles_once_with_original_dialogue(self):
        for key in GIFTS:
            with self.subTest(item=key):
                pet = model(hunger=29)
                events = []
                pet.presentation_requested.connect(events.append)
                self.assertTrue(pet.buy_item(key))
                self.assertEqual((pet.data.coins, pet.data.inventory[key]), (9940, 1))
                self.assertEqual(events, [])
                before = pet._lifetime_exp()
                self.assertTrue(pet.use_item(key))
                self.assertEqual((pet.data.hunger, pet._lifetime_exp()-before), (29, 20))
                self.assertEqual((pet.data.inventory[key], pet.data.stats["total_presents"]), (0, 1))
                self.assertFalse(pet.use_item(key))
                self.assertEqual(len(events), 1)
                self.assertEqual((events[0]["effect"], events[0]["duration"], events[0]["exp_gain"]), (key, 7, 20))
                self.assertEqual(events[0]["dialogue"], pet.catalog.dialogues["item_" + key][0])
                self.assertEqual(pet.data.interaction_history, [{"event": "gift", "item_id": key}])

    def test_food_restores_only_actual_hunger_and_never_affection(self):
        for key, cost, hunger in (("postmatch_noodles", 30, 15), ("late_practice_snack", 75, 35)):
            for starting in (0, 40, 99, 100):
                with self.subTest(item=key, hunger=starting):
                    pet = model(hunger=starting)
                    events, gains = [], []
                    pet.presentation_requested.connect(events.append)
                    pet.gains_received.connect(gains.append)
                    before = pet._lifetime_exp()
                    self.assertTrue(pet.buy_item(key, feed_now=True))
                    self.assertEqual((pet.data.hunger, pet.data.coins), (min(100, starting+hunger), 10000-cost))
                    self.assertEqual(pet._lifetime_exp(), before)
                    self.assertEqual(events[0]["hunger_gain"], min(hunger, 100-starting))
                    self.assertEqual(events[0]["exp_gain"], 0)
                    self.assertFalse(any(gain.get("exp") for gain in gains))
                    self.assertEqual(pet.data.stats["starvation_recoveries"], int(starting == 0))

    def test_zero_balance_and_unknown_requests_cannot_mutate_player_state(self):
        pet = PetModel(PetData(coins=0))
        before = pet.snapshot()
        for key in GIFTS + FOODS:
            self.assertFalse(pet.buy_item(key, feed_now=True))
            self.assertFalse(pet.use_item(key))
        for key in ACCESSORIES:
            self.assertFalse(pet.buy_accessory(key))
        for key in FURNITURE:
            self.assertFalse(pet.buy_furniture(key))
        self.assertFalse(pet.buy_trick("reverse_flash"))
        self.assertFalse(pet.buy_item("prematch_flag"))
        self.assertEqual(pet.snapshot(), before)

    def test_store_accessories_require_payment_even_at_level_30_and_keep_other_slots(self):
        pet = model(affection_level=30)
        self.assertTrue(pet.equip_accessory("head", "crown"))
        self.assertTrue(pet.equip_accessory("effect", "steam"))
        for key, (slot, cost) in ACCESSORIES.items():
            self.assertFalse(pet.equip_accessory(slot, key))
            before = pet.data.coins
            self.assertTrue(pet.buy_accessory(key))
            self.assertEqual(pet.data.coins, before-cost)
            self.assertTrue(pet.equip_accessory(slot, key))
            self.assertEqual(pet.effective_accessories()[slot], key)
            self.assertTrue(pet.buy_accessory(key))
            self.assertEqual(pet.data.coins, before-cost)
        before = pet.snapshot()
        self.assertFalse(pet.equip_accessory("head", "seven_goggles"))
        self.assertEqual(pet.snapshot(), before)
        self.assertTrue(pet.equip_accessory("face", ""))
        self.assertEqual(pet.effective_accessories()["back"], "kiting_scarf")
        self.assertEqual(pet.effective_accessories()["head"], "crown")
        self.assertEqual(pet.effective_accessories()["effect"], "steam")

    def test_paid_furniture_requires_ownership_and_rejects_duplicate_charge(self):
        pet = model()
        for key, (slot, price) in FURNITURE.items():
            self.assertFalse(pet.equip_furniture(slot, key))
            before = pet.data.coins
            self.assertTrue(pet.buy_furniture(key))
            self.assertTrue(pet.equip_furniture(slot, key))
            self.assertEqual(pet.data.coins, before-price)
            self.assertFalse(pet.buy_furniture(key))
            self.assertEqual(pet.data.coins, before-price)
        before = pet._lifetime_exp()
        pet.advance(6)
        self.assertEqual(pet._lifetime_exp(), before, "A training room does not passively grant experience")

    def test_reverse_flash_requires_learning_and_never_rewards_or_bypasses_cooldown(self):
        pet = model(affection_level=30)
        self.assertFalse(pet.record_trick("reverse_flash"))
        self.assertTrue(pet.buy_trick("reverse_flash"))
        self.assertEqual(pet.data.coins, 9640)
        self.assertFalse(pet.buy_trick("reverse_flash"))
        events, gains = [], []
        pet.trick_lifecycle.connect(events.append)
        pet.gains_received.connect(gains.append)
        baseline = (pet._lifetime_exp(), pet.data.coins, pet.data.hunger)
        self.assertTrue(pet.record_trick("reverse_flash"))
        self.assertEqual((pet.trick_busy, pet.trick_cooldowns["reverse_flash"]), (2.6, 12))
        self.assertFalse(pet.record_trick("reverse_flash"))
        self.assertTrue(pet.finish_trick("reverse_flash", "input"))
        self.assertFalse(pet.can_perform_trick("reverse_flash"))
        pet.advance(12)
        self.assertTrue(pet.record_trick("reverse_flash"))
        self.assertTrue(pet.finish_trick("reverse_flash"))
        self.assertEqual((pet._lifetime_exp(), pet.data.coins, pet.data.hunger), baseline)
        self.assertEqual(gains, [])
        self.assertEqual([event["phase"] for event in events], ["started", "interrupted", "started", "finished"])

    def test_developer_currency_uses_all_new_purchase_paths_without_free_entitlements(self):
        pet = PetModel(PetData(coins=0))
        self.assertFalse(pet.set_unlimited_coins(True))
        self.assertFalse(pet.has_trick("reverse_flash"))
        self.assertTrue(pet.set_unlimited_coins(True, authorized=True))
        for key in GIFTS + FOODS:
            self.assertTrue(pet.buy_item(key))
        for key in ACCESSORIES:
            self.assertTrue(pet.buy_accessory(key))
        for key in FURNITURE:
            self.assertTrue(pet.buy_furniture(key))
        self.assertTrue(pet.buy_trick("reverse_flash"))
        self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.can_perform_trick("flip"), "Infinite currency does not grant level perks")
        restored = PetModel(PetData.from_dict(pet.snapshot()))
        self.assertFalse(restored.unlimited_coins)
        self.assertFalse(restored.buy_item("gnar_workbook"))
        self.assertTrue(restored.has_trick("reverse_flash"))
        self.assertEqual(restored.data.coins, 0)


class PracticeProgressTests(unittest.TestCase):
    def test_progress_validation_is_bounded_and_old_save_defaults_empty(self):
        self.assertEqual(PetData.from_dict({}).practice_experiences, [])
        for bad in (None, "gnar_workbook", ["gnar_workbook", "gnar_workbook"], ["../practice"], ["fist_bump_glove"], [False], [{"id": "training_dummy"}]):
            with self.subTest(progress=bad), self.assertRaises(ValueError):
                PetData.from_dict({"practice_experiences": bad})

    def test_all_three_real_experiences_required_in_any_order_no_hat_required(self):
        for order in permutations(("gnar_workbook", "practice_hourglass", "training_dummy")):
            with self.subTest(order=order):
                pet = model()
                pet.buy_furniture("training_dummy")
                pet.equip_furniture("corner", "training_dummy")
                for index, key in enumerate(order):
                    if key == "training_dummy":
                        self.assertTrue(pet.record_furniture_interaction(key))
                    else:
                        self.assertTrue(pet.buy_item(key, feed_now=True))
                    self.assertEqual("这次真练好了" in pet.data.titles, index == 2)
                self.assertEqual(set(pet.data.practice_experiences), set(order))
                self.assertEqual(pet.data.titles.count("这次真练好了"), 1)
                self.assertEqual(pet.effective_accessories()["head"], "")
                self.assertEqual(pet._lifetime_exp(), 40)
                self.assertTrue(pet.equip_title("这次真练好了"))

    def test_real_dummy_only_and_repeated_click_is_a_silent_noop(self):
        pet = model()
        before = pet.snapshot()
        self.assertFalse(pet.record_furniture_interaction("training_dummy"))
        self.assertFalse(pet.record_furniture_interaction("gnar_workbook"))
        self.assertFalse(pet.record_furniture_interaction("tactics_screen"))
        self.assertEqual(pet.snapshot(), before)
        pet.buy_furniture("training_dummy")
        self.assertFalse(pet.record_furniture_interaction("training_dummy"))
        pet.equip_furniture("corner", "training_dummy")
        changed = []
        pet.state_changed.connect(changed.append)
        self.assertTrue(pet.record_furniture_interaction("training_dummy"))
        before = pet.snapshot()
        self.assertTrue(pet.record_furniture_interaction("training_dummy"))
        self.assertEqual(pet.snapshot(), before)
        self.assertEqual(len(changed), 1)
        self.assertEqual(pet._lifetime_exp(), 0)
        pet.equip_furniture("corner", "")
        self.assertFalse(pet.record_furniture_interaction("training_dummy"))

    def test_purchase_preview_and_failed_use_do_not_record_experiences(self):
        pet = model()
        self.assertTrue(pet.buy_item("gnar_workbook"))
        self.assertTrue(pet.buy_item("practice_hourglass"))
        self.assertEqual(pet.data.practice_experiences, [])
        self.assertNotIn("这次真练好了", pet.data.titles)
        pet.data.inventory["practice_hourglass"] = 0
        self.assertFalse(pet.use_item("practice_hourglass"))
        self.assertEqual(pet.data.practice_experiences, [])
        self.assertTrue(pet.use_item("gnar_workbook"))
        self.assertEqual(pet.data.practice_experiences, ["gnar_workbook"])
        self.assertFalse(pet.use_item("gnar_workbook"))
        self.assertEqual(pet.data.practice_experiences, ["gnar_workbook"])

    def test_titles_are_once_and_do_not_add_resources_beyond_the_consumed_gift(self):
        pet = model(practice_experiences=["gnar_workbook", "practice_hourglass"])
        pet.buy_furniture("training_dummy")
        pet.equip_furniture("corner", "training_dummy")
        gains = []
        pet.gains_received.connect(gains.append)
        resources = (pet.data.coins, pet._lifetime_exp(), pet.data.hunger)
        self.assertTrue(pet.record_furniture_interaction("training_dummy"))
        self.assertTrue(pet.record_furniture_interaction("training_dummy"))
        self.assertEqual((pet.data.coins, pet._lifetime_exp(), pet.data.hunger), resources)
        self.assertEqual(gains, [])
        self.assertTrue(pet.buy_item("gnar_workbook", feed_now=True))
        self.assertEqual(pet._lifetime_exp(), resources[1] + 20)
        self.assertEqual(pet.data.coins, resources[0] - 60)
        self.assertEqual(pet.data.titles.count("这次真练好了"), 1)

    def test_summit_title_needs_installed_wall_and_pickaxe_not_backpack(self):
        pet = model()
        self.assertTrue(pet.buy_item("summit_pickaxe", feed_now=True))
        self.assertNotIn("登峰造圆", pet.data.titles)
        self.assertTrue(pet.buy_furniture("summit_wall"))
        self.assertTrue(pet.buy_item("summit_pickaxe", feed_now=True))
        self.assertNotIn("登峰造圆", pet.data.titles)
        self.assertTrue(pet.equip_furniture("wall", "summit_wall"))
        before = (pet.data.coins, pet._lifetime_exp())
        self.assertTrue(pet.buy_item("summit_pickaxe", feed_now=True))
        self.assertEqual(pet.data.titles.count("登峰造圆"), 1)
        self.assertEqual((pet.data.coins, pet._lifetime_exp()), (before[0]-210, before[1]+80))
        self.assertEqual(pet.effective_accessories().get("back", ""), "")
        self.assertTrue(pet.buy_item("summit_pickaxe", feed_now=True))
        self.assertEqual(pet.data.titles.count("登峰造圆"), 1)

    def test_partial_progress_ownership_and_titles_survive_cross_process_restart(self):
        pet = model()
        pet.buy_item("gnar_workbook", feed_now=True)
        pet.buy_accessory("seven_goggles")
        pet.buy_accessory("kiting_scarf")
        pet.equip_accessory("face", "seven_goggles")
        pet.equip_accessory("back", "kiting_scarf")
        pet.buy_furniture("practice_room")
        pet.equip_furniture("theme", "practice_room")
        pet.buy_furniture("summit_wall")
        pet.equip_furniture("wall", "summit_wall")
        pet.buy_trick("reverse_flash")
        pet.buy_item("summit_pickaxe", feed_now=True)
        path = ART / "progress-save.json"
        manager = SaveManager(path)
        manager.update_game(pet.snapshot(), {"pinned": True, "x_ratio": .37, "y_ratio": .68})
        code = "from pathlib import Path;from save_manager import SaveManager;from models import PetModel;import json,sys;p=PetModel(SaveManager(Path(sys.argv[1])).load_game_state());print(json.dumps(p.snapshot(),ensure_ascii=False))"
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        raw = json.loads(result.stdout)
        restored = PetModel(PetData.from_dict(raw))
        self.assertEqual(restored.data.practice_experiences, ["gnar_workbook"])
        self.assertEqual(restored.effective_accessories(), pet.effective_accessories())
        self.assertEqual(restored.data.equipped_furniture, pet.data.equipped_furniture)
        self.assertIn("登峰造圆", restored.data.titles)
        self.assertTrue(restored.has_trick("reverse_flash"))
        self.assertEqual(json.loads(path.read_text("utf-8"))["schema_version"], 5)
        restored.buy_furniture("training_dummy")
        restored.equip_furniture("corner", "training_dummy")
        restored.record_furniture_interaction("training_dummy")
        restored.buy_item("practice_hourglass", feed_now=True)
        self.assertIn("这次真练好了", restored.data.titles)


if __name__ == "__main__":
    unittest.main(verbosity=2)
