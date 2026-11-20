import time
from datetime import datetime, timezone

import spotify
from event_storage import save_event


RECENTLY_PLAYED_OVERLAP_MS = 120_000
RECENT_EVENT_MATCH_WINDOW_MS = 2_000


def datetime_to_timestamp(value):
    return int(value.timestamp() * 1000)


def recent_play_matches_interval(
    track_id, played_at_ms, event_track_id, start_ms, end_ms
):
    return (
        track_id == event_track_id
        and start_ms - RECENT_EVENT_MATCH_WINDOW_MS
        <= played_at_ms
        <= end_ms + RECENT_EVENT_MATCH_WINDOW_MS
    )


class RecentHistory:
    def __init__(self, session_start_ms=None):
        if session_start_ms is None:
            session_start_ms = int(time.time() * 1000)

        self.session_start_ms = session_start_ms
        self.cursor_ms = session_start_ms
        self.seen = {}
        self.live_events = []

    def remember_live_event(self, event, ended_at):
        started_at_ms = datetime_to_timestamp(event["started_at"])
        ended_at_ms = datetime_to_timestamp(ended_at)
        self.seen[(event["track_id"], started_at_ms)] = started_at_ms
        self.live_events.append(
            (event["track_id"], started_at_ms, ended_at_ms)
        )

    def advance_cursor(self, timestamp_ms):
        self.cursor_ms = max(self.cursor_ms, timestamp_ms)

    def recover(self, sp, db, previous_event=None, active_event=None):
        response = spotify.get_recently_played(
            sp,
            after=max(0, self.cursor_ms - RECENTLY_PLAYED_OVERLAP_MS)
        )
        dated_items = self._dated_items(response.get("items", []))
        event_intervals = self._event_intervals(
            previous_event, active_event
        )
        skipped_occurrences = self._matching_occurrences(
            dated_items, event_intervals
        )

        self._save_unmatched_items(
            dated_items, skipped_occurrences, db
        )
        self._prune_old_occurrences()

    @staticmethod
    def _dated_items(items):
        dated_items = []
        for item in items:
            played_at = datetime.fromisoformat(
                item["played_at"].replace("Z", "+00:00")
            )
            if played_at.tzinfo is None:
                played_at = played_at.replace(tzinfo=timezone.utc)
            dated_items.append(
                (datetime_to_timestamp(played_at), item, played_at)
            )
        return sorted(dated_items, key=lambda result: result[0])

    def _event_intervals(self, previous_event, active_event):
        now_ms = int(time.time() * 1000)
        intervals = set(self.live_events)

        for event in (previous_event, active_event):
            if event is None:
                continue
            start_ms = datetime_to_timestamp(event["started_at"])
            ended_at = event.get("ended_at")
            end_ms = (
                datetime_to_timestamp(ended_at) if ended_at else now_ms
            )
            intervals.add((event["track_id"], start_ms, end_ms))

        return sorted(intervals, key=lambda event: event[1])

    @staticmethod
    def _matching_occurrences(dated_items, event_intervals):
        skipped = set()

        for event_track_id, start_ms, end_ms in event_intervals:
            candidates = [
                item
                for item in dated_items
                if (item[1].get("track") or {}).get("id") == event_track_id
                and (event_track_id, item[0]) not in skipped
                and recent_play_matches_interval(
                    event_track_id,
                    item[0],
                    event_track_id,
                    start_ms,
                    end_ms
                )
            ]
            if candidates:
                matching_item = min(
                    candidates,
                    key=lambda item: abs(item[0] - start_ms)
                )
                skipped.add((event_track_id, matching_item[0]))

        return skipped

    def _save_unmatched_items(self, dated_items, skipped, db):
        for played_at_ms, item, played_at in dated_items:
            track = item.get("track") or {}
            track_id = track.get("id")
            key = (track_id, played_at_ms)

            if played_at_ms < self.session_start_ms or key in self.seen:
                self.advance_cursor(played_at_ms)
                continue

            if key in skipped:
                self.seen[key] = played_at_ms
                self.advance_cursor(played_at_ms)
                continue
            if track.get("type") != "track" or not track_id:
                self.seen[key] = played_at_ms
                self.advance_cursor(played_at_ms)
                continue

            event = {
                "track_id": track_id,
                "track_name": track["name"],
                "track": track,
                "started_at": played_at,
                "playback_start": 0,
                "playback_end": track["duration_ms"],
                "duration_ms": track["duration_ms"],
            }
            save_event(db, event)
            self.seen[key] = played_at_ms
            self.advance_cursor(played_at_ms)
            print(f"Recovered from history: {event['track_name']}")

    def _prune_old_occurrences(self):
        cutoff_ms = self.cursor_ms - RECENTLY_PLAYED_OVERLAP_MS
        self.seen = {
            key: timestamp
            for key, timestamp in self.seen.items()
            if timestamp >= cutoff_ms
        }
        self.live_events = [
            event
            for event in self.live_events
            if event[2] >= cutoff_ms - RECENT_EVENT_MATCH_WINDOW_MS
        ]
