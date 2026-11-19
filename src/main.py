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
recent_event_match_window_ms = 2000

current_event = None

last_polled_at = time.monotonic()
last_polled_wallclock_ms = int(time.time() * 1000)
recently_played_session_start_ms = last_polled_wallclock_ms
last_playing_at = last_polled_at
last_poll_was_playing = False
recently_played_cursor_ms = last_polled_wallclock_ms
recently_played_seen = {}
recently_played_live_events = []


def timestamp_to_datetime(timestamp, fallback):
    if timestamp is None:
        return fallback
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc)


def datetime_to_timestamp(value):
    return int(value.timestamp() * 1000)


def recent_play_matches_interval(
    track_id, played_at_ms, event_track_id, start_ms, end_ms
):
    return (
        track_id == event_track_id
        and start_ms - recent_event_match_window_ms
        <= played_at_ms
        <= end_ms + recent_event_match_window_ms
    )


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


def recover_recently_played(
    sp, db, previous_event=None, active_event=None
):
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

    now_ms = int(time.time() * 1000)
    event_intervals = set(recently_played_live_events)
    for event in (previous_event, active_event):
        if event is not None:
            start_ms = datetime_to_timestamp(event["started_at"])
            ended_at = event.get("ended_at")
            end_ms = datetime_to_timestamp(ended_at) if ended_at else now_ms
            event_intervals.add((event["track_id"], start_ms, end_ms))

    skipped_occurrences = set()
    for event_track_id, start_ms, end_ms in sorted(
        event_intervals, key=lambda event: event[1]
    ):
        candidates = [
            (index, item)
            for index, item in enumerate(dated_items)
            if (item[1].get("track") or {}).get("id") == event_track_id
            and (event_track_id, item[0]) not in skipped_occurrences
            and recent_play_matches_interval(
                event_track_id,
                item[0],
                event_track_id,
                start_ms,
                end_ms
            )
        ]
        if candidates:
            _, matching_item = min(
                candidates,
                key=lambda candidate: abs(candidate[1][0] - start_ms)
            )
            skipped_occurrences.add(
                (event_track_id, matching_item[0])
            )

    for played_at_ms, item, played_at in dated_items:
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

        if (track_id, played_at_ms) in skipped_occurrences:
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
    recently_played_live_events[:] = [
        event
        for event in recently_played_live_events
        if event[2] >= cutoff_ms - recent_event_match_window_ms
    ]


def finish_event(elapsed_ms, db, ended_at=None):
    global current_event

    if current_event is None:
        return

    event = current_event
    if ended_at is None:
        ended_at = datetime.now(timezone.utc)
    if ended_at < event["started_at"]:
        ended_at = event["started_at"]
    event["ended_at"] = ended_at
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
    ended_at_ms = datetime_to_timestamp(ended_at)
    recently_played_seen[(event["track_id"], started_at_ms)] = started_at_ms
    recently_played_live_events.append(
        (event["track_id"], started_at_ms, ended_at_ms)
    )

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
    recovery_pending = False

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
        finish_event(
            0 if restarted or missing_expired else elapsed_ms,
            db,
            timestamp_to_datetime(timestamp, current_time)
        )
        recovery_pending = True

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
    if recovery_pending:
        recover_recently_played(
            sp,
            db,
            previous_event,
            current_event if is_playing and track_id else None
        )
    elif track_id is None:
        if current_event is not None and current_event["missing_since"] is None:
            current_event["missing_since"] = observed_at
        recover_recently_played(sp, db, current_event)

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