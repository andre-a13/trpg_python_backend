import unittest
from pathlib import Path
import hashlib
import json
from app.hearthstone_catalog import CARD_SET_NAMES_FR, collectible_cards, find_collectible_card, search_collectible_cards, collectible_card_sets
from app.schemas.hearthstone import HearthstoneCardResponse

class TestHearthstoneCatalogSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog_path = Path(__file__).resolve().parents[1] / "app/data/cards.frFR.json"
        with cls.catalog_path.open("rb") as f:
            cls.raw_bytes = f.read()
        cls.expected_sha256 = "7268dec7b7e45fccfde087ec615ca9f0dabaeeaebbde9eac16c2f763f2bbcdc3"

    def test_catalog_file_sha256(self):
        actual_sha256 = hashlib.sha256(self.raw_bytes).hexdigest()
        self.assertEqual(actual_sha256, self.expected_sha256)

    def test_raw_snapshot_shape_and_unique_ids(self):
        cards = json.loads(self.raw_bytes)
        self.assertIsInstance(cards, list)
        self.assertEqual(len(cards), 36390)
        ids = [card["id"] for card in cards]
        self.assertTrue(all(isinstance(card_id, str) and card_id for card_id in ids))
        self.assertEqual(len(set(ids)), len(ids))

    def test_collectible_cards_count_and_validation(self):
        cards = collectible_cards()
        self.assertEqual(len(cards), 8328)
        for card in cards:
            HearthstoneCardResponse.model_validate(card)

    def test_find_collectible_card_cata_484(self):
        card = find_collectible_card("CATA_484")
        self.assertIsNotNone(card)
        self.assertEqual(card["name"], "Dragonnet de Berceau-de-l’Hiver")
        self.assertEqual(card["cardSet"], "CATACLYSM")
        self.assertEqual(card["illustrationUrl"], "https://art.hearthstonejson.com/v1/512x/CATA_484.webp")

    def test_search_collectible_cards_cataclysm(self):
        results_page1, total = search_collectible_cards("", 1, 100, "CATACLYSM")
        self.assertEqual(total, 164)
        self.assertEqual(len(results_page1), 100)
        for card in results_page1:
            self.assertEqual(card["cardSet"], "CATACLYSM")

        results_page2, total2 = search_collectible_cards("", 2, 100, "CATACLYSM")
        self.assertEqual(total2, 164)
        self.assertEqual(len(results_page2), 64)
        self.assertEqual(set(c["id"] for c in results_page1) & set(c["id"] for c in results_page2), set())

    def test_search_dragonnet_by_name(self):
        cards, total = search_collectible_cards("berceau", 1, 100, "CATACLYSM")
        self.assertGreater(total, 0)
        self.assertIn("CATA_484", {card["id"] for card in cards})

    def test_search_collectible_cards_tgt(self):
        results, total = search_collectible_cards("", 1, 100, "TGT")
        self.assertEqual(total, 132)

    def test_search_collectible_cards_unknown_card(self):
        card = find_collectible_card("UNKNOWN_99999")
        self.assertIsNone(card)

    def test_search_collectible_cards_unknown_set(self):
        results, total = search_collectible_cards("", 1, 100, "NONEXISTENT_SET")
        self.assertEqual(total, 0)
        self.assertEqual(len(results), 0)

    def test_collectible_card_sets_count_and_sum(self):
        sets = collectible_card_sets()
        self.assertEqual(len(sets), 49)
        total_cards = sum(s["cardCount"] for s in sets)
        self.assertEqual(total_cards, 8328)
        for set_info in sets:
            self.assertIn(set_info["code"], CARD_SET_NAMES_FR)
            self.assertTrue(set_info["name"], f"Set code {set_info['code']} has empty name")
