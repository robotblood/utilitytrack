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


if __name__ == "__main__":
    unittest.main()
