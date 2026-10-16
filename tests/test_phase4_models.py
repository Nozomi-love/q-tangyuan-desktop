"""Phase 4 levels, permissions, customization and trick reward behavior."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import Catalog, PetData, PetModel

class PerkTests(unittest.TestCase):
    def test_milestones_cover_one_to_six_and_cap_stays_thirty(self):
        pet = PetModel()
        self.assertEqual([m['level'] for m in pet.perk_status()], list(range(1,7)))
        self.assertEqual(pet.MAX_LEVEL, 30)
        self.assertFalse(pet.has_perk('custom_import'))
        self.assertFalse(pet.has_perk('not-a-perk'))

    def test_each_level_unlocks_only_its_milestones(self):
        for level in range(1,7):
            pet = PetModel(PetData(affection_level=level))
            for key, perk in pet.catalog.perks.items():
                self.assertEqual(pet.has_perk(key), level >= perk['level'])

    def test_upgrade_unlock_signal_and_guardian_once(self):
        pet = PetModel(PetData(affection_level=5, affection_exp=249))
        events=[]
        pet.perks_unlocked.connect(events.append)
        pet.poke()
        self.assertEqual(pet.data.affection_level,6)
        self.assertIn('✨ 汤圆守护神',pet.data.titles)
        self.assertEqual(len(events),1)
        pet.poke()
        self.assertEqual(len(events),1)
        self.assertEqual(pet.data.titles.count('✨ 汤圆守护神'),1)

    def test_existing_level_restores_rewards_without_coin_grant(self):
        pet = PetModel(PetData(affection_level=6, coins=17))
        self.assertIn('✨ 汤圆守护神',pet.data.titles)
        self.assertEqual(pet.data.coins,17)
        self.assertTrue(pet.has_perk('accessory_bow'))

    def test_early_import_unlock_charges_exactly_once(self):
        pet=PetModel()
        self.assertTrue(pet.unlock_custom_import())
        self.assertEqual(pet.data.coins,50)
        self.assertTrue(pet.unlock_custom_import())
        self.assertEqual(pet.data.coins,50)
        self.assertTrue(PetModel(PetData.from_dict(pet.snapshot())).has_perk('custom_import'))

    def test_early_unlock_insufficient_and_free_at_level_three(self):
        pet=PetModel(PetData(coins=49))
        self.assertFalse(pet.unlock_custom_import())
        self.assertEqual(pet.data.coins,49)
        pet=PetModel(PetData(coins=0,affection_level=3))
        self.assertTrue(pet.unlock_custom_import())
        self.assertEqual(pet.data.coins,0)

    def test_debug_override_requires_authorization_and_does_not_change_level(self):
        pet=PetModel()
        self.assertFalse(pet.set_debug_unlock(True))
        self.assertFalse(pet.has_perk('trick_ball'))
        self.assertTrue(pet.set_debug_unlock(True,authorized=True))
        self.assertTrue(all(pet.has_perk(k) for k in pet.catalog.perks))
        self.assertEqual((pet.data.affection_level,pet.data.affection_exp,pet.data.coins),(1,0,100))
        pet.set_debug_unlock(False,authorized=True)
        self.assertFalse(pet.has_perk('trick_ball'))

    def test_accessory_locked_and_invalid_inputs_are_noops(self):
        pet=PetModel()
        before=pet.snapshot()
        self.assertFalse(pet.equip_accessory('head','crown'))
        self.assertFalse(pet.equip_accessory('head','sunglasses'))
        self.assertFalse(pet.equip_accessory('invalid','sprout'))
        self.assertFalse(pet.set_accessory_offset(31))
        self.assertFalse(pet.set_accessory_offset(True))
        self.assertEqual(pet.snapshot(),before)

    def test_accessory_equip_replaces_slot_offset_and_unequip_persist(self):
        pet=PetModel(PetData(affection_level=6))
        for slot,item in [('head','sprout'),('head','crown'),('head','bow'),('face','sunglasses'),('effect','steam')]:
            self.assertTrue(pet.equip_accessory(slot,item))
        self.assertTrue(pet.set_accessory_offset(-30))
        self.assertTrue(pet.set_accessory_offset(30))
        restored=PetModel(PetData.from_dict(pet.snapshot()))
        self.assertEqual(restored.effective_accessories(),{'head':'bow','face':'sunglasses','effect':'steam','offset_y':30})
        self.assertTrue(restored.equip_accessory('head',''))
        self.assertEqual(restored.effective_accessories()['head'],'')

    def test_debug_equipment_hidden_when_override_disabled(self):
        pet=PetModel()
        pet.set_debug_unlock(True,authorized=True)
        pet.equip_accessory('head','crown')
        pet.set_debug_unlock(False,authorized=True)
        self.assertEqual(pet.effective_accessories()['head'],'')
        self.assertEqual(pet.data.accessories['head'],'crown')

    def test_soul_achievement_on_accessory_and_claim_exactly_once(self):
        pet=PetModel(PetData(affection_level=2))
        pet.equip_accessory('head','sprout')
        self.assertIn('soul_infusion',pet.data.unlocked_achievements)
        coins=pet.data.coins
        self.assertTrue(pet.claim_achievement('soul_infusion'))
        self.assertEqual(pet.data.coins,coins+100)
        self.assertIn('百变星君',pet.data.titles)
        self.assertFalse(pet.claim_achievement('soul_infusion'))

    def test_soul_achievement_on_skin_and_default_does_not_count(self):
        pet=PetModel(PetData(affection_level=3))
        self.assertTrue(pet.select_skin('default'))
        self.assertNotIn('soul_infusion',pet.data.unlocked_achievements)
        self.assertTrue(pet.select_skin('user_'+'a'*32,imported=True))
        self.assertIn('soul_infusion',pet.data.unlocked_achievements)

    def test_bad_skin_ids_and_locked_import_rejected(self):
        pet=PetModel()
        for bad in ['../external','user_../bad','https://x/a.gif',True]:
            self.assertFalse(pet.select_skin(bad))
        self.assertFalse(pet.select_skin('user_'+'a'*32))
        self.assertEqual(pet.data.selected_skin_id,'default')

    def test_flip_exp_cooldown_mutual_exclusion_and_repeat(self):
        pet=PetModel(PetData(affection_level=6))
        self.assertTrue(pet.record_trick('flip'))
        self.assertEqual(pet.data.affection_exp,5)
        self.assertEqual(pet.trick_cooldowns['flip'],5)
        self.assertFalse(pet.record_trick('clone'))
        pet.advance(1.1)
        self.assertFalse(pet.record_trick('flip'))
        self.assertTrue(pet.record_trick('clone'))
        pet.advance(5)
        self.assertTrue(pet.record_trick('flip'))
        self.assertEqual(pet.data.affection_exp,10)

    def test_starving_or_locked_tricks_cannot_grant_experience(self):
        pet=PetModel()
        self.assertFalse(pet.record_trick('flip'))
        pet=PetModel(PetData(affection_level=6,hunger=0))
        for key in ('flip','clone','ball','not-trick'):
            self.assertFalse(pet.record_trick(key))
        self.assertEqual(pet.data.affection_exp,0)

    def test_no_change_to_legacy_data_fields_on_upgrade(self):
        raw={'coins':123,'hunger':0,'affection_level':2,'affection_exp':15,'stats':{'total_clicks':9}}
        data=PetData.from_dict(raw)
        self.assertEqual((data.coins,data.hunger,data.affection_level,data.affection_exp),(123,0,2,15))
        self.assertEqual(data.stats['total_clicks'],9)
        self.assertEqual(data.selected_skin_id,'default')
        self.assertFalse(data.custom_import_unlocked)

    def test_invalid_persistent_customization_fields_fail_closed(self):
        for raw in [{'selected_skin_id':'../x'},{'custom_import_unlocked':1},{'accessories':{'head':'evil'}},{'accessories':{'offset_y':float('nan')}},{'stats':{'customizations':-1}}]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                PetData.from_dict(raw)

if __name__=='__main__':
    unittest.main(verbosity=2)
