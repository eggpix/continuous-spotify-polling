# Polling Architecture

This file describes the method and frequency of requesting and logging data from the Spotify API. The most relevant endpoint exposed by the Spotify API is `GET /me/player`. The responses used to calculate user activity are as follows:

### is_playing `boolean`

Returns a boolean value representing the playback state of the user. Used by the program to detect user activity and vary the polling interval. Periodically polled at a default rate of 10, 30, or 90 seconds depending on user activity.

### timestamp `integer`

Unix ms timestamp when playback state was last changed. Used to improve calculation of song playback end duration. Spotify lists the reasons for a timestamp change as "play, pause, skip, scrub, new song, etc.". May be used to estimate started_at, playback_start, and playback_end values.

### progress_ms `integer`

Current playback progress. Especially useful for estimating started_at, playback_start, and playback_end values. More frequent polling increases accuracy for those values.

### item `oneOf`

Information on the currently playing track. Used to fill the track_id field in the playback_history table. Additional data pulled from the Spotify API can be used to fill in the remaining tables.