import unittest

from rate_tracker.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store.load()

    def test_seed_data_is_consistent(self):
        self.assertEqual(self.store.validate(), [])

    def test_every_action_has_a_driver(self):
        missing = [a["id"] for a in self.store.rate_actions if not a.get("driver_ids")]
        self.assertEqual(missing, [])

    def test_broken_link_is_caught(self):
        self.store.rate_actions[0]["driver_ids"].append("does-not-exist")
        self.assertTrue(any("missing driver" in e for e in self.store.validate()))


if __name__ == "__main__":
    unittest.main()
