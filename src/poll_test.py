import os
import time

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth, CacheHandler

load_dotenv()

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    scope=(
        "user-read-recently-played "
        "user-read-currently-playing"
    ),
))

def retrieve_playback_data():
    playback = sp.currently_playing()
    is_playing = playback is not None and playback.get("is_playing")
    
    if is_playing:
        item = playback.get("item")
        if item.get("type") != "track":
            return
        track_name = item.get("name")
        track_duration = item.get("duration_ms")
        playback_progress = playback.get("progress_ms")
        timestamp = playback.get("timestamp")

        print(f"Track {track_name} playing at time {int(playback_progress/1000)}/{int(track_duration/1000)} seconds.")

        time_since_timestamp = time.time() - timestamp / 1000

        print(f"\tLast event {time_since_timestamp} seconds ago")
    else:
        print("No track playing")

while True:

    retrieve_playback_data()
    
    time.sleep(6)