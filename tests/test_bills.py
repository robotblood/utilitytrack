import unittest

from rate_tracker.bills import annual_bill, load_tariffs, monthly_bill, observed_burden, validate_tariffs

TIERED = {
    "id": "t", "utility": "X", "service": "electric", "unit": "kWh", "verification": "verified",
    "sources": ["https://example.org"], "fixed_monthly": [{"name": "service", "amount": 10}],
    "seasons": {"summer": {"months": [6, 7, 8, 9], "blocks": [{"up_to": None, "rate": 0.20}]},
                "winter": {"months": [1, 2, 3, 4, 5, 10, 11, 12],
                           "blocks": [{"up_to": 500, "rate": 0.10}, {"up_to": None, "rate": 0.05}]}},
    "riders": [{"name": "fuel", "rate": 0.01}],
}


class BillTests(unittest.TestCase):
    def test_seed_tariffs_valid(self):
        self.assertEqual(validate_tariffs(load_tariffs()), [])

    def test_summer_flat(self):
        self.assertEqual(monthly_bill(TIERED, 1000, 7)["total"], 10 + 200 + 10)

    def test_winter_blocks(self):
        b = monthly_bill(TIERED, 800, 1)
        self.assertEqual(b["total"], 10 + 50 + 15 + 8)
        self.assertEqual(len(b["lines"]), 4)

    def test_minimum_bill(self):
        self.assertEqual(monthly_bill({**TIERED, "minimum_bill": 25}, 0, 1)["total"], 25)

    def test_annual(self):
        self.assertEqual(annual_bill(TIERED, [0] * 12), 120)
        with self.assertRaises(ValueError):
            annual_bill(TIERED, [0] * 11)

    def test_validation_catches_gaps(self):
        bad = {**TIERED, "seasons": {"summer": TIERED["seasons"]["summer"]}, "sources": []}
        errs = validate_tariffs([bad])
        self.assertTrue(any("months 1-12" in e for e in errs))
        self.assertTrue(any("no sources" in e for e in errs))

    def test_observed_burden(self):
        p = {"median_income": 24000, "median_income_owner": 60000, "median_income_renter": 15000,
             "costs": {"electricity": {"median_est": 100, "charged_hh": 75, "not_charged_hh": 25},
                       "gas": {"median_est": 50}, "water_sewer": {"median_est": 50}}}
        b = observed_burden(p)
        self.assertEqual(b["energy_burden_all"], 0.075)   # 150*12 / 24000
        self.assertEqual(b["energy_burden_all_level"], "high")
        self.assertEqual(b["energy_burden_renter_level"], "severe")
        self.assertEqual(b["utility_burden_owner"], 0.04)
        self.assertEqual(b["share_electric_not_billed"], 0.25)

    def test_observed_burden_without_costs(self):
        self.assertIsNone(observed_burden({"median_income": 50000})["energy_burden_all"])


if __name__ == "__main__":
    unittest.main()
