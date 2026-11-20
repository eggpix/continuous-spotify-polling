"""
Aplication main entry point
"""

import time

import database
import spotify
from playback import PlaybackTracker
from recent_history import RecentHistory
from spotipy.exceptions import SpotifyException


POLLING_INTERVALS_MS = {
    0: 20,
    60_000: 60,
    180_000: 180,
}


def polling_interval(inactive_ms):
    for threshold, interval in reversed(POLLING_INTERVALS_MS.items()):
        if inactive_ms >= threshold:
            return interval
    raise RuntimeError("No polling interval configured for this state")


def rate_limit_retry_after(error):
    retry_after = error.headers.get("Retry-After")
    try:
        return max(0, int(retry_after))
    except (TypeError, ValueError):
        print("Spotify did not provide a valid Retry-After; waiting 60 seconds")
        return 60


def main():
    tracker = PlaybackTracker(RecentHistory())

    # Initialize Spotify API and database connection
    try:
        print("Connecting to Spotify... ")
        sp = spotify.connect()
        print("Connecting to Database... ")
        db = database.Database()
    except Exception as error:
        print(f"Error: {error}")
        return

    try:
        # Main loop for API polling
        while True:
            # Poll the Spotify API
            try:
                tracker.poll(sp, db)
            except SpotifyException as error:
                if error.http_status == 429:
                    delay = rate_limit_retry_after(error)
                    print(f"Spotify rate limited; retrying in {delay} seconds")
                    time.sleep(delay)
                    continue
                if error.http_status == 401:
                    raise RuntimeError(
                        "Spotify authorization failed. Check the persisted "
                        "token cache and reauthorize locally if needed."
                    ) from error
                raise

            # Wait until next API call
            inactive_ms = (
                time.monotonic() - tracker.last_playing_at
            ) * 1000 # Time since last playing a track
            interval = polling_interval(inactive_ms)
            time.sleep(interval)

    except KeyboardInterrupt:
        tracker.close(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
