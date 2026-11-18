import os
import json

import spotipy
from spotipy.oauth2 import SpotifyOAuth, CacheHandler
from dotenv import load_dotenv

load_dotenv()

class EnvironmentCacheHandler(CacheHandler):
    def get_cached_token(self):
        cache = os.getenv("SPOTIPY_CACHE")
        return json.loads(cache) if cache else None

    def save_token_to_cache(self, token_info):
        pass

def connect():
    """Authenticate and return a Spotify client."""

    load_dotenv()

    # Use custom environment handler only if SPOTIPY_CACHE
    # exists in the environment variables
    cache = os.getenv("SPOTIPY_CACHE")
    cache_handler = (EnvironmentCacheHandler() if cache else None)

    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
        scope=(
            "user-read-recently-played "
            "user-read-currently-playing"
        ),
        cache_handler=cache_handler
    ))

def get_currently_playing(sp):
    return sp.currently_playing()
