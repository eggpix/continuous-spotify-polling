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

## Program loop

The following pseudocode describes the actions performed during each API request.

```python
# Persistent variables between loops

time_last_played: TIMESTAMP = CURRENT TIME # Stores the last time is_playing was active
                                           # Begin at current time, using lowest polling interval

# Current track info
current_track_id: ID = None
current_track_started_at: TIMESTAMP = None
current_track_playback_start: INTEGER = None
current_track_playback_end: INTEGER = None


polling_intervals = { # Polling intervals depending on time since time_last_played

    0: 10,    # If user was recently active, poll every 10 seconds
    300, 30,  # If user has been inactive for 5+ minutes, poll every 30 seconds
    900, 90   # If user has been inactive for 15+ minutes, poll every 90 seconds

}

poll_interval = polling_intervals[0] # Current polling interval
                                     # Updated each loop

last_track: ID


retrieve_playback_data():

    new_track_id = get_spot_player( "item" ).get( "track_id" )

    IF  new_track_id != current_track_id:

        # Update the database with the previous track information
        add_to_database( INFO )

        current_track_id = new_track_id

    IF NOT get_spot_player( "is_playing" ):
        RETURN # No new data to log


# Main program loop
WHILE PROGRAM IS RUNNING:

    current_time = CURRENT TIME
    time_since_last = current_time - time_last_played

    retrieve_playback_data()

    # Get correct poll interval at this time
    FOR key, value IN REVERSED( polling_intervals.ITEMS() ):
        IF time_since_last >= key:
            poll_interval = value
            BREAK

    WAIT FOR poll_interval SECONDS
```