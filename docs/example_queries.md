# Example Queries

## Top Tracks by Listening Time

Retrieve the user's top tracks by total minutes listened.

```sql
SELECT
    t.name AS track_name,
    al.name AS album_name,
    ROUND(
        SUM(
            GREATEST(
                COALESCE(ph.playback_end, t.duration_ms)
                - COALESCE(ph.playback_start, 0),
                0
            )
        ) / 60000.0,
        2
    ) AS total_minutes_listened
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN albums al
    ON al.id = t.album_id
WHERE
    ph.started_at >= TIMESTAMPTZ '2026-01-01 00:00:00 America/Phoenix'
    AND ph.started_at < TIMESTAMPTZ '2027-01-01 00:00:00 America/Phoenix'
GROUP BY
    t.id,
    t.name,
    al.name
ORDER BY
    total_minutes_listened DESC;
```

[View Query File ](../sql/top_tracks.sql)

## Top Albums by Listening Time

```sql
SELECT
    al.name AS album_name,
    ROUND(
        SUM(
            GREATEST(
                COALESCE(ph.playback_end, t.duration_ms)
                - COALESCE(ph.playback_start, 0),
                0
            )
        ) / 60000.0,
        2
    ) AS total_minutes_listened
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN albums al
    ON al.id = t.album_id
WHERE
    ph.started_at >= TIMESTAMPTZ '2026-01-01 00:00:00 America/Phoenix'
    AND ph.started_at < TIMESTAMPTZ '2027-01-01 00:00:00 America/Phoenix'
GROUP BY
    al.id,
    al.name
ORDER BY
    total_minutes_listened DESC;
```

[View Query File ](../sql/top_albums.sql)

## Top Artists by Listening Time

Retrieve the user's top artists by total minutes listened.

```sql
SELECT
    ar.name AS artist_name,
    ROUND(
        SUM(
            GREATEST(
                COALESCE(ph.playback_end, t.duration_ms)
                - COALESCE(ph.playback_start, 0),
                0
            )
        ) / 60000.0,
        2
    ) AS total_minutes_listened
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN track_artists ta
    ON ta.track_id = t.id
JOIN artists ar
    ON ar.id = ta.artist_id
GROUP BY
    ar.id,
    ar.name
ORDER BY
    total_minutes_listened DESC;
```

[View Query File ](../sql/top_artists.sql)

## Get Recent Playback Events

```sql
SELECT
    t.name AS track_name,
    al.name AS album_name,
    ph.started_at AT TIME ZONE 'America/Phoenix' AS start_date,
    ROUND(
        GREATEST(
            COALESCE(ph.playback_end, t.duration_ms)
            - COALESCE(ph.playback_start, 0),
            0
        ) / 60000.0,
        2
    ) AS listening_minutes
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN albums al
    ON al.id = t.album_id
ORDER BY
    ph.started_at DESC;
```

[View Query File ](../sql/recent_events.sql)
