import time
from datetime import datetime, timezone

import spotify
import database

# Configuration
polling_intervals = {
    0: 10,
    60_000: 30,
    900_000: 90,
}
time_margin = 2000

current_event = None

last_polled_at = time.monotonic()
last_playing_at = last_polled_at
last_poll_was_playing = False


def finish_event(elapsed_ms, db):
    global current_event

    if current_event is None:
        return

    event = current_event
    end = event["playback_end"]
    duration = event["duration_ms"]

    if last_poll_was_playing:
        if end >= duration - elapsed_ms - time_margin:
            end = duration
        else:
            end = min(end + elapsed_ms / 2, duration)

    event["playback_end"] = max(event["playback_start"], int(end))

    update_database(db, event)

    print(f"Recorded: {event['track_name']}")
    current_event = None

def update_database(db, event):
    db.insert_track(event["track"])
    db.insert_event(
        event["track_id"],
        event["started_at"],
        event["playback_start"],
        event["playback_end"]
    )
    db.commit()

def retrieve_playback_data(sp, db):
    global current_event, last_polled_at
    global last_playing_at, last_poll_was_playing

    playback = spotify.get_currently_playing(sp)

    observed_at = time.monotonic()
    elapsed_ms = (observed_at - last_polled_at) * 1000
    current_time = datetime.now(timezone.utc)

    is_playing = bool(playback and playback.get("is_playing"))
    item = playback.get("item") if playback else None

    track = item if item and item.get("type") == "track" else None
    track_id = track.get("id") if track else None

    # Finish the previous event if the track changed or disappeared.
    if current_event and track_id != current_event["track_id"]:
        finish_event(elapsed_ms, db)

    if is_playing:
        last_playing_at = observed_at

    if is_playing and track_id:
        progress = playback.get("progress_ms") or 0
        duration = track["duration_ms"]

        # Start a new playback event.
        if current_event is None:
            if not last_poll_was_playing:
                start = progress
            elif progress <= elapsed_ms + time_margin:
                start = 0
            else:
                start = max(progress - elapsed_ms / 2, 0)

            current_event = {
                "track_id": track_id,
                "track_name": track["name"],
                "track": track,
                "started_at": current_time,
                "playback_start": int(start),
                "playback_end": progress,
                "duration_ms": duration,
            }

        else:
            current_event["playback_end"] = progress

        print(
            f"Playing: {track['name']} "
            f"({int(progress / 1000)}/{int(duration / 1000)} seconds)"
        )

        timestamp = playback.get("timestamp")
        if timestamp is not None:
            age = time.time() - timestamp / 1000
            print(f"\tLast playback event: {age:.1f}s ago")

    elif item:
        print(f"Paused: {item.get('name', 'Unknown track')}")
    else:
        print("No track playing")

    last_poll_was_playing = is_playing
    last_polled_at = observed_at

def main():

    try:
        print("Connecting to Spotify... ")
        sp = spotify.connect()
        print("Connecting to Database... ")
        db = database.Database()
    except Exception as e:
        print(f"Error: {e}")
        return

    try:
        while True:
            retrieve_playback_data(sp, db)

            inactive_ms = (time.monotonic() - last_playing_at) * 1000

            for threshold, interval in reversed(list(polling_intervals.items())):
                if inactive_ms >= threshold:
                    poll_interval = interval
                    break

            print(f"\tCurrently polling once every {poll_interval} seconds")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        if current_event is not None:
            elapsed_ms = (time.monotonic() - last_polled_at) * 1000
            finish_event(elapsed_ms, db)
    finally:
        db.close()

if __name__ == "__main__":
    main()