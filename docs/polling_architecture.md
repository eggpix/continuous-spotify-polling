# Polling Architecture

The poller combines Spotify's `GET /me/player/currently-playing` response with
`GET /me/player/recently-played`. The current-playback endpoint provides the
live track, `is_playing`, `progress_ms`, and a Unix-millisecond `timestamp` for
the last playback-state change. Recently played provides full track metadata
and a `played_at` timestamp, but not the playback offsets.

## Playback events

- One in-memory event is kept for the current track. Polls of that same track
  update the event rather than insert another row. Starting playback only
  creates in-memory state; the live event is written when it closes.
- Pauses and brief responses without a track keep the event open. If the track
  stays unavailable for two minutes, the event is closed; a different track
  closes it immediately. A graceful poller exit also closes the open event.
- A backward progress jump greater than one second, accompanied by a changed
  playback timestamp, is treated as a restart or backward seek and starts a
  new event for the same track. Forward seeks stay in the current event.
- Track changes, backward seeks, and polls with no current track trigger a
  recently-played lookup to recover tracks that may have started and finished
  between polls. Occurrences matching the live event and the event being
  closed are excluded; a timestamp cursor plus overlap deduplicates repeated
  API results.
- Recovered tracks are stored with their full Spotify metadata and `played_at`.
  Their playback offsets are `NULL`, because the recently-played endpoint does
  not reveal how much of those tracks was heard.

The current-playback timestamp is used as the best available event-boundary
time. Progress and poll timing estimate offsets for live events; they cannot
prove exact listening duration when polling misses state changes.

## Poll intervals

Polling is every 10 seconds while recently active, 30 seconds after one minute
of inactivity, and 90 seconds after fifteen minutes. The recently-played
endpoint is queried at event boundaries and while no track is available,
rather than alongside every active-track poll.
