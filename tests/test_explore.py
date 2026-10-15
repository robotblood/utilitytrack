import unittest
from datetime import date

from rate_tracker.bills import load_tariffs
from rate_tracker.explore import (
    as_minimum_bill,
    bill_parts,
    cost_is_floor,
    headline_change,
    increase_by_group,
    map_class,
    next_decisions,
    nth_weekday,
    short_name,
    under_the_line,
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


def tract(geoid, income, elec, gas=0.0, households=100, renter_bins=None, level="ok"):
    """A web-layer tract profile: just the fields the tract views read."""
    return {"geoid": geoid, "name": f"Census Tract {geoid[-3:]}; Douglas County; Nebraska",
            "county": "Douglas", "median_income": income, "households": households,
            "income_renter": {"bins": renter_bins or {}}, "income_owner": {"bins": {}},
            "costs": {"electricity": {"median_est": elec, "bins": {"$250 or more": 1}},
                      "gas": {"median_est": gas, "bins": {"$25 to $49": 1, "$150 or more": 1}}},
            "burden": {"monthly_energy_cost": elec + gas, "energy_burden_all_level": level}}


class TractViewTests(unittest.TestCase):
    def test_map_class_and_names(self):
        breaks = [0.03, 0.06]
        self.assertEqual([map_class(v, breaks) for v in (0.01, 0.03, 0.031, 0.2)], [0, 0, 1, 2])
        self.assertIsNone(map_class(None, breaks))
        self.assertEqual(short_name(tract("31055000200", 1, 1)), "Tract 200, Douglas")

    def test_gas_in_top_bin_is_a_floor(self):
        self.assertTrue(cost_is_floor(tract("1", 1, 100, gas=150), "gas"))
        self.assertFalse(cost_is_floor(tract("1", 1, 100, gas=40), "gas"))

    def test_under_the_line_spreads_bins(self):
        # $100/mo -> 6% line at $20,000 and 10% line at $12,000
        bins = {"Less than $5,000": 10, "$10,000 to $14,999": 10, "$25,000 to $34,999": 10}
        r = under_the_line([tract("31055000100", 30000, 100, renter_bins=bins, level="high"),
                            tract("31055000200", 90000, 100, renter_bins={"$150,000 or more": 50})])
        self.assertEqual(r["tenure"]["renter"], {"households": 80, "under_6": 20, "under_10": 14})
        self.assertEqual(r["in_flagged"]["under_6"], 20)
        self.assertEqual((r["flagged_tracts"], r["lines"][0]["line"]), (1, 20000))

    def test_increase_weighs_more_at_the_bottom(self):
        a = action([{"customer_class": "residential", "metric": "avg_rate_change_pct", "value": 10}])
        groups = increase_by_group([tract("1", 20000, 100), tract("2", 100000, 150)], a, groups=2)
        self.assertEqual([g["added"] for g in groups], [120.0, 180.0])   # $100 and $150 a month, +10%
        self.assertEqual([g["share"] for g in groups], [0.006, 0.0018])


if __name__ == "__main__":
    unittest.main()
