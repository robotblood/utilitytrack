import unittest

from rate_tracker.acs import build, median_from_bins, normalize, parse_bin, resolve
from tests.acs_fixture import LABELS, row


class AcsTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("Estimate!!Total:!!Owner occupied:"), "Total/Owner occupied")

    def test_parse_bin(self):
        self.assertEqual(parse_bin("Less than $5,000"), (0, 5000))
        self.assertEqual(parse_bin("$50 to $99"), (50, 100))
        self.assertEqual(parse_bin("$250 or more"), (250, None))
        self.assertIsNone(parse_bin("Owner occupied"))

    def test_median_interpolates(self):
        bins = {"Less than $50": 10, "$50 to $99": 10, "$100 to $149": 0}
        self.assertEqual(median_from_bins(bins), 50)
        self.assertEqual(median_from_bins({"$250 or more": 5}), 250)
        self.assertIsNone(median_from_bins({"Less than $50": 0}))

    def test_profile(self):
        [t] = build(LABELS, [row()])
        self.assertEqual(t["geoid"], "31055000100")
        self.assertEqual((t["owner_hh"], t["renter_hh"], t["renter_share"]), (60, 40, 0.4))
        self.assertEqual((t["median_income_owner"], t["median_income_renter"]), (80000, 35000))
        self.assertEqual(t["owner_hh_65plus"], 30)
        self.assertEqual(t["renter_hh_65plus"], 30)
        self.assertIsNone(t["hispanic"])  # annotation code, not a count
        self.assertEqual(t["moe"]["renter_hh"], 5)
        self.assertEqual(len(t["income_owner"]["bins"]), 11)
        elec = t["costs"]["electricity"]
        self.assertEqual((elec["charged_hh"], elec["not_charged_hh"], elec["median_est"]), (10, 10, 150))
        self.assertIn("water_sewer", t["costs"])

    def test_two_or_more_races_not_double_counted(self):
        [t] = build(LABELS, [row()])
        self.assertEqual(t["multi_nh"], 10)

    def test_empty_tract_skipped(self):
        self.assertEqual(build(LABELS, [row(households=0, renters=0)]), [])

    def test_layout_change_fails_loudly(self):
        broken = {**LABELS, "B25003": {"B25003_001E": "Estimate!!Total:"}}
        with self.assertRaisesRegex(ValueError, "owner_hh"):
            resolve(broken)


if __name__ == "__main__":
    unittest.main()
