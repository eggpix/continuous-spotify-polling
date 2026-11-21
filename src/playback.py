import time
from datetime import datetime, timezone

import spotify
from event_storage import save_event


TIME_MARGIN_MS = 2_000 # Time to account for polling inconsistencies
SCRUB_THRESHOLD_MS = 1_000 # Maximum allowed backward user scrub before events separate
FORWARD_SCRUB_THRESHOLD_MS = 10_000 # Maximum allowed forward user scrub before events separate
MISSING_TRACK_GRACE_MS = 120_000 # If Spotify stops returning a currently playing track,
                                 # wait for 2 minutes before adding it to the database
                                 # (If the playback stops, don't immediately log the event)


def timestamp_to_datetime(timestamp, fallback):
    if timestamp is None:
        return fallback
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc)


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


def playback_was_restarted(
    event, progress, timestamp,
    elapsed_ms
):
    """
    Function to check if playback was moved back or forward more than the expected amount
    """
    previous_progress = event["last_progress_ms"]
    previous_timestamp = event["last_timestamp"]

    if progress is None or previous_progress is None:
        return False

    # Return true if playback moved back by more than the scrub threshold
    if progress < previous_progress - SCRUB_THRESHOLD_MS:
        timestamp_changed = (
            timestamp is None
            or previous_timestamp is None
            or timestamp > previous_timestamp
        )
        return timestamp_changed

    # Return true if playback moved forward by more than the forward scrub threshold
    if progress > (
        previous_progress + elapsed_ms + FORWARD_SCRUB_THRESHOLD_MS
    ):
        return True

    return False


class PlaybackTracker:
    def __init__(self, recent_history):
        self.recent_history = recent_history
        self.current_event = None # Information on current playback event
        self.last_polled_at = time.monotonic()
        self.last_polled_wallclock_ms = int(time.time() * 1000)
        self.last_playing_at = self.last_polled_at
        self.last_poll_was_playing = False
        self.history_recovery_pending = False

    def poll(self, sp, db):
        """
        Call Spotify API, executes once every polling loop
        """
        playback = spotify.get_currently_playing(sp)
        observed_at = time.monotonic() # Time of poll (for measuring elapsed time)
        elapsed_ms = (observed_at - self.last_polled_at) * 1000 # Time since last poll
        current_time = datetime.now(timezone.utc) # Current datetime in UTC
        observed_at_ms = int(time.time() * 1000) # Time of poll (Unix Epock time in ms)

        is_playing = bool(playback and playback.get("is_playing"))
        item = playback.get("item") if playback else None # Current playback item
        track = item if item and item.get("type") == "track" else None # Only counts tracks (exclude podcasts)
        track_id = track.get("id") if track else None
        progress = playback.get("progress_ms") if playback else None # Current track progress
        timestamp = playback.get("timestamp") if playback else None # Time since last playback event

        previous_event = self.current_event # Save event info before current one is modified
        history_recovery_pending = (
            self.history_recovery_pending and track_id is not None
        )
        restarted = self._playback_was_restarted(
            track_id, progress, timestamp, elapsed_ms
        ) # Check if playback restarted or changed more than allowed amount

        missing_expired = self._missing_track_expired(observed_at)
        track_changed = self._track_changed(track_id)
        recovery_pending = track_changed or restarted or missing_expired

        if recovery_pending:
            self.finish_event(
                0 if restarted or missing_expired else elapsed_ms,
                db,
                timestamp_to_datetime(timestamp, current_time)
            )

        if recovery_pending or history_recovery_pending or track_id is None:
            self.history_recovery_pending = True

        if is_playing:
            self.last_playing_at = observed_at

        if is_playing and track_id:
            self._update_playing_event(
                track,
                progress,
                timestamp,
                observed_at_ms,
                elapsed_ms,
                restarted,
                current_time
            )
        elif track_id and self.current_event is not None:
            update_event_from_playback(
                self.current_event, track, progress, timestamp
            )

        self._recover_history(
            sp,
            db,
            track_id,
            is_playing,
            recovery_pending,
            previous_event,
            observed_at,
            history_recovery_pending
        )
        if track_id is None:
            self.history_recovery_pending = True
        elif self.history_recovery_pending:
            self.history_recovery_pending = False
        self._remember_poll(observed_at, observed_at_ms, is_playing)

    def finish_event(self, elapsed_ms, db, ended_at=None):
        if self.current_event is None:
            return

        event = self.current_event
        if ended_at is None:
            ended_at = datetime.now(timezone.utc)
        if ended_at < event["started_at"]:
            ended_at = event["started_at"]
        event["ended_at"] = ended_at

        end = event["playback_end"]
        duration = event["duration_ms"]
        if end is not None and self.last_poll_was_playing:
            if end >= duration - elapsed_ms - TIME_MARGIN_MS:
                end = duration
            else:
                end = min(end + elapsed_ms / 2, duration)

        if end is not None:
            start = event["playback_start"] or 0
            event["playback_end"] = max(start, int(end))

        save_event(db, event)
        self.recent_history.remember_live_event(event, ended_at)
        print(f"Recorded: {event['track_name']}")
        self.current_event = None

    def close(self, db):
        if self.current_event is None:
            return
        elapsed_ms = (time.monotonic() - self.last_polled_at) * 1000
        self.finish_event(elapsed_ms, db)

    def _playback_was_restarted(
        self, track_id, progress, timestamp, elapsed_ms
    ):
        return (
            self.current_event is not None
            and track_id == self.current_event["track_id"]
            and playback_was_restarted(
                self.current_event,
                progress,
                timestamp,
                elapsed_ms
            )
        )

    def _missing_track_expired(self, observed_at):
        return (
            self.current_event is not None
            and self.current_event["missing_since"] is not None
            and (observed_at - self.current_event["missing_since"]) * 1000
            >= MISSING_TRACK_GRACE_MS
        )

    def _track_changed(self, track_id):
        return (
            self.current_event is not None
            and track_id is not None
            and track_id != self.current_event["track_id"]
        )

    def _update_playing_event(
        self, track, progress, timestamp, observed_at_ms,
        elapsed_ms, restarted, current_time
    ):
        if self.current_event is None:
            start = self._new_event_start(
                progress, timestamp, observed_at_ms, elapsed_ms, restarted
            )
            self.current_event = {
                "track_id": track["id"],
                "track_name": track["name"],
                "track": track,
                "started_at": timestamp_to_datetime(
                    timestamp, current_time
                ),
                "playback_start": int(start) if start is not None else None,
                "playback_end": progress,
                "duration_ms": track["duration_ms"],
                "last_progress_ms": progress,
                "last_timestamp": timestamp,
                "missing_since": None,
            }
        else:
            update_event_from_playback(
                self.current_event, track, progress, timestamp
            )

    def _new_event_start(
        self, progress, timestamp, observed_at_ms, elapsed_ms, restarted
    ):
        if restarted and progress is not None:
            return restarted_event_start(
                progress, timestamp, observed_at_ms
            )

        if (
            timestamp is not None
            and timestamp >= self.last_polled_wallclock_ms - TIME_MARGIN_MS
            and progress is not None
            and abs((observed_at_ms - timestamp) - progress) <= TIME_MARGIN_MS
        ):
            return 0

        if not self.last_poll_was_playing and progress is not None:
            return progress
        if progress is None:
            return None
        if progress <= elapsed_ms + TIME_MARGIN_MS:
            return 0
        return max(progress - elapsed_ms / 2, 0)

    def _recover_history(
        self, sp, db, track_id, is_playing, recovery_pending, previous_event,
        observed_at, history_recovery_pending
    ):
        if recovery_pending or history_recovery_pending:
            active_event = (
                self.current_event if is_playing and track_id else None
            )
            self.recent_history.recover(
                sp, db, previous_event, active_event
            )
        elif track_id is None:
            if (
                self.current_event is not None
                and self.current_event["missing_since"] is None
            ):
                self.current_event["missing_since"] = observed_at
            self.recent_history.recover(sp, db, self.current_event)

    def _remember_poll(self, observed_at, observed_at_ms, is_playing):
        self.last_poll_was_playing = is_playing
        self.last_polled_at = observed_at
        self.last_polled_wallclock_ms = observed_at_ms
