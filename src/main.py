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
scrub_threshold_ms = 1000
missing_track_grace_ms = 120_000
recently_played_overlap_ms = 120_000
recent_event_match_window_ms = 10_000

current_event = None

last_polled_at = time.monotonic()
last_polled_wallclock_ms = int(time.time() * 1000)
recently_played_session_start_ms = last_polled_wallclock_ms
last_playing_at = last_polled_at
last_poll_was_playing = False
recently_played_cursor_ms = last_polled_wallclock_ms
recently_played_seen = {}


def timestamp_to_datetime(timestamp, fallback):
    if timestamp is None:
        return fallback
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc)


def datetime_to_timestamp(value):
    return int(value.timestamp() * 1000)


def update_event_from_playback(event, track, progress, timestamp):
    event["track"] = track
    if progress is not None:
        event["playback_end"] = progress
        event["last_progress_ms"] = progress
    if timestamp is not None:
        event["last_timestamp"] = timestamp
    event["missing_since"] = None


def restarted_event_start(progress, timestamp, observed_at_ms):
    if timestamp is None:
        return progress
    elapsed_since_change = max(0, observed_at_ms - timestamp)
    return max(0, int(progress - elapsed_since_change))


def playback_was_restarted(event, progress, timestamp, observed_at_ms):
    previous_progress = event["last_progress_ms"]
    previous_timestamp = event["last_timestamp"]

    if progress is None or previous_progress is None:
        return False

    timestamp_changed = (
        timestamp is None
        or previous_timestamp is None
        or timestamp > previous_timestamp
    )
    if progress < previous_progress - scrub_threshold_ms:
        return timestamp_changed

    if (
        timestamp is not None
        and previous_timestamp is not None
        and timestamp > previous_timestamp
        and timestamp >= last_polled_wallclock_ms - time_margin
    ):
        elapsed_since_change = observed_at_ms - timestamp
        return abs(elapsed_since_change - progress) <= time_margin

    return False


def recover_recently_played(sp, db, playback, previous_event=None):
    global recently_played_cursor_ms, recently_played_seen

    response = spotify.get_recently_played(
        sp,
        after=max(0, recently_played_cursor_ms - recently_played_overlap_ms)
    )
    items = response.get("items", [])
    dated_items = []

    for item in items:
        played_at = datetime.fromisoformat(
            item["played_at"].replace("Z", "+00:00")
        )
        if played_at.tzinfo is None:
            played_at = played_at.replace(tzinfo=timezone.utc)
        dated_items.append((datetime_to_timestamp(played_at), item, played_at))

    dated_items.sort(key=lambda result: result[0])

    skip_indexes = set()
    if previous_event is not None:
        matching = [
            (index, result)
            for index, result in enumerate(dated_items)
            if result[1].get("track", {}).get("id")
            == previous_event["track_id"]
        ]
        if matching:
            previous_started_at = datetime_to_timestamp(
                previous_event["started_at"]
            )
            index, _ = min(
                matching,
                key=lambda match: abs(match[1][0] - previous_started_at)
            )
            if abs(dated_items[index][0] - previous_started_at) <= (
                recent_event_match_window_ms
            ):
                skip_indexes.add(index)

    playback_item = playback.get("item") if playback else None
    playback_track_id = (
        playback_item.get("id")
        if playback_item and playback_item.get("type") == "track"
        else None
    )
    if playback_track_id:
        matching = [
            index
            for index, result in enumerate(dated_items)
            if result[1].get("track", {}).get("id") == playback_track_id
        ]
        if matching:
            timestamp = playback.get("timestamp")
            if timestamp is None:
                skip_indexes.add(matching[-1])
            else:
                closest = min(
                    matching,
                    key=lambda index: abs(dated_items[index][0] - timestamp)
                )
                if (
                    abs(dated_items[closest][0] - timestamp)
                    <= recent_event_match_window_ms
                ):
                    skip_indexes.add(closest)

    for index, (played_at_ms, item, played_at) in enumerate(dated_items):
        track = item.get("track") or {}
        track_id = track.get("id")
        key = (track_id, played_at_ms)

        if played_at_ms < recently_played_session_start_ms:
            continue
        if key in recently_played_seen:
            continue
        recently_played_seen[key] = played_at_ms
        recently_played_cursor_ms = max(
            recently_played_cursor_ms, played_at_ms
        )

        if index in skip_indexes:
            continue
        if track.get("type") != "track" or not track_id:
            continue

        event = {
            "track_id": track_id,
            "track_name": track["name"],
            "track": track,
            "started_at": played_at,
            "playback_start": None,
            "playback_end": None,
            "duration_ms": track["duration_ms"],
        }
        update_database(db, event)
        print(f"Recovered from history: {event['track_name']}")

    cutoff_ms = recently_played_cursor_ms - recently_played_overlap_ms
    recently_played_seen = {
        key: timestamp
        for key, timestamp in recently_played_seen.items()
        if timestamp >= cutoff_ms
    }


def finish_event(elapsed_ms, db):
    global current_event

    if current_event is None:
        return

    event = current_event
    end = event["playback_end"]
    duration = event["duration_ms"]

    if end is not None and last_poll_was_playing:
        if end >= duration - elapsed_ms - time_margin:
            end = duration
        else:
            end = min(end + elapsed_ms / 2, duration)

    if end is not None:
        start = event["playback_start"] or 0
        event["playback_end"] = max(start, int(end))

    update_database(db, event)
    started_at_ms = datetime_to_timestamp(event["started_at"])
    recently_played_seen[(event["track_id"], started_at_ms)] = started_at_ms

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
    global current_event, last_polled_at, last_polled_wallclock_ms
    global recently_played_cursor_ms
    global last_playing_at, last_poll_was_playing

    playback = spotify.get_currently_playing(sp)

    observed_at = time.monotonic()
    elapsed_ms = (observed_at - last_polled_at) * 1000
    current_time = datetime.now(timezone.utc)
    observed_at_ms = int(time.time() * 1000)

    is_playing = bool(playback and playback.get("is_playing"))
    item = playback.get("item") if playback else None

    track = item if item and item.get("type") == "track" else None
    track_id = track.get("id") if track else None
    progress = playback.get("progress_ms") if playback else None
    timestamp = playback.get("timestamp") if playback else None
    recently_played_checked = False

    previous_event = current_event
    restarted = (
        current_event is not None
        and track_id == current_event["track_id"]
        and playback_was_restarted(
            current_event, progress, timestamp, observed_at_ms
        )
    )
    missing_expired = (
        current_event is not None
        and current_event["missing_since"] is not None
        and (observed_at - current_event["missing_since"]) * 1000
        >= missing_track_grace_ms
    )
    track_changed = (
        current_event is not None
        and track_id is not None
        and track_id != current_event["track_id"]
    )

    if track_changed or restarted or missing_expired:
        finish_event(0 if restarted or missing_expired else elapsed_ms, db)
        recover_recently_played(sp, db, playback, previous_event)
        recently_played_checked = True

    if is_playing:
        last_playing_at = observed_at

    if is_playing and track_id:
        duration = track["duration_ms"]

        if current_event is None:
            if restarted and progress is not None:
                start = restarted_event_start(
                    progress, timestamp, observed_at_ms
                )
            elif (
                timestamp is not None
                and timestamp >= last_polled_wallclock_ms - time_margin
                and progress is not None
                and abs((observed_at_ms - timestamp) - progress) <= time_margin
            ):
                start = 0
            elif not last_poll_was_playing and progress is not None:
                start = progress
            elif progress is None:
                start = None
            elif progress <= elapsed_ms + time_margin:
                start = 0
            else:
                start = max(progress - elapsed_ms / 2, 0)

            current_event = {
                "track_id": track_id,
                "track_name": track["name"],
                "track": track,
                "started_at": timestamp_to_datetime(timestamp, current_time),
                "playback_start": int(start) if start is not None else None,
                "playback_end": progress,
                "duration_ms": duration,
                "last_progress_ms": progress,
                "last_timestamp": timestamp,
                "missing_since": None,
            }
            if previous_event is None:
                recover_recently_played(sp, db, playback, current_event)
                recently_played_checked = True
        else:
            update_event_from_playback(
                current_event, track, progress, timestamp
            )

        print(
            f"Playing: {track['name']} "
            f"({int(progress / 1000) if progress is not None else '?'}"
            f"/{int(duration / 1000)} seconds)"
        )

        if timestamp is not None:
            age = time.time() - timestamp / 1000
            print(f"\tLast playback event: {age:.1f}s ago")

    elif track_id and current_event is not None:
        update_event_from_playback(
            current_event, track, progress, timestamp
        )
        print(f"Paused: {track['name']}")

    elif item:
        print(f"Paused: {item.get('name', 'Unknown track')}")
    else:
        print("No track playing")
    if track_id is None and not recently_played_checked:
        if current_event is not None and current_event["missing_since"] is None:
            current_event["missing_since"] = observed_at
        recover_recently_played(sp, db, playback, current_event)

    last_poll_was_playing = is_playing
    last_polled_at = observed_at
    last_polled_wallclock_ms = observed_at_ms
    recently_played_cursor_ms = max(
        recently_played_cursor_ms, observed_at_ms
    )

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