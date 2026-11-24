import signal
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from spotipy.exceptions import SpotifyException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main


class MainRegressionTests(unittest.TestCase):
    def test_polling_interval_boundaries(self):
        self.assertEqual(main.polling_interval(0), 20)
        self.assertEqual(main.polling_interval(60_000), 60)
        self.assertEqual(main.polling_interval(300_000), 180)

    def test_rate_limit_retry_uses_header_and_clamps_negative_values(self):
        retry = SpotifyException(
            429, -1, "rate limited", headers={"Retry-After": "7"}
        )
        negative = SpotifyException(
            429, -1, "rate limited", headers={"Retry-After": "-2"}
        )
        invalid = SpotifyException(
            429, -1, "rate limited", headers={"Retry-After": "invalid"}
        )

        self.assertEqual(main.rate_limit_retry_after(retry), 7)
        self.assertEqual(main.rate_limit_retry_after(negative), 0)
        self.assertEqual(main.rate_limit_retry_after(invalid), 60)

    def test_sigterm_raises_keyboard_interrupt(self):
        with self.assertRaises(KeyboardInterrupt):
            main.handle_sigterm(signal.SIGTERM, None)

    def test_authorization_error_names_cache_location(self):
        with patch.dict(
            "os.environ", {"SPOTIPY_CACHE_PATH": "/tmp/test-cache"}, clear=False
        ):
            message = main.authorization_error_message()

        self.assertIn("/tmp/test-cache", message)
        self.assertIn("reauthorize", message.lower())

    def test_rate_limit_poll_waits_and_skips_normal_wait(self):
        tracker = Mock()
        error = SpotifyException(
            429, -1, "rate limited", headers={"Retry-After": "3"}
        )
        tracker.poll.side_effect = error

        with patch.object(main.time, "sleep") as sleep:
            result = main.poll_playback(tracker, object(), object())

        self.assertEqual(result, 1)
        sleep.assert_called_once_with(3)

    def test_oauth_error_is_converted_to_runtime_error(self):
        tracker = Mock()
        tracker.poll.side_effect = main.SpotifyOauthError("expired")

        with self.assertRaisesRegex(RuntimeError, "authorization failed"):
            main.poll_playback(tracker, object(), object())


if __name__ == "__main__":
    unittest.main()
