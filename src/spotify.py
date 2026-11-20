import json
import os
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyOAuth


DEFAULT_CACHE_PATH = ".spotify-cache"


class PersistentCacheHandler(CacheHandler):
    def __init__(self, cache_path):
        self.cache_path = Path(cache_path)

    def get_cached_token(self):
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_token_to_cache(self, token_info):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.cache_path.with_name(
            self.cache_path.name + ".tmp"
        )
        with temporary_path.open("w", encoding="utf-8") as cache_file:
            json.dump(token_info, cache_file)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, self.cache_path)


def create_cache_handler():
    cache_path = Path(
        os.getenv("SPOTIPY_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
    cache_handler = PersistentCacheHandler(cache_path)

    if not cache_path.exists():
        cache = os.getenv("SPOTIPY_CACHE")
        if cache:
            token_info = json.loads(cache)
            if not isinstance(token_info, dict):
                raise ValueError("SPOTIPY_CACHE must contain a JSON object")
            cache_handler.save_token_to_cache(token_info)

    return cache_handler


def connect():
    """Authenticate and return a Spotify client."""

    load_dotenv()

    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
        scope=(
            "user-read-recently-played "
            "user-read-currently-playing"
        ),
        cache_handler=create_cache_handler()
    ))


def get_currently_playing(sp):
    return sp.currently_playing()


def get_recently_played(sp, after):
    return sp.current_user_recently_played(limit=50, after=after)
