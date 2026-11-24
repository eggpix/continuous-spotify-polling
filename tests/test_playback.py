import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import playback


class FakeDatabase:
    def __init__(self):
        self.events = []
        self.rollbacks = 0

    def insert_track(self, track):
        pass

    def insert_event(self, *event):
        self.events.append(event)

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1


def make_track(track_id, duration_ms=180_000):
    return {
        "id": track_id,
        "name": track_id,
        "duration_ms": duration_ms,
        "type": "track",
    }


def make_playback(track_id, progress_ms, is_playing=True):
    return {
        "item": make_track(track_id),
        "progress_ms": progress_ms,
        "is_playing": is_playing,
    }


class PlaybackRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = playback.PlaybackTracker()
        self.db = FakeDatabase()
        self.tracker.last_polled_time = 100
        self.current_patch = patch.object(
            playback.spotify, "get_currently_playing"
        )
        self.recent_patch = patch.object(
            playback.spotify,
            "get_recently_played",
            return_value={"items": []},
        )
        self.current_mock = self.current_patch.start()
        self.recent_patch.start()
        self.addCleanup(self.current_patch.stop)
        self.addCleanup(self.recent_patch.stop)

    def test_track_change_ends_old_event_and_starts_new_event(self):
        self.current_mock.side_effect = [
            make_playback("A", 20_000),
            make_playback("B", 5_000),
        ]

        with patch.object(playback.time, "monotonic", side_effect=[101, 104]):
            self.tracker.poll(object(), self.db)
            self.tracker.poll(object(), self.db)

        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.db.events[0][0], "A")
        self.assertEqual(self.tracker.current_event.track["id"], "B")

    def test_backward_scrub_splits_current_event(self):
        self.current_mock.side_effect = [
            make_playback("A", 30_000),
            make_playback("A", 5_000),
        ]

        with patch.object(playback.time, "monotonic", side_effect=[101, 102]):
            self.tracker.poll(object(), self.db)
            self.tracker.poll(object(), self.db)

        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.tracker.current_event.progress, 5_000)

    def test_missing_track_does_not_end_event_before_timeout(self):
        self.current_mock.side_effect = [
            make_playback("A", 20_000),
            None,
        ]

        with patch.object(playback.time, "monotonic", side_effect=[101, 102]):
            self.tracker.poll(object(), self.db)
            self.tracker.poll(object(), self.db)

        self.assertIsNotNone(self.tracker.current_event)
        self.assertEqual(self.db.events, [])

    def test_log_event_rolls_back_when_database_insert_fails(self):
        def fail(_track):
            raise RuntimeError("insert failed")

        self.db.insert_track = fail

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            self.tracker.log_event(
                self.db,
                make_track("A"),
                datetime.now(timezone.utc),
                0,
                100,
            )

        self.assertEqual(self.db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()