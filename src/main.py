
import os
import time
from datetime import datetime, timezone

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    scope="user-read-currently-playing",
))

# Configuration
polling_intervals = {
    0: 10,
    60_000: 30,
    900_000: 90,
}
time_margin = 2000

# Persistent state
playback_events = []
current_event = None

last_polled_at = time.monotonic()
last_playing_at = last_polled_at
last_poll_was_playing = False


def finish_event(elapsed_ms):
    global current_event

    if current_event is None:
        return

    end = current_event["playback_end"]
    duration = current_event["duration_ms"]

    if last_poll_was_playing:
        if end >= duration - elapsed_ms - time_margin:
            end = duration
        else:
            end = min(end + elapsed_ms / 2, duration)

    current_event["playback_end"] = max(
        current_event["playback_start"], int(end)
    )

    print(f"Recorded: {current_event['track_name']}")
    current_event = None


def retrieve_playback_data():
    global current_event, last_polled_at
    global last_playing_at, last_poll_was_playing

    playback = sp.currently_playing()

    observed_at = time.monotonic()
    elapsed_ms = (observed_at - last_polled_at) * 1000
    current_time = datetime.now(timezone.utc)

    is_playing = bool(playback and playback.get("is_playing"))
    item = playback.get("item") if playback else None

    track = item if item and item.get("type") == "track" else None
    track_id = track.get("id") if track else None

    # Finish the previous event if the track changed or disappeared.
    if current_event and track_id != current_event["track_id"]:
        finish_event(elapsed_ms)

    if is_playing:
        last_playing_at = observed_at

    if is_playing and track_id:
        progress = playback.get("progress_ms") or 0
        duration = track["duration_ms"]

        # Start a new playback event.
        if current_event is None:
            if last_poll_was_playing:
                start = (
                    0 if progress <= elapsed_ms + time_margin
                    else max(progress - elapsed_ms / 2, 0)
                )
            else:
                start = progress

            current_event = {
                "track_id": track_id,
                "track_name": track["name"],
                "played_at": current_time,
                "playback_start": int(start),
                "playback_end": progress,
                "duration_ms": duration,
            }
            playback_events.append(current_event)

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


# Main program loop
try:
    while True:
        retrieve_playback_data()

        inactive_ms = (time.monotonic() - last_playing_at) * 1000

        for threshold, interval in reversed(list(polling_intervals.items())):
            if inactive_ms >= threshold:
                poll_interval = interval
                break

        print(f"\tCurrently polling once every {poll_interval} seconds")
        time.sleep(poll_interval)

except KeyboardInterrupt:
    finish_event(0)
    print("\nPlayback events:")
    for event in playback_events:
        print(event)
