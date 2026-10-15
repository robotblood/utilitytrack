import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rate_tracker.env import load_env


class LoadEnvTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / ".env"
        path.write_text(text)
        return path

    def test_reads_keys_skips_comments(self):
        path = self.write("# comment\n\nCENSUS_API_KEY=abc123\nexport OTHER='quoted'\nnot a pair\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            load_env(path)
            self.assertEqual(os.environ["CENSUS_API_KEY"], "abc123")
            self.assertEqual(os.environ["OTHER"], "quoted")
            self.assertEqual(len(os.environ), 2)

    def test_shell_wins(self):
        path = self.write("CENSUS_API_KEY=from_file\n")
        with mock.patch.dict(os.environ, {"CENSUS_API_KEY": "from_shell"}, clear=True):
            load_env(path)
            self.assertEqual(os.environ["CENSUS_API_KEY"], "from_shell")

    def test_missing_file(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            load_env(Path(tempfile.mkdtemp()) / ".env")
            self.assertEqual(dict(os.environ), {})


if __name__ == "__main__":
    unittest.main()
