import time
from datetime import datetime, timezone, timedelta

import spotify

FORWARD_SCRUB_THRESHOLD_MS = 10_000
BACKWARD_SCRUB_THRESHOLD_MS = 2_000
TRACK_PAUSE_TIMEOUT = 180

class PlaybackEvent:
    def __init__(self, track_id, started_at, playback_start, duration):
        self.track_id = track_id
        self.started_at = started_at
        self.playback_start = playback_start
        self.playback_end = None

        self.duration = duration
        self.progress = 0
    
    def end(self, playback_end):
        self.playback_end = playback_end
    

class PlaybackTracker:
    def __init__(self):
        self.last_polled_time = time.monotonic()
        self.last_playing_time = time.time() # Last time a track was playing
        self.playing = False # Is a track currently playing
        self.current_event = None # Current playback event

    def start_event(self, playback, track, elapsed_time, now_utc):
        current_progress = playback.get("progress_ms")
        estimated_start_progress = max(0, current_progress - elapsed_time * 500)
        self.current_event = PlaybackEvent(
            track.get("id"),
            now_utc - timedelta(seconds=elapsed_time / 2),
            estimated_start_progress,
            track.get("duration_ms")
        )

    def end_event(self, playback, elapsed_time):
        current_progress = playback.get("progress_ms")
        estimated_end_progress = min(self.current_event.duration, current_progress - elapsed_time * 500)
        self.current_event.playback_end = estimated_end_progress

        # TODO STORE EVENT IN DATABASE

        self.current_event = None

    def close(self):
        pass
        # TODO CLOSE EVENT

    def poll(self, sp, db):
        """
        Call Spotify API, executes once every polling loop
        """
        observed_time = time.monotonic() # Time of this poll for measuring elapsed time
        elapsed_time = observed_time - self.last_polled_time # Time since last poll
        halfway_time = observed_time - elapsed_time / 2 # Halfway between this poll and the last poll
        now_utc = datetime.now(timezone.utc)

        playback = spotify.get_currently_playing(sp) # Currently playing endpoint
        if (
            playback is not None and
            playback.get("item") is not None and
            playback.get("item").get("type") == "track" and
            playback.get("is_playing")
        ):
            track = playback.get("item")
            if not self.playing:
                self.playing = True
                if self.last_playing_time > TRACK_PAUSE_TIMEOUT:
                    self.start_event(playback, track, elapsed_time, now_utc)
            elif not track.get("id") == self.current_event.track_id:
                self.end_event(playback, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)

            # Check for user playback scrubs
            current_progress = track.get("progress_ms") - elapsed_time * 500
            previous_progress = self.current_event.progress

            if current_progress < previous_progress - BACKWARD_SCRUB_THRESHOLD_MS:
                self.end_event(playback, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)

            if current_progress > previous_progress + elapsed_time + FORWARD_SCRUB_THRESHOLD_MS:
                self.end_event(playback, elapsed_time)
                self.start_event(playback, track, elapsed_time, now_utc)
            
            self.current_event.progress = track.get("progress_ms") - elapsed_time * 500
        else:
            if self.playing:
                self.playing = False
                self.last_playing_time = halfway_time
            elif halfway_time - self.last_playing_time > TRACK_PAUSE_TIMEOUT:
                self.end_event(playback, elapsed_time)

            # TODO RECOVER RECENT TRACKS

        self.last_polled_time = time.monotonic()
