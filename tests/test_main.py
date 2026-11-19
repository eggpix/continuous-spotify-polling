import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main


class FakeDatabase:
    def __init__(self):
        self.tracks = []
        self.events = []

    def insert_track(self, track):
        self.tracks.append(track)

    def insert_event(self, *event):
        self.events.append(event)

    def commit(self):
        pass


def make_track(track_id):
    return {
        "id": track_id,
        "name": track_id,
        "type": "track",
        "duration_ms": 180_000,
    }


def playback(track_id, progress, is_playing=True, timestamp=None):
    return {
        "is_playing": is_playing,
        "item": make_track(track_id),
        "progress_ms": progress,
        "timestamp": timestamp,
    }


class PlaybackEventTests(unittest.TestCase):
    def setUp(self):
        main.current_event = None
        main.last_polled_at = time.monotonic()
        main.last_polled_wallclock_ms = int(time.time() * 1000)
        main.recently_played_session_start_ms = main.last_polled_wallclock_ms
        main.last_playing_at = main.last_polled_at
        main.last_poll_was_playing = False
        main.recently_played_cursor_ms = main.last_polled_wallclock_ms
        main.recently_played_seen = {}
        self.db = FakeDatabase()
        self.current_playback = patch.object(
            main.spotify, "get_currently_playing"
        )
        self.current_playback_mock = self.current_playback.start()
        self.addCleanup(self.current_playback.stop)
        self.recent_playback = patch.object(
            main.spotify, "get_recently_played", return_value={"items": []}
        )
        self.recent_playback_mock = self.recent_playback.start()
        self.addCleanup(self.recent_playback.stop)

    def test_pause_and_brief_missing_item_do_not_split_event(self):
        timestamp = main.last_polled_wallclock_ms - 10_000
        self.current_playback_mock.side_effect = [
            playback("A", 20_000, timestamp=timestamp),
            playback("A", 20_000, is_playing=False, timestamp=timestamp + 1),
            None,
            playback("A", 21_000, timestamp=timestamp + 2),
        ]

        for _ in range(4):
            main.retrieve_playback_data(object(), self.db)

        self.assertEqual(self.db.events, [])
        self.assertEqual(main.current_event["track_id"], "A")
        self.assertEqual(main.current_event["playback_end"], 21_000)

    def test_backward_seek_splits_same_track_event(self):
        timestamp = main.last_polled_wallclock_ms - 5_000
        self.current_playback_mock.side_effect = [
            playback("A", 20_000, timestamp=timestamp),
            playback("A", 10_000, timestamp=timestamp + 5_000),
        ]

        main.retrieve_playback_data(object(), self.db)
        main.retrieve_playback_data(object(), self.db)

        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.db.events[0][0], "A")
        self.assertEqual(self.db.events[0][2:], (20_000, 20_000))
        self.assertAlmostEqual(
            main.current_event["playback_start"], 10_000, delta=1_000
        )

    def test_long_missing_track_closes_event(self):
        self.current_playback_mock.side_effect = [
            playback("A", 20_000),
            None,
        ]
        main.retrieve_playback_data(object(), self.db)
        main.current_event["missing_since"] = (
            time.monotonic() - main.missing_track_grace_ms / 1000 - 1
        )

        main.retrieve_playback_data(object(), self.db)

        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.db.events[0][0], "A")
        self.assertIsNone(main.current_event)

    def test_recently_played_recovers_only_unobserved_tracks_once(self):
        cursor = int(time.time() * 1000) - 60_000
        main.recently_played_session_start_ms = cursor

        def recent(track_id, offset_ms):
            played_at = datetime.fromtimestamp(
                (cursor + offset_ms) / 1000, timezone.utc
            )
            return {
                "track": make_track(track_id),
                "played_at": played_at.isoformat(),
            }

        items = [recent("A", 1_000), recent("B", 20_000), recent("C", 30_000)]
        started_at = datetime.fromtimestamp(
            (cursor + 1_000) / 1000, timezone.utc
        )
        current_playback = playback("C", 5_000, timestamp=cursor + 30_000)
        main.recently_played_cursor_ms = cursor
        main.recently_played_seen = {}
        self.recent_playback_mock.return_value = {"items": items}
        previous_event = {"track_id": "A", "started_at": started_at}

        main.recover_recently_played(
            object(), self.db, current_playback, previous_event
        )
        main.recover_recently_played(
            object(), self.db, current_playback, previous_event
        )

        self.assertEqual([track["id"] for track in self.db.tracks], ["B"])
        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.db.events[0][0], "B")
        self.assertIsNone(self.db.events[0][2])
        self.assertIsNone(self.db.events[0][3])

    def test_recently_played_recovers_track_when_no_item_is_current(self):
        cursor = main.last_polled_wallclock_ms
        played_at = datetime.fromtimestamp(
            (cursor + 1_000) / 1000, timezone.utc
        )
        main.recently_played_cursor_ms = cursor
        self.recent_playback_mock.return_value = {
            "items": [{
                "track": make_track("B"),
                "played_at": played_at.isoformat(),
            }]
        }
        self.current_playback_mock.return_value = None

        main.retrieve_playback_data(object(), self.db)

        self.assertEqual([track["id"] for track in self.db.tracks], ["B"])
        self.assertEqual([event[0] for event in self.db.events], ["B"])

    def test_recent_history_does_not_duplicate_a_saved_live_event(self):
        started_at = datetime.fromtimestamp(
            main.last_polled_wallclock_ms / 1000, timezone.utc
        )
        main.current_event = {
            "track_id": "A",
            "track_name": "A",
            "track": make_track("A"),
            "started_at": started_at,
            "playback_start": 0,
            "playback_end": 20_000,
            "duration_ms": 180_000,
        }
        self.recent_playback_mock.return_value = {
            "items": [{
                "track": make_track("A"),
                "played_at": started_at.isoformat(),
            }]
        }

        main.finish_event(0, self.db)
        main.recover_recently_played(object(), self.db, None)

        self.assertEqual(len(self.db.events), 1)
        self.assertEqual([track["id"] for track in self.db.tracks], ["A"])


if __name__ == "__main__":
    unittest.main()
