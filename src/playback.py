import time
from datetime import datetime, timezone, timedelta

import spotify

FORWARD_SCRUB_THRESHOLD_MS = 10_000
BACKWARD_SCRUB_THRESHOLD_MS = 2_000
TRACK_PAUSE_TIMEOUT = 180

class PlaybackEvent:
    def __init__(self, track, started_at, playback_start, progress):
        self.track = track
        self.started_at = started_at
        self.playback_start = playback_start

        self.progress = progress
        self.last_progress_polling_gap = None

class PlaybackTracker:
    def __init__(self):
        self.last_polled_time = time.monotonic()
        self.last_playing_time = time.monotonic() # Last time a track was playing
        self.current_event = None # Current playback event

        self.last_active_wall_clock = time.time() # For use in getting recent tracks

    def start_event(self, playback, track, elapsed_time, now_utc):
        current_progress = playback.get("progress_ms")
        if current_progress is None:
            current_progress = 0
        estimated_start_progress = max(0, current_progress - elapsed_time * 500)
        self.current_event = PlaybackEvent(
            track,
            now_utc - timedelta(seconds=elapsed_time / 2),
            estimated_start_progress,
            current_progress
        )

    def log_event(self, db, track, started_at, playback_start, playback_end):
        try:
            db.insert_track(track)
            db.insert_event(
                track.get("id"),
                started_at,
                playback_start,
                playback_end
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    def end_event(self, db, elapsed_time=None):
        if elapsed_time is None:
            elapsed_time = time.monotonic() - self.last_polled_time
        if self.current_event is None:
            return
        
        end_progress = self.current_event.progress # Final polled progress
        playback_end = min(self.current_event.track.get("duration_ms"), end_progress + elapsed_time * 500)

        self.log_event(
            db,
            self.current_event.track,
            self.current_event.started_at,
            self.current_event.playback_start,
            playback_end
        )

        print(
            f"Stored track {self.current_event.track.get('id')}\n"
            f"\tName: {self.current_event.track.get('name')}\n"
            f"\tDuration: {self.current_event.track.get('duration_ms')}\n"
            f"\tStarted At: {self.current_event.started_at}\n"
            f"\tPlayback Start: {self.current_event.playback_start}\n"
            f"\tPlayback End: {playback_end}"
        )

        self.current_event = None

    def get_recent_tracks(self, sp, db):
        recent = spotify.get_recently_played(sp, after=int(self.last_active_wall_clock * 1000))

        cutoff = datetime.fromtimestamp(
            self.last_active_wall_clock,
            tz=timezone.utc
        )
        poll_time = datetime.now(tz=timezone.utc)

        for item in recent.get("items"):
            played_at = datetime.fromisoformat(
                item["played_at"].replace("Z", "+00:00")
            )
            if played_at <= cutoff:
                continue
            elif played_at + timedelta(milliseconds=item.get("track").get("duration_ms")) >= poll_time:
                continue

            self.log_event(
                db,
                item.get("track"),
                played_at,
                0.0,
                item.get("track").get("duration_ms")
            )

            print(
                f"Recovered track {item.get("track").get('id')} from recently played\n"
                f"\tName: {item.get("track").get('name')}\n"
                f"\tDuration: {item.get("track").get('duration_ms')}\n"
                f"\tStarted At: {played_at}"
            )

    def poll(self, sp, db):
        """
        Call Spotify API, executes once every polling loop
        """
        observed_time = time.monotonic() # Time of this poll for measuring elapsed time
        elapsed_time = observed_time - self.last_polled_time # Time since last poll
        self.last_polled_time = observed_time
        halfway_time = observed_time - elapsed_time / 2 # Halfway between this poll and the last poll
        now_utc = datetime.now(timezone.utc)

        playback = spotify.get_currently_playing(sp) # Currently playing endpoint

        self.get_recent_tracks(sp, db)

        user_active = (
            playback is not None and
            playback.get("item") is not None
        )

        is_actively_playing = (
            user_active and
            playback.get("item").get("type") == "track" and
            playback.get("is_playing")
        )

        if user_active:
            self.last_active_wall_clock = time.time()

        # If a track is currently playing:
        if is_actively_playing:
            self.last_playing_time = halfway_time

            track = playback.get("item")

            if self.current_event is None:
                self.start_event(playback, track, elapsed_time, now_utc)
                return

            self.current_event.last_progress_polling_gap = None
            
            current_progress = playback.get("progress_ms")
            previous_progress = self.current_event.progress
            if current_progress is None:
                current_progress = previous_progress

            # Check if song just started
            if not track.get("id") == self.current_event.track.get("id"):
                self.end_event(db, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)
                return

            # Check for user playback scrubs
            if current_progress < previous_progress - BACKWARD_SCRUB_THRESHOLD_MS:
                self.end_event(db, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)
                return

            if current_progress > previous_progress + elapsed_time * 1000 + FORWARD_SCRUB_THRESHOLD_MS:
                self.end_event(db, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)
                return
                
            self.current_event.progress = current_progress
        else:
            if self.current_event is not None:
                if self.current_event.last_progress_polling_gap is None:
                    self.current_event.last_progress_polling_gap = elapsed_time
                if (
                    playback is not None and
                    playback.get("item") is not None and
                    not playback.get("item").get("id") == self.current_event.track.get("id")
                ):
                    self.end_event(db, elapsed_time)
                elif (observed_time - self.last_playing_time > TRACK_PAUSE_TIMEOUT):
                    self.end_event(db, self.current_event.last_progress_polling_gap)
