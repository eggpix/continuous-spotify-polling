# Polling Architecture

The goal of this code is to continuously poll Spotify’s API and detect the current playback state of the user, then use this information to reconstruct the playback history of the user stored in a relational database. Playback history is stored as playback events, which are defined as sessions of advancing playback without significant skips or scrubs. Pauses and exits separate tracks into different events if they last more than a specified period. Only tracks are stored; podcasts are excluded from the database.

## Table Fields

The table containing playback event history contains the following fields:

- `event_id`  
  Unique ID used to distinguish each playback event.

- `track_id`  
  Foreign key referencing a track in the `tracks` table.

- `started_at`  
  The wall clock timestamp when a playback event began.

- `playback_start`  
  The progress, in milliseconds, through a song when playback for this event began. If a song is played from start to finish, this value will be zero.

- `playback_end`  
  The progress, in milliseconds, through a song when playback for this event ended. If a song is played from start to finish, this value will equal the length of the track in milliseconds.


## Polling Interval

One request to the Spotify API occurs once every 20, 60, or 180 seconds as defined by the code. The time interval depends on when a track was last estimated to be actively playing. Other user events like playing podcasts or scrubbing a track are not counted toward this calculation. The polling intervals defined in the code are as follows:

- Recently active — poll every 20 seconds

- Inactive for 60 seconds or more — poll every 60 seconds

- Inactive for 300 seconds or more — poll every 180 seconds

## Event Change Estimation

When a new song is started, its actual start time and starting progress can only be estimated, since polling happens in discrete intervals. For estimating the playback start wall clock timestamp, the playback start progress, and the playback end progress, each event is assumed to have occurred halfway between the current poll time and the last. This logic also applies for calculating the correct polling interval.

The exception to this rule is in filling in missing tracks from the recently played tracks endpoint. This endpoint only retrieves tracks played to the end of a song, not ones that are skipped. Since playback could have started any time within a polling gap, the whole period should be checked when comparing to the song started at value.

## Recording Playback Events

Playback events aren’t recorded in the database until the song is no longer playing. If the player returns a different item than the current track, the event is ended immediately and stored according to the estimated halfway time. If the user has simply paused the song, or the client stops returning the currently played item, wait for 180 seconds and then end the event. If the event resumes within that time period, keep recording on the same event and end when appropriate.

If a new song is noticed by an API request but the song is paused, don’t start a new event yet. Store the old track and update the polling interval if applicable, but wait until the poll notices the song playing and then start the event at the halfway point.

Events can also be ended if the user scrubs more than the allowed amount. If the user scrubs or seeks to a playback progress less than the previously polled progress minus 2,000 milliseconds, or past the previously polled progress, plus the elapsed time, plus 10,000 milliseconds, the event is ended and a new one is started for the same song. A new event is only created if the song is playing while beyond the acceptable bounds, not if it is paused. Likewise, previously polled progress is only stored as the last estimated playback progress while the song was playing.

## Recovering Missing Tracks

With a polling period as high as 180 seconds, it’s likely a song may be missed due to infrequent polling. While the nature of the recently played endpoint prevents recovery of skipped songs, songs played to completion can be noticed and added to the database on the next poll. This can also be used to recover songs played from downloads while offline.

First, on every poll, check the last time the user’s Spotify client was active. The last active time value should be based on the last time the “currently playing” endpoint returned an item of any type. As mentioned in *Event Change Estimation*,  The last active time value should be rounded down to the nearest poll time to capture every potential playback start. Add any songs to the database returned during this period up to the current poll time. The starting time should be based on the value returned by Spotify’s API, and the playback start and end times should be 0 and the length of the song respectively.

## Code organization

- `src/playback.py`  
  Tracks active playback events and state transitions.

- `src/recent_history.py`  
  Reconciles recent-played results with live events.

- `src/event_storage.py`  
  Writes track metadata and playback events.

- `src/main.py`  
  Connects the services and runs the polling loop.
