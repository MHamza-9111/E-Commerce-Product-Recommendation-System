import unittest
from datetime import datetime

from chatbot.support import (
    classify_return_issue,
    detect_commerce_intent,
    match_order_items,
    product_name_summary,
)


class ChatbotSupportTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {
                "id": 1,
                "order_id": 101,
                "name": "Wireless Headphones Pro",
                "brand": "SoundMax",
                "category": "Electronics",
                "order_date": datetime(2026, 8, 18),
            },
            {
                "id": 2,
                "order_id": 102,
                "name": "Running Shoes",
                "brand": "Sprint",
                "category": "Sports",
                "order_date": datetime(2026, 8, 17),
            },
        ]

    def test_damaged_headphone_typo_is_a_return(self):
        message = "my headphone order recievded damged i wanna return"
        self.assertEqual(detect_commerce_intent(message, "unknown"), "returns")
        matches = match_order_items(message, self.items)
        self.assertEqual([item["name"] for item in matches], ["Wireless Headphones Pro"])
        self.assertEqual(classify_return_issue(message), "damaged")

    def test_damage_typo_without_return_word_is_still_actionable(self):
        message = "the headphones were recievded damged"
        self.assertEqual(detect_commerce_intent(message, "unknown"), "returns")
        self.assertEqual(match_order_items(message, self.items)[0]["name"], "Wireless Headphones Pro")
        self.assertEqual(classify_return_issue(message), "damaged")

    def test_support_number_request_is_deterministic(self):
        self.assertEqual(
            detect_commerce_intent("give me the toll free support number", "unknown"),
            "contact_support",
        )

    def test_product_specific_tracking_matches_real_name(self):
        intent = detect_commerce_intent("where is my headphone order", "unknown")
        self.assertEqual(intent, "order_tracking")
        self.assertEqual(match_order_items("where is my headphone order", self.items)[0]["order_id"], 101)

    def test_order_summary_uses_names_not_only_numbers(self):
        self.assertEqual(
            product_name_summary(self.items),
            "Wireless Headphones Pro, Running Shoes",
        )

    def test_unrelated_model_intent_is_preserved(self):
        self.assertEqual(detect_commerce_intent("show laptops", "product_search"), "product_search")


if __name__ == "__main__":
    unittest.main()
