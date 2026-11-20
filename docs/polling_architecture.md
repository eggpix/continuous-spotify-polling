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
  new event for the same track. A forward jump beyond expected progress plus
  ten seconds also starts a new event.
- Track changes, seeks, and polls with no current track trigger a
  recently-played lookup to recover tracks that may have started and finished
  between polls. Recovery is retried when a track returns after a no-track
  period. Occurrences matching the live event and the event being closed are
  excluded. The timestamp cursor advances only through returned history, with
  an overlap to deduplicate results; an empty response does not move it forward.
- Recovered tracks are stored with their full Spotify metadata and `played_at`.
  Based on the observed recently-played behavior, they are recorded as full
  plays with offsets from zero to the track duration. Their `started_at` uses
  `played_at`, which may represent the history timestamp rather than the exact
  track start.

The current-playback timestamp is used as the best available event-boundary
time. Progress and poll timing estimate offsets for live events; they cannot
prove exact listening duration when polling misses state changes.

## Code organization

- `src/playback.py` tracks active playback events and state transitions.
- `src/recent_history.py` reconciles recent-played results with live events.
- `src/event_storage.py` writes track metadata and playback events.
- `src/main.py` connects the services and runs the polling loop.

## Poll intervals

Polling is every 20 seconds while recently active, 60 seconds after one minute
of inactivity, and 180 seconds after three minutes. The recently-played
endpoint is queried at event boundaries and while no track is available,
rather than alongside every active-track poll.
