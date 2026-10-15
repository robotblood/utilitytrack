import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from rate_tracker.web.app import INCOME_FILE, create_app
except ImportError:  # web extra not installed; core tests still run
    TestClient = None

from rate_tracker.store import DATA_DIR


@unittest.skipIf(TestClient is None, 'web extra not installed (pip install -e ".[dev]")')
class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app())

    def test_timeline_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("oppd-2025", r.text)

    def test_timeline_filter(self):
        r = self.client.get("/", params={"utility": "MUD", "service": "gas"})
        self.assertNotIn("/actions/oppd-", r.text)

    def test_action_page_and_404(self):
        self.assertEqual(self.client.get("/actions/oppd-2025").status_code, 200)
        self.assertEqual(self.client.get("/actions/nope").status_code, 404)

    def test_api_action_includes_drivers(self):
        body = self.client.get("/api/actions/oppd-2025").json()
        self.assertEqual(len(body["drivers"]), len(body["driver_ids"]))

    def test_neighborhoods_empty_state(self):
        r = self.client.get("/neighborhoods")
        self.assertEqual(r.status_code, 200)
        self.assertIn("acs-profiles", r.text)

    def test_bill_page_and_api(self):
        r = self.client.get("/bill", params={"usage": 1000, "month": 7, "income": 30000})
        self.assertEqual(r.status_code, 200)
        self.assertIn("needs verification", r.text)
        body = self.client.get("/api/bill/oppd-rate-110-2026", params={"usage": 0, "month": 1}).json()
        self.assertEqual(body["total"], 30.0)
        self.assertEqual(self.client.get("/api/bill/oppd-rate-110-2026",
                                         params={"usage": 1, "month": 13}).status_code, 422)

    def test_explore_pages(self):
        for path in ("/explore", "/explore/fixed-charge", "/explore/next", "/static/explore.css",
                     "/static/explore.js", "/explore/map", "/explore/increase"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertIn("minimum bill", self.client.get("/explore/fixed-charge").text)
        self.assertIn("third Thursday of December", self.client.get("/explore/next").text)

    def test_income_page_without_data(self):
        r = self.client.get("/income")
        self.assertEqual(r.status_code, 200)
        self.assertIn("census-income", r.text)


@unittest.skipIf(TestClient is None, "web extra not installed")
class WebIncomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for f in DATA_DIR.glob("*.json"):
            shutil.copy(f, self.tmp)
        tract = {"geoid": "31055000100", "name": "Tract 1", "county": "Douglas", "households": 100,
                 "share_under_20k": 0.25, "share_125k_plus": None}
        (self.tmp / INCOME_FILE).write_text(json.dumps(
            {"source": "test", "groups": ["under_20k", "125k_plus"], "tracts": [tract]}))
        self.client = TestClient(create_app(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_income_table(self):
        r = self.client.get("/income")
        self.assertIn("31055000100", r.text)
        self.assertIn("25%", r.text)
        self.assertEqual(self.client.get("/api/income/tracts").json()["tracts"][0]["county"], "Douglas")


@unittest.skipIf(TestClient is None, "web extra not installed")
class WebNeighborhoodTests(unittest.TestCase):
    def setUp(self):
        from rate_tracker.acs import build
        from rate_tracker.bills import observed_burden
        from rate_tracker.geo import rollup
        from tests.acs_fixture import LABELS, row
        self.tmp = Path(tempfile.mkdtemp())
        for f in DATA_DIR.glob("*.json"):
            shutil.copy(f, self.tmp)
        tracts = build(LABELS, [row("000100", renters=40), row("000200", renters=80)])
        (self.tmp / "acs_tracts.json").write_text(json.dumps({"source": "test", "tracts": tracts}))
        xw = [{"geoid": "31055000100", "area": "Benson", "weight": 1.0},
              {"geoid": "31055000200", "area": "Dundee", "weight": 1.0}]
        areas = [{**a, "burden": observed_burden(a)} for a in rollup(tracts, xw)]
        (self.tmp / "areas_neighborhoods.json").write_text(json.dumps({"areas": areas}))
        self.client = TestClient(create_app(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_layers(self):
        self.assertEqual(self.client.get("/healthz").json()["layers"], ["neighborhoods", "tracts"])

    def test_neighborhood_table(self):
        r = self.client.get("/neighborhoods", params={"layer": "neighborhoods", "sort": "renter_share"})
        self.assertEqual(r.status_code, 200)
        self.assertLess(r.text.index("Dundee"), r.text.index("Benson"))  # 80% renters sorts first
        self.assertIn("80.0%", r.text)

    def test_explore_tract_views(self):
        for path in ("/explore", "/explore/cost-vs-income", "/explore/increase", "/explore/six-percent-line"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertIn("Tract 000200, Douglas", self.client.get("/explore/six-percent-line").text)
        # the tmp data dir has no boundaries, so the map page says where to get them
        self.assertIn("cb_2024_31_tract_500k.zip", self.client.get("/explore/map").text)

    def test_tract_layer_and_api(self):
        self.assertIn("31055000100", self.client.get("/neighborhoods", params={"layer": "tracts"}).text)
        areas = self.client.get("/api/areas/neighborhoods").json()
        self.assertIn("energy_burden_renter", areas[0]["burden"])
        self.assertEqual(self.client.get("/api/areas/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
