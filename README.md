# Continuous Spotfy Polling

A limitation of my
[Spotify Music Analytics](https://github.com/eggpix/spotify-music-analytics/)
project is that Spotify only provides limited
access to track playback history. Only songs
listened to completion are counted, while anything
that's skipped is discarded. This project continuously
requests data from Spotify's API to extract more precise
information on listening habits.

While Spotify does not send total playback duration
for a recently played songs, it does send current
information on playback, such as the current playback time
in milliseconds. Combining this information with data from
the recently played tracks endpoint, it's possible to
extract detailed listening behavior analytics with relatively
infrequent polling.

To prevent rate limitting from the Spotify Web API,
polling intervals dynamically adjust to user activity.
When a user is currently listening to a track, data is
retrieved more frequently than if they haven't used
Spotify for an hour. Missing track information may be
filled in by comparing playback request info to recently
played tracks.

## Usage

Install the Python dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

Run the file with the following command:

Install the Python dependencies from the repository root:

```bash
python main.py
```

The program will begin looping and polling periodically.

Follow Instructions from [Spotify Music Analytics](https://github.com/eggpix/spotify-music-analytics/) to install in a remote database.