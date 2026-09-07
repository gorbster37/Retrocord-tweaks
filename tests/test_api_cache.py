import tempfile
import unittest
from pathlib import Path

from services.api_cache import ApiCache


class ApiCacheTests(unittest.TestCase):
    def test_distribution_round_trips_through_json(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "api_cache.json"
            cache = ApiCache(str(path))
            cache.set_distribution(42, {"10": 3})

            self.assertEqual(ApiCache(str(path)).get_distribution(42), {"10": 3})
