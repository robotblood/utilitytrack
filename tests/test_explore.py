import unittest
from datetime import date

from rate_tracker.bills import load_tariffs
from rate_tracker.explore import (
    as_minimum_bill,
    bill_parts,
    headline_change,
    next_decisions,
    nth_weekday,
    vote_pattern,
)
from rate_tracker.store import Store


def action(changes, **kw):
    return {"id": "x", "utility": "OPPD", "service": "electric", "effective_date": "2025-01-01",
            "status": "approved", "verification": "verified", "changes": changes, **kw}


class ExploreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store.load()
        self.tariff = load_tariffs()[0]

    def test_headline_prefers_residential_then_bill(self):
        a = action([{"customer_class": "all", "metric": "avg_bill_change_pct", "value": 2.9},
                    {"customer_class": "residential", "metric": "avg_rate_change_pct", "value": 2.5},
                    {"customer_class": "residential", "metric": "avg_bill_change_pct", "value": 4.7}])
        self.assertEqual(headline_change(a)["value"], 4.7)
        self.assertEqual(headline_change(a)["label"], "residential bill")
        self.assertIsNone(headline_change(action([{"customer_class": "residential",
                                                   "metric": "commodity_charge_change_pct", "value": 1}])))

    def test_fixed_charge_two_readings(self):
        fixed = bill_parts(self.tariff, 1000, 1)
        minimum = bill_parts(as_minimum_bill(self.tariff), 1000, 1)
        self.assertEqual(fixed["fixed"], 30.0)
        self.assertEqual(minimum["fixed"], 0)
        self.assertAlmostEqual(fixed["total"] - minimum["total"], 30.0, places=2)
        self.assertEqual(bill_parts(as_minimum_bill(self.tariff), 100, 1)["total"], 30.0)

    def test_vote_pattern_and_projection(self):
        self.assertEqual(nth_weekday(2026, 12, 3, 3), date(2026, 12, 17))
        rule = vote_pattern(self.store, "OPPD")["rule"]
        self.assertEqual(rule["text"], "third Thursday of December")
        oppd = lambda today: next(u for u in next_decisions(self.store, today)
                                  if u["utility"]["code"] == "OPPD")
        before = oppd(date(2026, 10, 12))
        self.assertEqual((before["projected"], before["days"]), (date(2026, 12, 17), 66))
        self.assertEqual(oppd(date(2026, 12, 18))["projected"], date(2027, 12, 16))

    def test_no_pattern_from_mismatched_votes(self):
        self.store.rate_actions[1]["approved_date"] = "2022-12-14"  # a Wednesday, breaking the run
        self.assertIsNone(vote_pattern(self.store, "OPPD")["rule"])


if __name__ == "__main__":
    unittest.main()
