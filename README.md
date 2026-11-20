# Continuous Spotfy Polling

A limitation of my [Spotify Music Analytics](https://github.com/eggpix/spotify-music-analytics/) project is that Spotify only provides limited access to track playback history. Only songs listened to completion are counted, while anything that's skipped is discarded. This project continuously requests data from Spotify's API to extract more precise information on listening habits.

While Spotify does not send total playback duration for a recently played songs, it does send current information on playback, such as the current playback time in milliseconds. Combining this information with data from the recently played tracks endpoint, it's possible to extract detailed listening behavior analytics with relatively infrequent polling.

To prevent rate limitting from the Spotify Web API, polling intervals dynamically adjust to user activity. When a user is currently listening to a track, data is retrieved more frequently than if they haven't used Spotify for an hour. Missing track information may be filled in by comparing playback request info to recently played tracks.

## Usage

First, install the Python dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

After the requirements are installed, create a Spotify developer Web API app with the redirect URI set to `http://127.0.0.1:8888/callback`. Add the app information to your environment variables:

```dotenv
SPOTIPY_CLIENT_ID="your_client_id_here"
SPOTIPY_CLIENT_SECRET="your_client_secret_here"
SPOTIPY_REDIRECT_URI="http://127.0.0.1:8888/callback"
```

For a remote server, authorize once on a local machine and provide the
resulting `.cache` JSON as the `SPOTIPY_CACHE` environment variable on its first
start. The app copies it into a writable cache file and persists token refreshes
there. Set `SPOTIPY_CACHE_PATH` to a path on persistent storage (such as a
mounted volume) so refreshed credentials survive restarts. Keep both the
environment variable and cache file secret; the default cache path is
`.spotify-cache`. If authorization is revoked, reauthorize locally, update
`SPOTIPY_CACHE`, and replace or remove the persisted cache file before
restarting; an existing cache file takes precedence over the environment value.

Create a database and add the relevant information to the environment variables.

```dotenv
PGHOST="localhost"
PGPORT="5432"
PGDATABASE="spotify_music_analytics"
PGUSER="postgres"
PGPASSWORD="your_local_postgres_password"
```

Or, if using a remote database:

```dotenv
DATABASE_URL="your_connection_url_here"
```

finally, run the file with the following command:

```bash
python src/main.py
```

The program will begin looping and polling the Spotify API periodically. As described in [Polling Architecture](docs/polling_architecture.md), the polling interval changes dynamically to reduce API usage.

## Query your data

Connect a PostgreSQL client, such as pgAdmin, to the same database you configured for the importer and run one of the [example queries](docs/example_queries.md).