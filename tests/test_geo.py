import json
import tempfile
import unittest
from pathlib import Path

try:
    import shapely  # noqa: F401
except ImportError:
    shapely = None

from rate_tracker.acs import build
from tests.acs_fixture import LABELS, row


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def fc(features):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": props, "geometry": geom} for props, geom in features]}


@unittest.skipIf(shapely is None, 'geo extra not installed (pip install -e ".[geo]")')
class GeoTests(unittest.TestCase):
    def setUp(self):
        from rate_tracker.geo import load_features
        self.tmp = Path(tempfile.mkdtemp())
        # tract A is x 0..1, tract B is x 1..2; "West" covers A's left half, "East" the rest
        (self.tmp / "tracts.geojson").write_text(json.dumps(fc([
            ({"GEOID": "31055000100", "COUNTYFP": "055"}, square(0, 0, 1, 1)),
            ({"GEOID": "31055000200", "COUNTYFP": "055"}, square(1, 0, 2, 1)),
            ({"GEOID": "31001000100", "COUNTYFP": "001"}, square(5, 5, 6, 6))])))
        (self.tmp / "hoods.geojson").write_text(json.dumps(fc([
            ({"NAME": "West"}, square(0, 0, 0.5, 1)),
            ({"NAME": "East"}, square(0.5, 0, 2, 1))])))
        self.tracts = load_features(self.tmp / "tracts.geojson", "GEOID", keep={"COUNTYFP": {"055"}})
        self.hoods = load_features(self.tmp / "hoods.geojson", "NAME")

    def test_county_filter(self):
        self.assertEqual(len(self.tracts), 2)

    def test_missing_id_field(self):
        from rate_tracker.geo import load_features
        with self.assertRaisesRegex(KeyError, "fields are"):
            load_features(self.tmp / "hoods.geojson", "NOPE")

    def test_crosswalk_weights(self):
        from rate_tracker.geo import crosswalk
        xw = {(r["geoid"], r["area"]): r["weight"] for r in crosswalk(self.tracts, self.hoods)}
        self.assertEqual(xw, {("31055000100", "West"): 0.5, ("31055000100", "East"): 0.5,
                              ("31055000200", "East"): 1.0})

    def test_rollup_splits_counts(self):
        from rate_tracker.geo import crosswalk, rollup
        profiles = build(LABELS, [row("000100", renters=40), row("000200", renters=80)])
        areas = {a["area"]: a for a in rollup(profiles, crosswalk(self.tracts, self.hoods))}
        self.assertEqual(areas["West"]["renter_hh"], 20)
        self.assertEqual(areas["East"]["renter_hh"], 100)
        self.assertEqual(areas["East"]["households"], 150)
        self.assertEqual(areas["East"]["renter_share"], round(100 / 150, 4))
        self.assertEqual(areas["East"]["costs"]["electricity"]["median_est"], 150)
        self.assertEqual(areas["West"]["median_income_hhwavg"], 60000)


if __name__ == "__main__":
    unittest.main()
