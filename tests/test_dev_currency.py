"""Developer free spending preserves player balances and all other game rules."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import PetData, PetModel
from save_manager import SaveManager


class DeveloperCurrencyTests(unittest.TestCase):
    def model(self, *, coins=0, developer=True, **values):
        pet = PetModel(PetData(coins=coins, **values), rng=random.Random(1))
        if developer:
            self.assertTrue(pet.set_unlimited_coins(True, authorized=True))
        return pet

    def test_default_model_has_real_balance_and_needs_explicit_authorization(self):
        pet = self.model(developer=False)
        before = pet.snapshot()
        self.assertFalse(pet.unlimited_coins)
        self.assertFalse(pet.set_unlimited_coins(True))
        self.assertFalse(pet.set_unlimited_coins(True, authorized=1))
        self.assertEqual(pet.snapshot(), before)

    def test_runtime_toggle_emits_refresh_without_changing_serialized_state(self):
        pet = self.model(coins=7, developer=False)
        states = []
        pet.state_changed.connect(states.append)
        before = pet.snapshot()
        self.assertTrue(pet.set_unlimited_coins(True, authorized=True))
        self.assertEqual(states, [before])
        self.assertTrue(pet.set_unlimited_coins(True, authorized=True))
        self.assertEqual(len(states), 1)
        self.assertTrue(pet.set_unlimited_coins(False))
        self.assertEqual(states, [before, before])
        self.assertEqual(pet.data.coins, 7)

    def test_malformed_prices_cannot_credit_money_or_bypass_validation(self):
        for developer in (False, True):
            pet = self.model(coins=30, developer=developer)
            for invalid in (-1, True, None, '30', 2.5, float('inf')):
                with self.subTest(developer=developer, invalid=invalid):
                    self.assertFalse(pet.can_afford(invalid))
                    self.assertFalse(pet.spend_coins(invalid))
            self.assertEqual(pet.data.coins, 30)
        self.assertFalse(pet.set_unlimited_coins(1, authorized=True))

    def test_free_spending_accepts_arbitrary_integer_cost_without_sentinel_balance(self):
        pet = self.model(coins=0)
        self.assertTrue(pet.can_afford(10 ** 30))
        self.assertTrue(pet.spend_coins(10 ** 30))
        self.assertEqual(pet.data.coins, 0)
        self.assertIs(type(pet.data.coins), int)

    def test_all_food_and_gift_inventory_purchases_work_at_zero(self):
        catalog = self.model().catalog
        for key in catalog.items:
            with self.subTest(item=key):
                pet = self.model()
                self.assertTrue(pet.buy_item(key))
                self.assertEqual(pet.data.inventory[key], 1)
                self.assertEqual(pet.data.coins, 0)

    def test_buy_and_feed_has_one_consumption_and_no_food_exp(self):
        pet = self.model(hunger=1)
        self.assertTrue(pet.buy_item('sugar', feed_now=True))
        self.assertEqual(pet.data.hunger, 16)
        self.assertEqual(pet.data.stats['total_feeds'], 1)
        self.assertEqual(pet.data.affection_exp, 0)
        self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.use_item('sugar'))

    def test_normal_purchases_still_refuse_and_deduct_exact_price(self):
        for key in ('sugar', 'music_box'):
            with self.subTest(item=key):
                pet = self.model(developer=False)
                price = pet.item(key)['cost']
                self.assertFalse(pet.buy_item(key))
                self.assertNotIn(key, pet.data.inventory)
                pet.data.coins = price + 1
                self.assertTrue(pet.buy_item(key))
                self.assertEqual(pet.data.coins, 1)

    def test_all_store_furniture_free_but_level_only_furniture_stays_locked(self):
        pet = self.model()
        for key, product in pet.catalog.furniture.items():
            if key in pet.data.owned_furniture:
                continue
            with self.subTest(furniture=key):
                self.assertEqual(pet.buy_furniture(key), not bool(product.get('unlock_perk')))
                self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.buy_furniture('not-real'))

    def test_furniture_cannot_be_bought_twice(self):
        pet = self.model()
        self.assertTrue(pet.buy_furniture('warm_lamp'))
        purchases = pet.data.stats['furniture_purchases']
        self.assertFalse(pet.buy_furniture('warm_lamp'))
        self.assertEqual(pet.data.stats['furniture_purchases'], purchases)
        self.assertEqual(pet.data.owned_furniture.count('warm_lamp'), 1)

    def test_store_trick_purchase_free_but_still_respects_cooldown(self):
        pet = self.model()
        self.assertFalse(pet.has_trick('screen_roll'))
        self.assertTrue(pet.buy_trick('screen_roll'))
        self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.buy_trick('screen_roll'))
        self.assertTrue(pet.record_trick('screen_roll'))
        self.assertFalse(pet.record_trick('screen_roll'))
        pet.finish_trick('screen_roll')
        self.assertFalse(pet.record_trick('screen_roll'))
        self.assertFalse(pet.buy_trick('not-real'))

    def test_free_coins_do_not_unlock_level_tricks_or_bypass_starvation(self):
        pet = self.model()
        self.assertFalse(pet.can_perform_trick('flip'))
        self.assertFalse(pet.equip_accessory('head', 'crown'))
        self.assertTrue(pet.buy_trick('screen_roll'))
        pet.set_hunger(0)
        self.assertFalse(pet.can_perform_trick('screen_roll'))

    def test_accessory_purchases_free_and_permanent_without_duplicate_records(self):
        pet = self.model()
        for key in pet.catalog.accessory_products:
            with self.subTest(accessory=key):
                self.assertTrue(pet.buy_accessory(key))
                self.assertIn(key, pet.data.purchased_accessories)
                self.assertTrue(pet.buy_accessory(key))
                self.assertEqual(pet.data.purchased_accessories.count(key), 1)
                self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.buy_accessory('not-real'))

    def test_team_skin_purchases_free_without_unlocking_unpurchased_skins(self):
        pet = self.model()
        self.assertFalse(pet.can_use_skin('team_s16_tes'))
        for key in pet.catalog.team_skins:
            with self.subTest(skin=key):
                self.assertTrue(pet.buy_team_skin(key))
                self.assertTrue(pet.buy_team_skin(key))
                self.assertEqual(pet.data.owned_team_skins.count(key), 1)
                self.assertEqual(pet.data.coins, 0)
        self.assertFalse(pet.buy_team_skin('not-real'))

    def test_tes_exclusive_gifts_still_require_the_eligible_selected_skin(self):
        pet = self.model()
        restricted = [key for key, item in pet.catalog.items.items() if item.get('required_skin')]
        self.assertTrue(restricted)
        for key in restricted:
            with self.subTest(gift=key):
                before = pet.snapshot()
                self.assertFalse(pet.buy_item(key, feed_now=True))
                self.assertEqual(pet.snapshot(), before)
                self.assertTrue(pet.buy_item(key))
                self.assertFalse(pet.use_item(key))
                self.assertEqual(pet.data.inventory[key], 1)
        self.assertTrue(pet.buy_team_skin('team_s16_tes'))
        self.assertTrue(pet.select_skin('team_s16_tes'))
        self.assertTrue(pet.use_item(restricted[0]))
        self.assertEqual(pet.data.inventory[restricted[0]], 0)

    def test_legacy_early_closet_unlock_uses_the_same_spending_rule(self):
        pet = self.model()
        self.assertTrue(pet.unlock_custom_import())
        self.assertTrue(pet.unlock_custom_import())
        self.assertEqual(pet.data.coins, 0)
        self.assertTrue(pet.data.custom_import_unlocked)

    def test_disabling_free_spending_reverts_immediately_to_real_balance(self):
        pet = self.model(coins=7)
        self.assertTrue(pet.buy_item('sugar'))
        self.assertTrue(pet.set_unlimited_coins(False))
        self.assertFalse(pet.buy_item('sugar'))
        self.assertEqual(pet.data.coins, 7)
        self.assertEqual(pet.data.inventory['sugar'], 1)

    def test_income_remains_real_and_survives_developer_mode_switch(self):
        pet = self.model(coins=3)
        received = []
        pet.gains_received.connect(received.append)
        self.assertTrue(pet.offer_collectible())
        amount = sum(event.get('coins', 0) for event in received)
        self.assertGreaterEqual(amount, 10)
        self.assertLessEqual(amount, 20)
        self.assertEqual(pet.data.coins, 3 + amount)
        pet.set_unlimited_coins(False)
        self.assertEqual(pet.data.coins, 3 + amount)

    def test_replace_data_preserves_only_the_process_currency_policy(self):
        pet = self.model()
        pet.replace_data(PetData(coins=42))
        self.assertTrue(pet.unlimited_coins)
        self.assertEqual(pet.data.coins, 42)
        self.assertTrue(pet.buy_item('sugar'))
        self.assertEqual(pet.data.coins, 42)
        restored = PetModel(PetData.from_dict(pet.snapshot()))
        self.assertFalse(restored.unlimited_coins)
        self.assertTrue(restored.buy_item('sugar'))
        self.assertEqual(restored.data.coins, 12)

    def test_disk_save_and_fresh_process_never_inherit_unlimited_flag(self):
        artifacts = ROOT / 'tests/artifacts' / datetime.now().strftime('dev-currency-%Y%m%d-%H%M%S-%f')
        artifacts.mkdir(parents=True, exist_ok=False)
        path = artifacts / 'save_data.json'
        pet = self.model(coins=7)
        self.assertTrue(pet.buy_item('sugar'))
        SaveManager(path).update_game(pet.snapshot())
        payload = json.loads(path.read_text(encoding='utf8'))
        self.assertEqual(payload['coins'], 7)
        self.assertNotIn('unlimited_coins', payload)
        self.assertNotIn('dev_mode', payload)
        code = (
            'import json,sys;from pathlib import Path;'
            'from models import PetModel;from save_manager import SaveManager;'
            'm=PetModel(SaveManager(Path(sys.argv[1])).load_game_state());'
            'print(json.dumps([m.unlimited_coins,m.data.coins,m.buy_item("sugar"),m.data.inventory["sugar"]]))'
        )
        result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=str(ROOT),
                                capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), [False, 7, False, 1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
