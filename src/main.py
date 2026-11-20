"""
Aplication main entry point
"""

import os
import signal
import time

import database
import spotify
from playback import PlaybackTracker
from recent_history import RecentHistory
from spotipy.exceptions import SpotifyException, SpotifyOauthError


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


def handle_sigterm(signum, frame):
    del frame
    raise KeyboardInterrupt(f"Received signal {signum}")


def authorization_error_message():
    cache_path = os.getenv(
        "SPOTIPY_CACHE_PATH",
        spotify.DEFAULT_CACHE_PATH
    )
    return (
        "Spotify authorization failed. Reauthorize locally, update "
        f"SPOTIPY_CACHE if used, and replace the persisted cache file "
        f"at {cache_path}."
    )


def announce_polling_interval_change(previous_interval, interval):
    if interval != previous_interval:
        print(
            "Polling rate changed. "
            f"Now polling once every {interval} seconds."
        )
    return interval


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

    signal.signal(signal.SIGTERM, handle_sigterm)

    last_interval = POLLING_INTERVALS_MS[0]
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
                        authorization_error_message()
                    ) from error
                raise
            except SpotifyOauthError as error:
                raise RuntimeError(
                    authorization_error_message()
                ) from error

            # Wait until next API call
            inactive_ms = (
                time.monotonic() - tracker.last_playing_at
            ) * 1000 # Time since last playing a track
            interval = polling_interval(inactive_ms)
            last_interval = announce_polling_interval_change(
                last_interval, interval
            )
            time.sleep(interval)

    except KeyboardInterrupt:
        tracker.close(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
