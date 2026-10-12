import unittest

from rate_tracker.census_income import BINS, build, regroup

# One fake tract: 10 households in each of the 16 brackets, MOE 3 each
ROW = {"NAME": "Census Tract 1; Douglas County; Nebraska", "state": "31", "county": "055",
       "tract": "000100", "B19001_001E": "160", "B19001_001M": "20",
       **{b + "E": "10" for b in BINS}, **{b + "M": "3" for b in BINS}}


class CensusIncomeTests(unittest.TestCase):
    def test_exact_groups(self):
        t = regroup(ROW)
        self.assertEqual(t["geoid"], "31055000100")
        self.assertEqual(t["hh_under_20k"], 30)
        self.assertEqual(t["hh_75_125k"], 20)
        self.assertEqual(t["hh_125k_plus"], 30)
        self.assertAlmostEqual(t["moe_under_20k"], round((3 * 3 ** 2) ** 0.5, 1))

    def test_raw_ranges_kept(self):
        t = regroup(ROW)
        self.assertEqual(len(t["ranges"]), 16)
        self.assertEqual(sum(t["ranges"].values()), 160)

    def test_empty_tract_skipped(self):
        empty = {**ROW, "B19001_001E": "0", **{b + "E": "0" for b in BINS}}
        self.assertEqual(build([ROW, empty]), [regroup(ROW)])


if __name__ == "__main__":
    unittest.main()
