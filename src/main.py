import time

import database
import spotify
from playback import PlaybackTracker
from recent_history import RecentHistory


POLLING_INTERVALS_MS = {
    0: 10,
    60_000: 30,
    900_000: 90,
}


def polling_interval(inactive_ms):
    for threshold, interval in reversed(POLLING_INTERVALS_MS.items()):
        if inactive_ms >= threshold:
            return interval
    raise RuntimeError("No polling interval configured for this state")


def main():
    tracker = PlaybackTracker(RecentHistory())

    try:
        print("Connecting to Spotify... ")
        sp = spotify.connect()
        print("Connecting to Database... ")
        db = database.Database()
    except Exception as error:
        print(f"Error: {error}")
        return

    try:
        while True:
            tracker.poll(sp, db)

            inactive_ms = (
                time.monotonic() - tracker.last_playing_at
            ) * 1000
            interval = polling_interval(inactive_ms)
            print(f"\tCurrently polling once every {interval} seconds")
            time.sleep(interval)

    except KeyboardInterrupt:
        tracker.close(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
