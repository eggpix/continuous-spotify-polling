import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import spotify


class PersistentCacheHandlerTests(unittest.TestCase):
    def test_environment_cache_bootstraps_and_refreshed_token_persists(self):
        initial_token = {
            "access_token": "initial-access",
            "refresh_token": "initial-refresh",
            "expires_at": 1,
        }
        refreshed_token = {
            "access_token": "refreshed-access",
            "refresh_token": "rotated-refresh",
            "expires_at": 2,
        }

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "nested" / "spotify-cache.json"
            environment = {
                "SPOTIPY_CACHE": json.dumps(initial_token),
                "SPOTIPY_CACHE_PATH": str(cache_path),
            }
            with patch.dict(os.environ, environment, clear=False):
                handler = spotify.create_cache_handler()
                self.assertEqual(handler.get_cached_token(), initial_token)

                handler.save_token_to_cache(refreshed_token)

                next_handler = spotify.create_cache_handler()
                self.assertEqual(
                    next_handler.get_cached_token(), refreshed_token
                )


if __name__ == "__main__":
    unittest.main()
